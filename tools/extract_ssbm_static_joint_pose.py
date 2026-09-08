#!/usr/bin/env python3
"""Extract a canonical static HSD joint pose from a qualified live capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_payload(capture: dict[str, Any]) -> dict[str, Any]:
    source = capture.get("guard_target_joint_tree")
    if (
        not isinstance(source, dict)
        or source.get("schema") != 1
        or not isinstance(source.get("joints"), list)
        or len(source["joints"]) != 62
    ):
        raise ValueError("capture has no qualified 62-joint GuardOn target tree")
    joints: list[dict[str, Any]] = []
    for expected_index, row in enumerate(source["joints"]):
        if (
            not isinstance(row, dict)
            or row.get("source_index") != expected_index
            or not isinstance(row.get("parent_index"), int)
        ):
            raise ValueError("invalid static joint row")
        output = {
            "source_index": expected_index,
            "target_part_index": row.get("target_part_index"),
            "parent_index": row["parent_index"],
        }
        if not isinstance(output["target_part_index"], int):
            raise ValueError("invalid static joint target part")
        for field in ("rotation", "scale", "translation"):
            values = row.get(field)
            if (
                not isinstance(values, list)
                or len(values) != 3
                or not all(isinstance(value, (int, float)) for value in values)
            ):
                raise ValueError(f"invalid static joint {field}")
            output[field] = [float(value) for value in values]
        joints.append(output)
    capture_bytes = json.dumps(
        capture, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema": 1,
        "scope": "ssbm-static-hsd-joint-pose",
        "fighter": capture.get("fighter"),
        "pose": "guard_target",
        "target_parts_count": source.get("parts_count"),
        "skipped_part_indices": source.get("skipped_part_indices"),
        "source": {
            "capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
            "disc_sha256": capture.get("disc", {}).get("sha256"),
            "oracle": capture.get("oracle"),
            "oracle_gameplay_policy": capture.get("oracle_gameplay_policy"),
            "probe": capture.get("surface_collision_memory_probe"),
        },
        "joints": joints,
    }


def render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = canonical_payload(json.loads(args.capture.read_text(encoding="utf-8")))
    output = render(payload)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != output:
            raise SystemExit(f"stale static HSD joint pose: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
    print(
        "ssbm-static-joint-pose=pass "
        f"joints={len(payload['joints'])} sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
