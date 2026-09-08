#!/usr/bin/env python3
"""Compare a qualified live SSBM capture directly with the native simulator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from generate_ssbm_stored_trace_oracle import generate_native_csv
from ssbm_live_trace import canonical_sha256
from ssbm_native_csv_trace import NativeCsvTraceError, canonical_runner_trace
from ssbm_natural_movement_domain import (
    NaturalMovementDomainError,
    canonical_capture,
    load_capture,
)

def fail(message: str) -> None:
    raise SystemExit(f"ssbm-live-native-trace=fail reason={message}")


def executable_path(build_directory: Path, executable: str) -> Path:
    candidates = [build_directory / executable]
    if not executable.endswith(".exe"):
        candidates.append(build_directory / f"{executable}.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    fail(f"missing-runner executable={executable} build_dir={build_directory}")


def first_mismatch(
    source: dict[str, Any],
    production: dict[str, Any],
) -> str:
    source_cases = source.get("cases", [])
    production_cases = production.get("cases", [])
    for source_case, production_case in zip(
        source_cases, production_cases, strict=False
    ):
        case_id = source_case.get("id")
        if case_id != production_case.get("id"):
            return f"case-id source={case_id} production={production_case.get('id')}"
        for sample_index, (source_sample, production_sample) in enumerate(
            zip(
                source_case.get("samples", []),
                production_case.get("samples", []),
                strict=False,
            )
        ):
            if source_sample != production_sample:
                fields = sorted(set(source_sample) | set(production_sample))
                field = next(
                    name
                    for name in fields
                    if source_sample.get(name) != production_sample.get(name)
                )
                return (
                    f"case={case_id} sample={sample_index} field={field} "
                    f"source={source_sample.get(field)} "
                    f"production={production_sample.get(field)}"
                )
    return "canonical-shape"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()

    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    stored = coverage.get("stored_oracle")
    live_source = coverage.get("live_source")
    if (
        not isinstance(stored, dict)
        or stored.get("kind") != "native-csv-trace-v1"
        or not isinstance(live_source, dict)
    ):
        fail("coverage-schema")
    try:
        capture = load_capture(
            args.capture,
            str(live_source["capture_sha256"]),
            live_source,
        )
        source = canonical_capture(capture, coverage)
        generated = json.loads(generate_native_csv(coverage))
        runner = stored.get("runner")
        if (
            not isinstance(runner, dict)
            or not isinstance(runner.get("executable"), str)
            or not isinstance(runner.get("arguments"), list)
        ):
            fail("runner-schema")
        production = canonical_runner_trace(
            generated,
            executable_path(args.build_dir, runner["executable"]),
            runner["arguments"],
        )
    except (NaturalMovementDomainError, NativeCsvTraceError) as error:
        fail(str(error))

    source_digest = canonical_sha256(source)
    production_digest = canonical_sha256(production)
    if source != production:
        fail(
            f"semantic-mismatch {first_mismatch(source, production)} "
            f"source_sha256={source_digest} "
            f"production_sha256={production_digest}"
        )
    print(
        "ssbm-live-native-trace=pass "
        f"domain={coverage['domain']} cases={len(source['cases'])} "
        f"semantic_sha256={source_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
