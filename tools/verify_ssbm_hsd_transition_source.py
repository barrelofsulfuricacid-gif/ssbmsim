#!/usr/bin/env python3
"""Verify Melee's moving-target local-SRT transition recurrence from captures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any


JOBJ_USE_QUATERNION = 1 << 17
FIGHTER_BONE_ANIMATED = 0x40
FIGHTER_BONE_SKIP = 0x80
FIGHTER_BONE_COPY_TARGET = 0x08
FIGHTER_BONE_SECONDARY = 0x04


def binary32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def euler_to_quaternion(rotation: list[float]) -> tuple[float, ...]:
    cx = math.cos(0.5 * rotation[0])
    cy = math.cos(0.5 * rotation[1])
    cz = math.cos(0.5 * rotation[2])
    sx = math.sin(0.5 * rotation[0])
    sy = math.sin(0.5 * rotation[1])
    sz = math.sin(0.5 * rotation[2])
    ss = sy * sz
    cc = cy * cz
    return (
        sx * cc - cx * ss,
        cz * (cx * sy) + sz * (sx * cy),
        sz * (cx * cy) - cz * (sx * sy),
        cx * cc + sx * ss,
    )


def pose_quaternion(pose: dict[str, Any]) -> tuple[float, ...]:
    rotation = pose.get("rotation")
    require(
        isinstance(rotation, list)
        and len(rotation) == 4
        and all(isinstance(value, (int, float)) for value in rotation),
        "JObj rotation is invalid",
    )
    if int(pose.get("flags", 0)) & JOBJ_USE_QUATERNION:
        return tuple(float(value) for value in rotation)
    return euler_to_quaternion([float(value) for value in rotation[:3]])


def slerp(
    target: tuple[float, ...],
    current: tuple[float, ...],
    current_weight: float,
) -> tuple[float, ...]:
    dot = sum(left * right for left, right in zip(target, current, strict=True))
    if dot < 0.0:
        current = tuple(-value for value in current)
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if 1.0 - dot <= 1.0e-10:
        target_weight = 1.0 - current_weight
        return tuple(
            target_weight * left + current_weight * right
            for left, right in zip(target, current, strict=True)
        )
    theta = math.acos(dot)
    sine = math.sin(theta)
    target_weight = math.sin((1.0 - current_weight) * theta) / sine
    old_weight = math.sin(current_weight * theta) / sine
    return tuple(
        target_weight * left + old_weight * right
        for left, right in zip(target, current, strict=True)
    )


def vector(pose: dict[str, Any], name: str, count: int) -> tuple[float, ...]:
    value = pose.get(name)
    require(
        isinstance(value, list)
        and len(value) == count
        and all(isinstance(component, (int, float)) for component in value),
        f"JObj {name} is invalid",
    )
    return tuple(float(component) for component in value)


def closure(row: dict[str, Any]) -> list[dict[str, Any]]:
    surface = row.get("surface_collision_memory")
    require(isinstance(surface, dict), "row has no surface probe")
    source = surface.get("ecb_source")
    require(isinstance(source, dict), "row has no ECB source probe")
    result = source.get("joint_closure")
    require(isinstance(result, list), "row has no joint closure")
    return result


def canonical_pose(pose: dict[str, Any], root: bool) -> dict[str, Any]:
    translation = list(vector(pose, "translation", 3))
    if root:
        translation = [0.0, 0.0, 0.0]
    return {
        "flags": int(pose["flags"]) & JOBJ_USE_QUATERNION,
        "rotation_q20": [round(value * (1 << 20)) for value in pose_quaternion(pose)],
        "scale_q20": [round(value * (1 << 20)) for value in vector(pose, "scale", 3)],
        "translation_f32": [binary32(value) for value in translation],
    }


def semantic_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        surface = row["surface_collision_memory"]
        joints = closure(row)
        payload.append(
            {
                "label": row["label"],
                "action": row["action"],
                "motion": surface["fighter_motion_id"],
                "animation": surface["fighter_animation_id"],
                "frame_f32": binary32(surface["fighter_animation_frame"]),
                "rate_f32": binary32(surface["fighter_animation_rate"]),
                "blend_frames_f32": binary32(
                    surface["fighter_animation_blend_frames"]
                ),
                "blend_progress_f32": binary32(
                    surface["fighter_animation_blend_progress"]
                ),
                "joints": [
                    {
                        "source_index": joint["source_index"],
                        "bone_flags": joint["fighter_bone_flags"],
                        "current": canonical_pose(
                            joint["pose"], int(joint["source_index"]) == 0
                        ),
                        "target": canonical_pose(
                            joint["animation_pose"], False
                        ),
                    }
                    for joint in joints
                ],
            }
        )
    return payload


def semantic_sha256(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        semantic_payload(rows), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_capture(
    name: str,
    capture: dict[str, Any],
    expected_rows: int,
    expected_joints: list[int],
    blend_start: int,
    local_tolerance: float,
    quaternion_tolerance: float,
) -> tuple[int, int, float, float]:
    rows = capture.get("rows")
    require(isinstance(rows, list) and len(rows) == expected_rows, f"{name}: row count")
    comparisons = 0
    joint_comparisons = 0
    maximum_local = 0.0
    maximum_quaternion = 0.0
    previous: dict[str, Any] | None = None
    for row in rows:
        joints = closure(row)
        require(
            [int(joint["source_index"]) for joint in joints] == expected_joints,
            f"{name}: joint closure changed",
        )
        surface = row["surface_collision_memory"]
        if previous is not None:
            old_surface = previous["surface_collision_memory"]
            progress = float(surface["fighter_animation_blend_progress"])
            old_progress = float(old_surface["fighter_animation_blend_progress"])
            frames = float(surface["fighter_animation_blend_frames"])
            continuation = (
                row["action"] == previous["action"]
                and surface["fighter_motion_id"] == old_surface["fighter_motion_id"]
                and surface["fighter_animation_id"] == old_surface["fighter_animation_id"]
                and frames > 0.0
                and 0.0 < progress - old_progress
                and old_progress < frames
                and progress <= frames
            )
            if continuation:
                delta = progress - old_progress
                target_weight = delta / (frames - old_progress)
                current_weight = 1.0 - target_weight
                old_by_index = {
                    int(joint["source_index"]): joint for joint in closure(previous)
                }
                for joint in joints:
                    source_index = int(joint["source_index"])
                    if source_index < blend_start:
                        continue
                    flags = int(joint["fighter_bone_flags"]) >> 8
                    if (
                        not flags & FIGHTER_BONE_ANIMATED
                        or flags & FIGHTER_BONE_SKIP
                        or flags & FIGHTER_BONE_SECONDARY
                    ):
                        continue
                    actual = joint["pose"]
                    target = joint["animation_pose"]
                    old = old_by_index[source_index]["pose"]
                    copy_target = bool(flags & FIGHTER_BONE_COPY_TARGET) or progress >= frames
                    for field in ("translation", "scale"):
                        actual_values = vector(actual, field, 3)
                        target_values = vector(target, field, 3)
                        old_values = vector(old, field, 3)
                        expected_values = (
                            target_values
                            if copy_target
                            else tuple(
                                target_weight * new + current_weight * prior
                                for new, prior in zip(
                                    target_values, old_values, strict=True
                                )
                            )
                        )
                        difference = max(
                            abs(observed - expected)
                            for observed, expected in zip(
                                actual_values, expected_values, strict=True
                            )
                        )
                        maximum_local = max(maximum_local, difference)
                        require(
                            difference <= local_tolerance,
                            f"{name}: row={row['trace_frame']} joint={source_index} "
                            f"{field} difference={difference}",
                        )
                    expected_quaternion = (
                        pose_quaternion(target)
                        if copy_target
                        else slerp(
                            pose_quaternion(target),
                            pose_quaternion(old),
                            current_weight,
                        )
                    )
                    actual_quaternion = pose_quaternion(actual)
                    direct = max(
                        abs(left - right)
                        for left, right in zip(
                            actual_quaternion, expected_quaternion, strict=True
                        )
                    )
                    negated = max(
                        abs(left + right)
                        for left, right in zip(
                            actual_quaternion, expected_quaternion, strict=True
                        )
                    )
                    difference = min(direct, negated)
                    maximum_quaternion = max(maximum_quaternion, difference)
                    require(
                        difference <= quaternion_tolerance,
                        f"{name}: row={row['trace_frame']} joint={source_index} "
                        f"quaternion difference={difference}",
                    )
                    joint_comparisons += 1
                comparisons += 1
        previous = row
    return comparisons, joint_comparisons, maximum_local, maximum_quaternion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("repeat_capture", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    qualification = manifest.get("live_qualification")
    checkpoint = manifest.get("checkpoint_pack")
    require(isinstance(qualification, dict), "manifest qualification is missing")
    require(isinstance(checkpoint, dict), "manifest checkpoint pack is missing")
    captures: list[tuple[str, dict[str, Any]]] = []
    for name, path, digest_key in (
        ("control", args.capture, "capture_sha256"),
        ("repeat", args.repeat_capture, "repeat_capture_sha256"),
    ):
        raw = path.read_bytes()
        actual_digest = hashlib.sha256(raw).hexdigest()
        require(
            actual_digest == qualification[digest_key],
            f"{name}: capture SHA-256 changed",
        )
        capture = json.loads(raw)
        require(
            capture.get("disc", {}).get("sha256") == qualification["disc_sha256"],
            f"{name}: disc SHA-256 changed",
        )
        require(
            capture.get("oracle_execution", {}).get("release_artifact_sha256")
            == qualification["dolphin_release_artifact_sha256"],
            f"{name}: Dolphin artifact SHA-256 changed",
        )
        captures.append((name, capture))
    expected_joints = [int(value) for value in qualification["source_joint_indices"]]
    results = [
        verify_capture(
            name,
            capture,
            int(checkpoint["expected_rows"]),
            expected_joints,
            int(qualification["blend_start_source_index"]),
            float(qualification["local_tolerance"]),
            float(qualification["quaternion_tolerance"]),
        )
        for name, capture in captures
    ]
    semantic_payloads = [
        semantic_payload(capture["rows"]) for _, capture in captures
    ]
    converged_payloads: list[dict[str, Any]] = []
    converged_counts = qualification.get("converged_suffix_counts")
    require(
        isinstance(converged_counts, dict) and converged_counts,
        "manifest converged suffix counts are missing",
    )
    for prefix, expected_count in converged_counts.items():
        require(
            isinstance(prefix, str)
            and isinstance(expected_count, int)
            and expected_count > 0,
            "manifest converged suffix count is invalid",
        )
        indices = [
            index
            for index, row in enumerate(semantic_payloads[0])
            if row["label"].startswith(prefix)
        ]
        require(indices, f"capture has no rows for {prefix}")
        matching_suffix: list[int] = []
        for offset, index in enumerate(indices):
            if all(
                semantic_payloads[0][candidate]
                == semantic_payloads[1][candidate]
                for candidate in indices[offset:]
            ):
                matching_suffix = indices[offset:]
                break
        require(
            len(matching_suffix) == expected_count,
            f"{prefix} converged suffix count changed: "
            f"expected={expected_count} actual={len(matching_suffix)}",
        )
        converged_payloads.extend(
            semantic_payloads[0][index] for index in matching_suffix
        )
    semantic_digest = hashlib.sha256(
        json.dumps(
            converged_payloads, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    require(
        semantic_digest == qualification.get("semantic_sha256"),
        "converged transition semantic SHA-256 changed: "
        f"expected={qualification.get('semantic_sha256')} "
        f"actual={semantic_digest}",
    )
    print(
        "ssbm-hsd-transition-source=pass "
        f"captures={len(captures)} rows={sum(len(c['rows']) for _, c in captures)} "
        f"updates={sum(result[0] for result in results)} "
        f"joints={sum(result[1] for result in results)} "
        f"converged_rows={len(converged_payloads)} "
        f"local_max={max(result[2] for result in results):.9g} "
        f"quaternion_max={max(result[3] for result in results):.9g} "
        f"semantic_sha256={semantic_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
