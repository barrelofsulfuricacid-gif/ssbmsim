"""Shared primitives for live SSBM-to-production numeric qualification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from typing import Any


MELEE_X_TO_SIM_F32 = 12.0 / 115.0
MELEE_Y_TO_SIM_F32 = 11.0 / 62.0


def binary32(value: float) -> float:
    """Round one offline numeric value to the production binary32 domain."""

    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def normalized_sha256(path: Path) -> str:
    """Hash source text independently of the host checkout's line endings."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def selected_trace_fields(
    fields: list[str],
    field_exclusions: dict[str, list[list[int]]],
    sample_index: int,
) -> list[str]:
    """Return the fields live-qualified for one stored numeric sample."""

    return [
        field
        for field in fields
        if not any(
            start <= sample_index < end
            for start, end in field_exclusions.get(field, [])
        )
    ]


def parse_numeric_observations(
    path: Path,
    prefix: str,
    group_field: str = "case",
) -> dict[str, list[dict[str, int | float]]]:
    """Parse allocation-free C runner key/value diagnostics by case."""

    return parse_numeric_observations_text(
        path.read_text(encoding="utf-8-sig"), prefix, group_field
    )


def parse_numeric_observations_text(
    text: str,
    prefix: str,
    group_field: str = "case",
) -> dict[str, list[dict[str, int | float]]]:
    """Parse allocation-free C runner diagnostics already held in memory."""

    groups: dict[str, list[dict[str, int | float]]] = {}
    for line in text.lstrip("\ufeff").splitlines():
        if not line.startswith(prefix):
            continue
        fields = dict(
            token.split("=", 1) for token in line[len(prefix) :].split()
        )
        group = fields.pop(group_field)
        groups.setdefault(group, []).append(
            {
                key: (
                    float(value)
                    if any(marker in value for marker in ".eE")
                    else int(value)
                )
                for key, value in fields.items()
            }
        )
    return groups


def select_labeled_rows(
    capture: dict[str, Any],
    *,
    route: str,
    case_id: str,
    segment: str = "response",
    include_derived_labels: bool = False,
) -> list[dict[str, Any]]:
    """Select one manifest case without depending on capture frame numbers."""

    label = f"{route}_{case_id}_observe_{segment}"
    return [
        row
        for row in capture["rows"]
        if row.get("label") == label
        or (
            include_derived_labels
            and str(row.get("label", "")).startswith(f"{label}_")
        )
    ]


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label}: {actual!r} != {expected!r}")


def require_f32_close(
    actual: float,
    expected: float,
    tolerance: float,
    label: str,
) -> None:
    if abs(actual - expected) > tolerance:
        raise SystemExit(
            f"{label}: {actual} != {expected} +/- {tolerance} float32"
        )


def source_x_to_sim_f32(value: float) -> float:
    return binary32(value * MELEE_X_TO_SIM_F32)


def source_y_to_sim_f32(value: float) -> float:
    """Convert a source-up displacement/vector to simulation-down float32."""

    return binary32(-value * MELEE_Y_TO_SIM_F32)


def source_axis_to_sim_q15(value: float, *, invert: bool = False) -> int:
    """Encode a source fighter axis, retaining UCF's negative endpoint."""

    if not -1.0 <= value <= 1.0:
        raise ValueError(f"source fighter axis out of range: {value!r}")
    if invert:
        value = -value
    if value <= -1.0:
        encoded = -32768
    elif value >= 1.0:
        encoded = 32767
    else:
        encoded = round(value * 32767.0)
    return encoded


def common_movement_source_sample(
    row: dict[str, Any],
    *,
    action_state: int,
    action_ticks: int,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> dict[str, int | float]:
    """Project one ordinary movement row into the native CSV field contract."""

    grounded = int(bool(row["grounded"]))
    support = 0
    normal_x_f32 = 0.0
    normal_y_f32 = 0.0
    if grounded != 0:
        collision = row.get("surface_collision_memory")
        surfaces = collision.get("surfaces") if isinstance(collision, dict) else None
        floor = surfaces.get("floor") if isinstance(surfaces, dict) else None
        if isinstance(floor, dict):
            line_index = floor.get("index")
            normal = floor.get("normal")
            if (
                isinstance(line_index, int)
                and not isinstance(line_index, bool)
                and 0 <= line_index < 0xFFFFFFFF
            ):
                support = line_index + 1
            if isinstance(normal, list) and len(normal) >= 2:
                normal_x_f32 = binary32(float(normal[0]))
                normal_y_f32 = binary32(float(normal[1]))
    velocity_x_key = "ground_velocity_x" if grounded != 0 else "air_velocity_x"
    sample = {
        "action_state": action_state,
        "action_ticks": action_ticks,
        "facing": int(row["facing"]),
        "grounded": grounded,
        "support": support,
        "surface_normal_source_x_f32": normal_x_f32,
        "surface_normal_source_y_f32": normal_y_f32,
        "position_x_f32_from_origin": source_x_to_sim_f32(
            float(row["position_x_from_origin"]) - origin_x
        ),
        "position_y_f32_from_origin": source_y_to_sim_f32(
            float(row["position_y"]) - origin_y
        ),
        "velocity_x_f32": source_x_to_sim_f32(float(row[velocity_x_key])),
        "velocity_y_f32": source_y_to_sim_f32(float(row["velocity_y"])),
        "hitlag_ticks": round(float(row.get("hitlag_left", 0.0))),
        "tumble": int(str(row.get("action", "")) == "TUMBLING"),
    }
    input_memory = row.get("input_memory")
    if isinstance(input_memory, dict):
        for source_name, sample_name, maximum in (
            ("tilt_x_age", "tilt_x_age", 254),
            ("tilt_y_age", "tilt_y_age", 254),
            ("ucf_tilt_x_age", "ucf_tilt_x_age", 254),
            ("ucf_tilt_y_age", "ucf_tilt_y_age", 254),
            ("ucf_pad_buffer_count", "ucf_pad_buffer_count", 255),
        ):
            value = input_memory.get(source_name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= maximum
            ):
                sample[sample_name] = value
        for source_name, sample_name, invert in (
            ("fighter_processed_main_x", "effective_main_x_q15", False),
            ("fighter_processed_main_y", "effective_main_y_q15", True),
            ("fighter_processed_c_x", "effective_c_x_q15", False),
            ("fighter_processed_c_y", "effective_c_y_q15", True),
        ):
            value = input_memory.get(source_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sample[sample_name] = source_axis_to_sim_q15(
                    float(value),
                    invert=invert,
                )
    return sample


def validate_capture_provenance(
    capture: dict[str, Any],
    *,
    schema: int,
    stage: str,
    fighter: str,
    opponent: str,
    disc_sha256: str,
    oracle_artifact_sha256: str,
    case_count: int,
) -> None:
    if (
        capture.get("schema") != schema
        or capture.get("stage") != stage
        or capture.get("fighter") != fighter
        or capture.get("opponent") != opponent
        or capture.get("disc", {}).get("sha256") != disc_sha256
        or capture.get("oracle_execution", {}).get("release_artifact_sha256")
        != oracle_artifact_sha256
        or capture.get("checkpoint_pack", {}).get("case_count") != case_count
    ):
        raise SystemExit("live capture provenance mismatch")
