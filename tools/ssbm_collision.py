"""Reusable offline collision helpers for pinned SSBM oracle captures.

These floating-point routines mirror Melee's finite segment geometry for
qualification and diagnostics only. Production simulation owns the portable
binary32 implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any, Sequence


def _subtract(
    left: Sequence[float], right: Sequence[float]
) -> list[float]:
    return [
        float(a) - float(b)
        for a, b in zip(left, right, strict=True)
    ]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _point_on_segment(
    start: Sequence[float], direction: Sequence[float], parameter: float
) -> list[float]:
    return [
        float(value) + parameter * float(delta)
        for value, delta in zip(start, direction, strict=True)
    ]


def segment_distance(
    first_start: Sequence[float],
    first_end: Sequence[float],
    second_start: Sequence[float],
    second_end: Sequence[float],
) -> float:
    """Return the closest distance between two finite 3D segments."""

    points = (first_start, first_end, second_start, second_end)
    if any(len(point) != 3 for point in points):
        raise ValueError("segment endpoints must have exactly three axes")
    first_direction = _subtract(first_end, first_start)
    second_direction = _subtract(second_end, second_start)
    start_delta = _subtract(first_start, second_start)
    first_length = _dot(first_direction, first_direction)
    second_length = _dot(second_direction, second_direction)
    second_projection = _dot(second_direction, start_delta)
    epsilon = 1.0e-12

    if first_length <= epsilon and second_length <= epsilon:
        return math.dist(first_start, second_start)
    if first_length <= epsilon:
        first_parameter = 0.0
        second_parameter = max(
            0.0, min(1.0, second_projection / second_length)
        )
    else:
        first_projection = _dot(first_direction, start_delta)
        if second_length <= epsilon:
            second_parameter = 0.0
            first_parameter = max(
                0.0, min(1.0, -first_projection / first_length)
            )
        else:
            direction_dot = _dot(first_direction, second_direction)
            denominator = (
                first_length * second_length
                - direction_dot * direction_dot
            )
            first_parameter = (
                max(
                    0.0,
                    min(
                        1.0,
                        (
                            direction_dot * second_projection
                            - first_projection * second_length
                        )
                        / denominator,
                    ),
                )
                if denominator > epsilon
                else 0.0
            )
            second_parameter = (
                direction_dot * first_parameter + second_projection
            ) / second_length
            if second_parameter < 0.0:
                second_parameter = 0.0
                first_parameter = max(
                    0.0, min(1.0, -first_projection / first_length)
                )
            elif second_parameter > 1.0:
                second_parameter = 1.0
                first_parameter = max(
                    0.0,
                    min(
                        1.0,
                        (direction_dot - first_projection) / first_length,
                    ),
                )
    return math.dist(
        _point_on_segment(
            first_start, first_direction, first_parameter
        ),
        _point_on_segment(
            second_start, second_direction, second_parameter
        ),
    )


def segment_collision_margin(
    first_start: Sequence[float],
    first_end: Sequence[float],
    first_radius: float,
    second_start: Sequence[float],
    second_end: Sequence[float],
    second_radius: float,
) -> float:
    """Return radius sum minus distance; nonnegative means overlap."""

    if first_radius < 0.0 or second_radius < 0.0:
        raise ValueError("collision radii must be nonnegative")
    return (
        float(first_radius)
        + float(second_radius)
        - segment_distance(
            first_start,
            first_end,
            second_start,
            second_end,
        )
    )


def captured_collision_margin(
    hitbox: dict[str, Any],
    hurtbox: dict[str, Any],
    moving: bool,
) -> float:
    """Evaluate one live-memory hitbox/hurtbox pair."""

    current = [float(value) for value in hitbox["position"]]
    previous = (
        [float(value) for value in hitbox["previous_position"]]
        if moving
        else current
    )
    return segment_collision_margin(
        previous,
        current,
        float(hitbox["radius"]),
        [float(value) for value in hurtbox["collision_position_a"]],
        [float(value) for value in hurtbox["collision_position_b"]],
        float(hurtbox["radius"]),
    )


DEFAULT_HURT_POSE_TOLERANCE_F32 = 0.0000152587890625


def binary32(value: float) -> float:
    """Round once to the runtime's IEEE-754 binary32 representation."""

    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def canonical_hurt_pose_f32(
    memory: dict[str, Any],
    hurtbox_key: str,
    fighter_position_key: str,
    facing: int,
    coordinate_scale_f32: float,
    endpoint_key_prefix: str = "position",
) -> tuple[tuple[float | int, ...], ...]:
    """Canonicalize a live hurt pose into facing-right float32 space."""

    if facing not in (-1, 1):
        raise ValueError("hurt-pose facing must be -1 or 1")
    if coordinate_scale_f32 <= 0.0:
        raise ValueError("hurt-pose coordinate scale must be positive")
    if endpoint_key_prefix not in {"position", "collision_position"}:
        raise ValueError("unsupported hurt-pose endpoint key prefix")
    fighter_position = [
        float(value) for value in memory[fighter_position_key]
    ]
    capsules = []
    for hurtbox_id, source in enumerate(memory[hurtbox_key]):
        hurtbox = dict(source)
        if int(hurtbox["state"]) != 0:
            continue
        endpoint_a = [
            float(value)
            for value in hurtbox[f"{endpoint_key_prefix}_a"]
        ]
        endpoint_b = [
            float(value)
            for value in hurtbox[f"{endpoint_key_prefix}_b"]
        ]
        capsules.append(
            (
                binary32(
                    facing
                    * (endpoint_a[0] - fighter_position[0])
                    * coordinate_scale_f32
                ),
                binary32(
                    -(endpoint_a[1] - fighter_position[1])
                    * coordinate_scale_f32
                ),
                binary32(
                    facing
                    * (endpoint_a[2] - fighter_position[2])
                    * coordinate_scale_f32
                ),
                binary32(
                    facing
                    * (endpoint_b[0] - fighter_position[0])
                    * coordinate_scale_f32
                ),
                binary32(
                    -(endpoint_b[1] - fighter_position[1])
                    * coordinate_scale_f32
                ),
                binary32(
                    facing
                    * (endpoint_b[2] - fighter_position[2])
                    * coordinate_scale_f32
                ),
                binary32(float(hurtbox["radius"]) * coordinate_scale_f32),
                hurtbox_id,
                int(hurtbox["height"]),
                int(hurtbox["grabbable"]),
            )
        )
    return tuple(capsules)


def hurt_poses_equivalent(
    left: tuple[tuple[float | int, ...], ...],
    right: tuple[tuple[float | int, ...], ...],
    tolerance_f32: float = DEFAULT_HURT_POSE_TOLERANCE_F32,
) -> bool:
    """Compare canonical binary32 hurt poses with a bounded coordinate envelope."""

    if not math.isfinite(tolerance_f32) or tolerance_f32 < 0.0:
        raise ValueError("hurt-pose tolerance must be nonnegative")
    return len(left) == len(right) and all(
        left_capsule[7:] == right_capsule[7:]
        and all(
            abs(float(left_value) - float(right_value)) <= tolerance_f32
            for left_value, right_value in zip(
                left_capsule[:7], right_capsule[:7], strict=True
            )
        )
        for left_capsule, right_capsule in zip(left, right, strict=True)
    )


def hurt_pose_tracks_semantic_payload(
    tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip capture provenance while retaining every bounded source pose."""

    return [
        {
            "id": track["id"],
            "source_action": track["source_action"],
            "first_displayed_frame": track["first_displayed_frame"],
            "frames": [
                {
                    "displayed_frame": frame["displayed_frame"],
                    "capsules_f32": frame["capsules_f32"],
                }
                for frame in track["frames"]
            ],
        }
        for track in tracks
    ]


def canonical_json_sha256(value: object) -> str:
    """Hash one JSON-compatible value with the repository's canonical form."""

    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
