#!/usr/bin/env python3
"""Verify the live UCF DBOOC and shield-input boundary matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ssbm_natural_movement_domain import NaturalMovementDomainError
from verify_ssbm_special_acquisition_domain import (
    SpecialAcquisitionVerificationError,
    case_rows,
    verify_capture_pair,
)


class UcfShieldInputVerificationError(ValueError):
    """The live trace does not prove the pinned UCF boundary matrix."""


def fail(reason: str) -> None:
    raise UcfShieldInputVerificationError(reason)


def edge_row(
    rows: list[dict[str, Any]],
    prefix: str,
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = case_rows(rows, prefix)
    edge_index = next(
        (
            index
            for index, row in enumerate(current)
            if str(row.get("label", "")).endswith("_edge")
        ),
        -1,
    )
    if edge_index <= 0:
        fail(f"edge-row case={case_id}")
    return current[edge_index - 1], current[edge_index]


def input_memory(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    memory = row.get("input_memory")
    if not isinstance(memory, dict):
        fail(f"input-memory case={case_id}")
    return memory


def floor_line(row: dict[str, Any]) -> int | None:
    collision = row.get("surface_collision_memory")
    surfaces = collision.get("surfaces") if isinstance(collision, dict) else None
    floor = surfaces.get("floor") if isinstance(surfaces, dict) else None
    return floor.get("index") if isinstance(floor, dict) else None


def qualify_ucf084_matrix(
    capture: dict[str, Any],
    coverage: dict[str, Any],
) -> None:
    input_probe = capture.get("input_memory_probe")
    surface_probe = capture.get("surface_collision_memory_probe")
    if (
        not isinstance(input_probe, dict)
        or input_probe.get("schema") != 2
        or not isinstance(surface_probe, dict)
    ):
        fail("input-surface-provenance")
    stored_cases = coverage["stored_oracle"]["cases"]
    cases = {
        str(case["id"]): case
        for case in stored_cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    expected_ids = {
        "dbooc_radial_over",
        "dbooc_radial_under",
        "dbooc_age1",
        "shield_drop_raw_y63",
        "shield_drop_raw_y64",
        "shield_drop_extended_delta50",
        "shield_drop_extended_delta44",
    }
    if set(cases) != expected_ids:
        fail("case-set")

    rows = capture["rows"]
    for case_id, raw_x, age, action in (
        ("dbooc_radial_over", 63, 0, "CROUCHING"),
        ("dbooc_radial_under", 60, 0, "CROUCH_END"),
        ("dbooc_age1", 63, 1, "CROUCH_END"),
    ):
        case = cases[case_id]
        _, edge = edge_row(rows, str(case["source_label_prefix"]), case_id)
        memory = input_memory(edge, case_id)
        if (
            edge.get("observed_raw_main_x") != raw_x
            or edge.get("observed_raw_main_y") != -48
            or memory.get("tilt_x_age") != age
            or memory.get("ucf_tilt_x_age") != age
            or edge.get("action") != action
            or not bool(edge.get("grounded"))
        ):
            fail(f"dbooc-boundary case={case_id}")

    for case_id, raw_y, action, grounded in (
        ("shield_drop_raw_y63", -63, "PLATFORM_DROP", False),
        ("shield_drop_raw_y64", -64, "SPOTDODGE", True),
    ):
        case = cases[case_id]
        pre_edge, edge = edge_row(
            rows, str(case["source_label_prefix"]), case_id
        )
        memory = input_memory(edge, case_id)
        if (
            floor_line(pre_edge) != 2
            or edge.get("observed_raw_main_x") != 48
            or edge.get("observed_raw_main_y") != raw_y
            or not isinstance(memory.get("tilt_x_age"), int)
            or memory["tilt_x_age"] < 4
            or edge.get("action") != action
            or bool(edge.get("grounded")) != grounded
        ):
            fail(f"shield-drop-suppression case={case_id}")

    for case_id, initial_count, edge_count, action, grounded in (
        (
            "shield_drop_extended_delta50",
            1,
            2,
            "PLATFORM_DROP",
            False,
        ),
        ("shield_drop_extended_delta44", 0, 0, "SHIELD", True),
    ):
        case = cases[case_id]
        pre_edge, edge = edge_row(
            rows, str(case["source_label_prefix"]), case_id
        )
        pre_memory = input_memory(pre_edge, case_id)
        edge_memory = input_memory(edge, case_id)
        if (
            floor_line(pre_edge) != 2
            or pre_edge.get("observed_raw_main_y") != -50
            or edge.get("observed_raw_main_x") != 61
            or edge.get("observed_raw_main_y") != -50
            or pre_memory.get("ucf_pad_buffer_count") != initial_count
            or edge_memory.get("ucf_pad_buffer_count") != edge_count
            or edge.get("action") != action
            or bool(edge.get("grounded")) != grounded
        ):
            fail(f"extended-shield-drop case={case_id}")


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
            extra_qualifier=qualify_ucf084_matrix,
        )
    except (
        KeyError,
        NaturalMovementDomainError,
        SpecialAcquisitionVerificationError,
        UcfShieldInputVerificationError,
    ) as error:
        raise SystemExit(
            f"ssbm-ucf084-shield-input=fail reason={error}"
        ) from error
    print(
        "ssbm-ucf084-shield-input=pass "
        f"domain={coverage['domain']} rows={len(capture['rows'])} "
        f"stored_cases={len(coverage['checkpoint_cases'])} "
        f"source_trace_sha256={observed_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
