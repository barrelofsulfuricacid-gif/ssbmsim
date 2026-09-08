#!/usr/bin/env python3
"""Verify a manifest-declared common-state special-acquisition domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from ssbm_live_trace import canonical_sha256
from ssbm_natural_movement_domain import (
    NaturalMovementDomainError,
    canonical_capture,
    load_capture,
)


class SpecialAcquisitionVerificationError(ValueError):
    """A capture pair does not satisfy its acquisition-domain contract."""


def fail(message: str) -> None:
    raise SpecialAcquisitionVerificationError(message)


def case_rows(
    rows: list[dict[str, Any]],
    source_label_prefix: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("label", "")).startswith(source_label_prefix)
    ]


def qualify_capture(
    capture: dict[str, Any],
    coverage: dict[str, Any],
) -> None:
    rows = capture["rows"]
    checkpoint = capture.get("checkpoint_pack")
    checkpoint_cases = coverage.get("checkpoint_cases")
    checkpoint_pack = coverage.get("checkpoint_pack")
    stored_cases = coverage.get("stored_oracle", {}).get("cases")
    expectations = coverage.get("live_expectations")
    if (
        not isinstance(checkpoint_cases, list)
        or not isinstance(checkpoint_pack, dict)
        or not isinstance(stored_cases, list)
        or not isinstance(expectations, dict)
    ):
        fail("coverage-schema")
    expected_labels = [case["start_label"] for case in checkpoint_cases]
    expected_slots = checkpoint_pack["capture_plan"]["checkpoint_slot_count"]
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("protocol")
        != "immutable-multislot-slippi-state-file-control-v2"
        or checkpoint.get("slot_count") != expected_slots
        or checkpoint.get("case_count") != len(expected_labels)
        or checkpoint.get("case_start_labels") != expected_labels
    ):
        fail("checkpoint-isolation")

    stored_by_id = {
        str(case.get("id")): case
        for case in stored_cases
        if isinstance(case, dict)
    }
    if set(stored_by_id) != set(expectations):
        fail("expectation-case-set")
    for case_id, expected in expectations.items():
        case = stored_by_id[case_id]
        if not isinstance(expected, dict):
            fail(f"expectation-schema case={case_id}")
        current = case_rows(rows, str(case["source_label_prefix"]))
        edge_index = next(
            (
                index
                for index, row in enumerate(current)
                if str(row.get("label", "")).endswith("_edge")
            ),
            -1,
        )
        edge_frames = expected.get("edge_action_frames")
        edge_action = expected.get("edge_action")
        expected_edge_rows = expected.get("edge_rows")
        edge_facing = expected.get("edge_facing")
        pre_edge_grounded = expected.get("pre_edge_grounded")
        pre_edge_support_line = expected.get("pre_edge_support_line")
        if (
            edge_index <= 0
            or not isinstance(pre_edge_grounded, bool)
            or (
                pre_edge_support_line is not None
                and (
                    not isinstance(pre_edge_support_line, int)
                    or isinstance(pre_edge_support_line, bool)
                    or not 0 <= pre_edge_support_line < 0xFFFFFFFF
                )
            )
        ):
            fail(f"expectation-schema case={case_id}")
        pre_edge_action = expected.get("pre_edge_action")
        pre_edge_action_frame = expected.get("pre_edge_action_frame")
        if (
            (
                pre_edge_action is not None
                and (
                    not isinstance(pre_edge_action, str)
                    or not pre_edge_action
                )
            )
            or (
                pre_edge_action_frame is not None
                and (
                    not isinstance(pre_edge_action_frame, int)
                    or isinstance(pre_edge_action_frame, bool)
                )
            )
            or (pre_edge_action is None) != (pre_edge_action_frame is None)
        ):
            fail(f"expectation-schema case={case_id}")
        pre_edge = current[edge_index - 1]
        collision = pre_edge.get("surface_collision_memory")
        surfaces = collision.get("surfaces") if isinstance(collision, dict) else None
        floor = surfaces.get("floor") if isinstance(surfaces, dict) else None
        actual_support_line = (
            floor.get("index") if isinstance(floor, dict) else None
        )
        if (
            bool(pre_edge.get("grounded")) != pre_edge_grounded
            or (
                pre_edge_support_line is not None
                and actual_support_line != pre_edge_support_line
            )
            or (
                pre_edge_action is not None
                and (
                    pre_edge.get("action") != pre_edge_action
                    or round(float(pre_edge["action_frame"])) !=
                        pre_edge_action_frame
                )
            )
        ):
            fail(f"pre-edge-outcome case={case_id}")
        edge_rows = current[edge_index:]
        if expected_edge_rows is not None:
            if (
                not isinstance(expected_edge_rows, list)
                or not expected_edge_rows
                or len(edge_rows) != len(expected_edge_rows)
            ):
                fail(f"expectation-schema case={case_id}")
            for row_index, (actual, declared) in enumerate(
                zip(edge_rows, expected_edge_rows, strict=True)
            ):
                if (
                    not isinstance(declared, dict)
                    or set(declared) !=
                        {"action", "action_frame", "facing", "grounded"}
                    or not isinstance(declared.get("action"), str)
                    or not declared["action"]
                    or not isinstance(
                        declared.get("action_frame"), int
                    )
                    or isinstance(declared["action_frame"], bool)
                    or declared.get("facing") not in {-1, 1}
                    or not isinstance(declared.get("grounded"), bool)
                ):
                    fail(f"expectation-schema case={case_id}")
                if (
                    actual.get("action") != declared["action"]
                    or round(float(actual["action_frame"])) !=
                        declared["action_frame"]
                    or actual.get("facing") != float(declared["facing"])
                    or bool(actual.get("grounded")) != declared["grounded"]
                ):
                    fail(
                        f"edge-outcome case={case_id} row={row_index}"
                    )
            continue
        if (
            not isinstance(edge_action, str)
            or not edge_action
            or not isinstance(edge_frames, list)
            or not edge_frames
            or any(
                not isinstance(frame, int) or isinstance(frame, bool)
                for frame in edge_frames
            )
            or edge_facing not in {-1, 1}
        ):
            fail(f"expectation-schema case={case_id}")
        actual_frames = [
            round(float(row["action_frame"]))
            for row in edge_rows
            if row.get("action") == edge_action
        ]
        if (
            len(edge_rows) != len(edge_frames)
            or actual_frames != edge_frames
            or any(row.get("action") != edge_action for row in edge_rows)
            or any(row.get("facing") != float(edge_facing) for row in edge_rows)
        ):
            fail(f"edge-outcome case={case_id}")


def verify_capture_pair(
    coverage: dict[str, Any],
    capture_path: Path,
    repeat_capture_path: Path,
    *,
    extra_qualifier: Callable[
        [dict[str, Any], dict[str, Any]], None
    ] | None = None,
) -> tuple[dict[str, Any], str]:
    live_source = coverage.get("live_source")
    if (
        coverage.get("schema") != 1
        or not isinstance(coverage.get("domain"), str)
        or not isinstance(live_source, dict)
        or coverage.get("stored_oracle", {}).get("kind")
        != "native-csv-trace-v1"
    ):
        fail("coverage-schema")
    capture = load_capture(
        capture_path,
        str(live_source["capture_sha256"]),
        live_source,
    )
    repeat_capture = load_capture(
        repeat_capture_path,
        str(live_source["repeat_capture_sha256"]),
        live_source,
    )
    qualify_capture(capture, coverage)
    qualify_capture(repeat_capture, coverage)
    if extra_qualifier is not None:
        extra_qualifier(capture, coverage)
        extra_qualifier(repeat_capture, coverage)
    canonical = canonical_capture(capture, coverage)
    repeat_canonical = canonical_capture(repeat_capture, coverage)
    if canonical != repeat_canonical:
        fail("repeat-semantic-trace")
    observed_digest = canonical_sha256(canonical)
    expected_digest = coverage["stored_oracle"].get(
        "source_trace_sha256"
    )
    if observed_digest != expected_digest:
        fail(
            f"source-trace-sha256 expected={expected_digest} "
            f"actual={observed_digest}"
        )
    return capture, observed_digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("repeat_capture", type=Path)
    args = parser.parse_args()

    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    try:
        capture, observed_digest = verify_capture_pair(
            coverage,
            args.capture,
            args.repeat_capture,
        )
    except (
        KeyError,
        NaturalMovementDomainError,
        SpecialAcquisitionVerificationError,
    ) as error:
        raise SystemExit(
            f"ssbm-special-acquisition=fail reason={error}"
        ) from error
    print(
        "ssbm-special-acquisition=pass "
        f"domain={coverage['domain']} rows={len(capture['rows'])} "
        f"stored_cases={len(coverage['checkpoint_cases'])} "
        f"source_trace_sha256={observed_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
