#!/usr/bin/env python3
"""Verify live and stored UCF 0.84 SDI, shield-SDI, and tumble inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ssbm_live_trace import canonical_sha256
from ssbm_native_csv_trace import NativeCsvTraceError, canonical_runner_trace
from ssbm_natural_movement_domain import (
    NaturalMovementDomainError,
    canonical_capture,
    load_capture,
)


class UcfDamageInputVerificationError(ValueError):
    """A live or native trace violates the declared UCF boundary theorem."""


def fail(reason: str) -> None:
    raise UcfDamageInputVerificationError(reason)


def case_rows(
    capture: dict[str, Any], case: dict[str, Any]
) -> list[dict[str, Any]]:
    prefix = str(case["source_label_prefix"])
    return [
        row
        for row in capture["rows"]
        if str(row.get("label", "")).startswith(prefix)
    ]


def memory(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    value = row.get("input_memory")
    if not isinstance(value, dict):
        fail(f"input-memory case={case_id}")
    return value


def verify_checkpoint(capture: dict[str, Any], coverage: dict[str, Any]) -> None:
    checkpoint = capture.get("checkpoint_pack")
    probe = capture.get("input_memory_probe")
    expected_labels = [
        str(case["start_label"]) for case in coverage["checkpoint_cases"]
    ]
    expected_slots = coverage["checkpoint_pack"]["capture_plan"][
        "checkpoint_slot_count"
    ]
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("protocol")
        != "immutable-multislot-slippi-state-file-control-v2"
        or checkpoint.get("slot_count") != expected_slots
        or checkpoint.get("case_count") != len(expected_labels)
        or checkpoint.get("case_start_labels") != expected_labels
        or not isinstance(probe, dict)
        or probe.get("schema") != 2
    ):
        fail(f"checkpoint-provenance domain={coverage['domain']}")


def verify_hitlag_live(capture: dict[str, Any], coverage: dict[str, Any]) -> None:
    cases = {
        str(case["id"]): case for case in coverage["stored_oracle"]["cases"]
    }
    expected_ids = {
        "sdi_raw_delta_62_reject",
        "sdi_raw_delta_63_accept",
        "shield_sdi_raw_delta_62_reject",
        "shield_sdi_raw_delta_63_accept",
    }
    if set(cases) != expected_ids:
        fail("hitlag-case-set")
    for case_id, case in cases.items():
        rows = case_rows(capture, case)
        shield = case_id.startswith("shield_")
        accept = case_id.endswith("63_accept")
        boundary = 63 if accept else 62
        expected_actions = (
            ["SHIELD", "SHIELD_STUN", "SHIELD_STUN", "SHIELD_STUN"]
            if shield
            else [
                "STANDING",
                "DAMAGE_NEUTRAL_2",
                "DAMAGE_NEUTRAL_2",
                "DAMAGE_NEUTRAL_2",
            ]
        )
        expected_grounded = [True, True, True, True] if shield else [
            True,
            False,
            False,
            False,
        ]
        expected_damage = [0.0] * 4 if shield else [0.0, 2.0, 2.0, 2.0]
        if (
            len(rows) != 4
            or [row.get("action") for row in rows] != expected_actions
            or [bool(row.get("grounded")) for row in rows]
            != expected_grounded
            or [float(row.get("damage_percent", -1.0)) for row in rows]
            != expected_damage
            or [round(float(row.get("hitlag_left", -1.0))) for row in rows]
            != [0, 3, 2, 1]
            or [row.get("observed_raw_main_x") for row in rows]
            != [0, 44, boundary, 0]
        ):
            fail(f"hitlag-live-outcome case={case_id}")
        memories = [memory(row, case_id) for row in rows]
        if (
            [value.get("tilt_x_age") for value in memories]
            != [254, 254, 254, 254]
            or [value.get("ucf_tilt_x_age") for value in memories]
            != [254, 0, 1, 254]
        ):
            fail(f"hitlag-input-history case={case_id}")
        positions = [float(row["position_x"]) for row in rows]
        expected_shift = 3.1185 if shield else 4.725
        if accept:
            if (
                abs((positions[2] - positions[1]) - expected_shift) > 1e-6
                or abs(positions[3] - positions[2]) > 1e-6
            ):
                fail(f"hitlag-positive-shift case={case_id}")
        elif any(abs(position - positions[0]) > 1e-6 for position in positions):
            fail(f"hitlag-negative-shift case={case_id}")


def verify_tumble_live(capture: dict[str, Any], coverage: dict[str, Any]) -> None:
    cases = {
        str(case["id"]): case for case in coverage["stored_oracle"]["cases"]
    }
    if set(cases) != {
        "tumble_raw_delta_75_reject",
        "tumble_raw_delta_76_accept",
    }:
        fail("tumble-case-set")
    for case_id, case in cases.items():
        rows = case_rows(capture, case)
        accept = case_id.endswith("76_accept")
        boundary = 76 if accept else 75
        actions = ["TUMBLING", "TUMBLING", "FALLING" if accept else "TUMBLING"]
        frames = [1, 2, 1 if accept else 3]
        if (
            len(rows) != 3
            or [row.get("action") for row in rows] != actions
            or [round(float(row.get("action_frame", -1.0))) for row in rows]
            != frames
            or [row.get("observed_raw_main_x") for row in rows]
            != [0, 63, boundary]
            or any(bool(row.get("grounded")) for row in rows)
            or any(float(row.get("damage_percent", -1.0)) != 61.0 for row in rows)
            or any(round(float(row.get("hitlag_left", -1.0))) != 0 for row in rows)
        ):
            fail(f"tumble-live-outcome case={case_id}")
        memories = [memory(row, case_id) for row in rows]
        if (
            [value.get("tilt_x_age") for value in memories] != [254, 0, 1]
            or [value.get("ucf_tilt_x_age") for value in memories]
            != [254, 0, 1]
        ):
            fail(f"tumble-input-history case={case_id}")


def load_pair(
    coverage_path: Path,
    capture_path: Path,
    repeat_path: Path,
    qualifier: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    live_source = coverage["live_source"]
    capture = load_capture(
        capture_path,
        str(live_source["capture_sha256"]),
        live_source,
        require_zero_damage=False,
    )
    repeat = load_capture(
        repeat_path,
        str(live_source["repeat_capture_sha256"]),
        live_source,
        require_zero_damage=False,
    )
    for current in (capture, repeat):
        verify_checkpoint(current, coverage)
        qualifier(current, coverage)
    canonical = canonical_capture(capture, coverage)
    repeat_canonical = canonical_capture(repeat, coverage)
    if canonical != repeat_canonical:
        fail(f"repeat-semantic-trace domain={coverage['domain']}")
    digest = canonical_sha256(canonical)
    if digest != coverage["stored_oracle"]["source_trace_sha256"]:
        fail(f"source-digest domain={coverage['domain']} actual={digest}")
    return coverage, canonical


def native_trace(coverage: dict[str, Any], runner: Path) -> dict[str, Any]:
    generated_path = Path(coverage["stored_oracle"]["generator"]["output"])
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    canonical = canonical_runner_trace(generated, runner, [])
    digest = canonical_sha256(canonical)
    if digest != coverage["stored_oracle"]["production_trace_sha256"]:
        fail(f"production-digest domain={coverage['domain']} actual={digest}")
    return canonical


def compare_hitlag(
    source: dict[str, Any], production: dict[str, Any]
) -> None:
    if [case["id"] for case in source["cases"]] != [
        case["id"] for case in production["cases"]
    ]:
        fail("hitlag-native-case-order")
    for source_case, production_case in zip(
        source["cases"], production["cases"], strict=True
    ):
        source_samples = source_case["samples"]
        production_samples = production_case["samples"]
        for index, (left, right) in enumerate(
            zip(source_samples, production_samples, strict=True)
        ):
            if {
                key: value
                for key, value in left.items()
                if key != "position_x_f32_from_origin"
            } != {
                key: value
                for key, value in right.items()
                if key != "position_x_f32_from_origin"
            }:
                fail(f"hitlag-native-field case={source_case['id']} row={index}")
        source_base = source_samples[1]["position_x_f32_from_origin"]
        production_base = production_samples[1]["position_x_f32_from_origin"]
        for index in range(1, 4):
            source_delta = (
                source_samples[index]["position_x_f32_from_origin"] - source_base
            )
            production_delta = (
                production_samples[index]["position_x_f32_from_origin"]
                - production_base
            )
            if abs(source_delta - production_delta) > 0.0000152587890625:
                fail(f"hitlag-float32 case={source_case['id']} row={index}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hitlag_coverage", type=Path)
    parser.add_argument("hitlag_capture", type=Path)
    parser.add_argument("hitlag_repeat", type=Path)
    parser.add_argument("tumble_coverage", type=Path)
    parser.add_argument("tumble_capture", type=Path)
    parser.add_argument("tumble_repeat", type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    args = parser.parse_args()
    try:
        hitlag_coverage, hitlag_source = load_pair(
            args.hitlag_coverage,
            args.hitlag_capture,
            args.hitlag_repeat,
            verify_hitlag_live,
        )
        tumble_coverage, tumble_source = load_pair(
            args.tumble_coverage,
            args.tumble_capture,
            args.tumble_repeat,
            verify_tumble_live,
        )
        hitlag_native = native_trace(hitlag_coverage, args.runner)
        tumble_native = native_trace(tumble_coverage, args.runner)
        compare_hitlag(hitlag_source, hitlag_native)
        if tumble_source != tumble_native:
            fail("tumble-native-exact")
    except (
        KeyError,
        NativeCsvTraceError,
        NaturalMovementDomainError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise SystemExit(f"ssbm-ucf084-damage-input=fail reason={error}") from error
    print(
        "ssbm-ucf084-damage-input=pass domains=2 cases=6 rows=22 "
        "strict62=1 strict75=1 source_repeat=1 stored=1 float32_tolerance=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
