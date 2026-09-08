#!/usr/bin/env python3
"""Merge independently captured checkpoint shards in manifest case order."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    case_specs = list(manifest["checkpoint_cases"])
    case_order = [str(case["id"]) for case in case_specs]
    case_by_start_label = {
        str(case["start_label"]): str(case["id"])
        for case in case_specs
    }
    merge_setup_suffixes = manifest.get("checkpoint_pack", {}).get(
        "merge_setup_suffixes"
    )
    if (
        len(case_by_start_label) != len(case_specs)
        or len(set(case_order)) != len(case_specs)
        or (
            merge_setup_suffixes is not None
            and (
                not isinstance(merge_setup_suffixes, list)
                or not merge_setup_suffixes
                or any(
                    not isinstance(suffix, str) or not suffix
                    for suffix in merge_setup_suffixes
                )
                or len(set(merge_setup_suffixes)) != len(merge_setup_suffixes)
                or any(
                    left.startswith(right) or right.startswith(left)
                    for index, left in enumerate(merge_setup_suffixes)
                    for right in merge_setup_suffixes[index + 1 :]
                )
            )
        )
    ):
        raise SystemExit("duplicate checkpoint case id or start label")
    captures: list[dict[str, Any]] = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.inputs
    ]
    first = captures[0]
    invariant_keys = (
        "schema",
        "oracle",
        "fighter",
        "opponent",
        "stage",
        "disc",
        "dolphin_version",
        "libmelee_version",
        "stage_collision_memory",
        "oracle_gameplay_policy",
        "input_memory_probe",
        "surface_collision_memory_probe",
        "hitbox_memory_probe",
        "hurtbox_memory_probe",
    )
    for capture in captures[1:]:
        for key in invariant_keys:
            if capture.get(key) != first.get(key):
                raise SystemExit(f"checkpoint shard provenance mismatch: {key}")
        if capture.get("oracle_execution") != first.get("oracle_execution"):
            raise SystemExit("checkpoint shard oracle execution mismatch")

    rows_by_case: dict[str, list[dict[str, Any]]] = {}
    for capture in captures:
        for label in capture.get("checkpoint_pack", {}).get(
            "case_start_labels", []
        ):
            start_label = str(label)
            case_id = case_by_start_label.get(start_label)
            if case_id is None:
                raise SystemExit(
                    f"unknown checkpoint shard start label: {start_label}"
                )
            if case_id in rows_by_case:
                raise SystemExit(f"duplicate checkpoint shard case: {case_id}")
            if start_label.endswith("_setup"):
                base_prefix = start_label.removesuffix("_setup") + "_"
                prefixes = (
                    tuple(
                        base_prefix + str(suffix)
                        for suffix in merge_setup_suffixes
                    )
                    if merge_setup_suffixes is not None
                    else (base_prefix + "observe",)
                )
            elif start_label.endswith("_place"):
                prefixes = (start_label.removesuffix("_place") + "_",)
            else:
                raise SystemExit(
                    f"unsupported checkpoint shard start label: {start_label}"
                )
            rows_by_case[case_id] = [
                row
                for row in capture["rows"]
                if any(
                    row["label"].startswith(prefix) for prefix in prefixes
                )
            ]
            if not rows_by_case[case_id]:
                raise SystemExit(f"empty checkpoint shard case: {case_id}")

    if set(rows_by_case) != set(case_order):
        missing = sorted(set(case_order) - set(rows_by_case))
        extra = sorted(set(rows_by_case) - set(case_order))
        raise SystemExit(f"checkpoint shard coverage mismatch: missing={missing} extra={extra}")

    merged = copy.deepcopy(first)
    merged["rows"] = [row for case_id in case_order for row in rows_by_case[case_id]]
    pack = merged["checkpoint_pack"]
    pack["case_count"] = len(case_order)
    pack["case_start_labels"] = [
        str(case["start_label"]) for case in case_specs
    ]
    pack["coverage_manifest"] = manifest
    merged["parallel_capture"] = {
        "schema": 1,
        "shards": len(captures),
        "case_order": case_order,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(merged, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"ssbm-checkpoint-merge=pass shards={len(captures)} "
        f"cases={len(case_order)} rows={len(merged['rows'])} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
