#!/usr/bin/env python3
"""Canonicalize a manifest-generated native CSV trace runner."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import subprocess
from typing import Any

from ssbm_natural_movement_domain import selected_trace_fields
from ssbm_live_trace import binary32


class NativeCsvTraceError(RuntimeError):
    """Raised when a native trace cannot be reproduced canonically."""


MAX_CASE_WORKERS = 4


def canonical_runner_trace(
    generated: dict[str, Any],
    executable: Path,
    common_arguments: list[str],
) -> dict[str, Any]:
    domain = generated.get("domain")
    cases = generated.get("cases")
    if (
        generated.get("kind") != "native-csv-trace-v1"
        or not isinstance(domain, str)
        or not domain
        or not isinstance(cases, list)
        or not cases
    ):
        raise NativeCsvTraceError("invalid-generated-native-csv-domain")

    prepared: list[tuple[str, list[str], list[str], dict[str, Any], int, str]] = []
    for case_index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise NativeCsvTraceError(f"invalid-case index={case_index}")
        case_id = case.get("id")
        arguments = case.get("runner_arguments")
        fields = case.get("serialized_fields")
        exclusions = case.get("field_exclusions")
        runs = case.get("input_runs")
        sample_count = case.get("sample_count")
        if (
            not isinstance(case_id, str)
            or not isinstance(arguments, list)
            or any(not isinstance(value, str) for value in arguments)
            or not isinstance(fields, list)
            or not fields
            or any(not isinstance(value, str) for value in fields)
            or not isinstance(exclusions, dict)
            or not isinstance(runs, list)
            or not isinstance(sample_count, int)
        ):
            raise NativeCsvTraceError(f"invalid-case case={case_id!r}")
        input_lines: list[str] = []
        for run in runs:
            if (
                not isinstance(run, dict)
                or not isinstance(run.get("ticks"), int)
                or run["ticks"] <= 0
                or not isinstance(run.get("input"), str)
            ):
                raise NativeCsvTraceError(f"invalid-input-run case={case_id}")
            input_lines.extend([run["input"]] * run["ticks"])
        if len(input_lines) != sample_count:
            raise NativeCsvTraceError(
                f"input-count case={case_id} expected={sample_count} "
                f"actual={len(input_lines)}"
            )
        prepared.append(
            (
                case_id,
                arguments,
                fields,
                exclusions,
                sample_count,
                "\n".join(input_lines) + "\n",
            )
        )

    def run_case(
        item: tuple[str, list[str], list[str], dict[str, Any], int, str],
    ) -> dict[str, Any]:
        case_id, arguments, fields, exclusions, sample_count, input_text = item
        result = subprocess.run(
            [str(executable), *common_arguments, *arguments],
            input=input_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit-code={result.returncode}"
            raise NativeCsvTraceError(f"runner case={case_id} detail={detail}")
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        if len(rows) != sample_count:
            raise NativeCsvTraceError(
                f"row-count case={case_id} expected={sample_count} "
                f"actual={len(rows)}"
            )
        try:
            samples = [
                {
                    field: (
                        binary32(float(row[field]))
                        if "_f32" in field
                        else int(row[field])
                    )
                    for field in selected_trace_fields(
                        fields,
                        exclusions,
                        sample_index,
                    )
                }
                for sample_index, row in enumerate(rows)
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise NativeCsvTraceError(
                f"native-csv-field case={case_id} detail={error}"
            ) from error
        return {"id": case_id, "samples": samples}

    worker_count = min(len(prepared), os.cpu_count() or 1, MAX_CASE_WORKERS)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        canonical_cases = list(executor.map(run_case, prepared))
    return {"schema": 1, "domain": domain, "cases": canonical_cases}
