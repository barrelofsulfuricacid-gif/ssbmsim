#!/usr/bin/env python3
"""Qualify source-evaluated action ECBs against pinned Dolphin captures."""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from hsd_figatree import decode_figatree
from hsd_joint_pose import (
    FIGHTER_ANIMATION_TRANSLATION_FLAG,
    evaluate_joint_matrices,
    fighter_animation_flags,
    fighter_animation_slice,
    fighter_model_scale,
    read_joint_tree,
)
from ssbm_dat import read_hsd_archive
from ssbm_ecb_pose import canonical_source_ecb, pose_f32
from verify_ssbm_dynamic_hurt_pose_source import source_joint_ecb_f32


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pinned_source(
    path: Path,
    manifest: dict[str, Any],
    source_name: str,
) -> bytes:
    raw = path.read_bytes()
    actual = sha256(raw)
    require(
        actual == manifest["source_sha256"].get(source_name),
        f"unexpected {source_name} SHA-256: {actual}",
    )
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qualification-key",
        default="action_ecb_qualification",
        help="manifest object containing the ECB qualification",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="report coordinate maxima without enforcing the tolerance",
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("fighter_dat", type=Path)
    parser.add_argument("animation_dat", type=Path)
    parser.add_argument("model_dat", type=Path)
    parser.add_argument("captures", type=Path, nargs="+")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    motion_specs = manifest.get("motions")
    require(isinstance(motion_specs, list), "manifest has no motion inventory")
    action_frame_offsets = {
        int(spec["submotion_index"]): int(spec["action_frame_offset"])
        for spec in motion_specs
        if isinstance(spec, dict) and "action_frame_offset" in spec
    }
    require(
        all(offset in (-1, 0) for offset in action_frame_offsets.values()),
        "action ECB source-frame offsets must be -1 or 0",
    )
    qualification = manifest.get(args.qualification_key)
    require(
        isinstance(qualification, dict),
        f"manifest has no {args.qualification_key} ECB qualification",
    )
    require_motion_offset = qualification.get(
        "require_motion_action_frame_offset", False
    )
    require(
        isinstance(require_motion_offset, bool),
        "require_motion_action_frame_offset must be boolean",
    )
    capture_specs = qualification.get("captures")
    require(
        isinstance(capture_specs, list) and capture_specs,
        "action ECB qualification has no captures",
    )
    specs_by_digest = {
        str(spec["sha256"]): spec
        for spec in capture_specs
        if isinstance(spec, dict)
    }
    require(
        len(specs_by_digest) == len(capture_specs),
        "action ECB capture digests must be unique",
    )
    supplied: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in args.captures:
        raw = path.read_bytes()
        digest = sha256(raw)
        require(digest in specs_by_digest, f"undeclared capture SHA-256: {digest}")
        require(digest not in supplied, f"duplicate capture SHA-256: {digest}")
        supplied[digest] = (path, json.loads(raw))
    require(
        set(supplied) == set(specs_by_digest),
        "supplied action ECB captures do not match the manifest",
    )

    fighter_raw = load_pinned_source(args.fighter_dat, manifest, "fighter_dat")
    animation_raw = load_pinned_source(
        args.animation_dat, manifest, "animation_dat"
    )
    model_raw = load_pinned_source(args.model_dat, manifest, "model_dat")
    fighter_archive = read_hsd_archive(fighter_raw)
    model_archive = read_hsd_archive(model_raw)
    fighter_root = str(manifest["fighter_root"])
    conversion = manifest["pose_conversion"]
    root_rotation_turns = conversion["root_rotation_turns"]
    joints = list(read_joint_tree(model_archive, str(manifest["model_root"])))
    model_scale = fighter_model_scale(fighter_archive, fighter_root)
    root = joints[0]
    joints[0] = replace(
        root,
        rotation=tuple(
            root.rotation[axis]
            + float(root_rotation_turns[axis]) * 2.0 * math.pi
            for axis in range(3)
        ),
        scale=(model_scale, model_scale, model_scale),
    )
    source_joints = tuple(joints)
    point_sets = manifest["joint_point_sets"]
    ecb_sets = [point_set for point_set in point_sets if point_set["id"] == "ecb"]
    require(len(ecb_sets) == 1, "manifest ECB joint point set is not unique")
    ecb_source_joints = tuple(ecb_sets[0]["source_joint_indices"])
    tolerance = float(qualification["coordinate_tolerance_f32"])
    require(tolerance >= 0, "action ECB tolerance must be nonnegative")
    disc_sha256 = qualification["disc_sha256"]
    probe_version = qualification["probe_engine_version"]
    decomp_revision = qualification["decomp_revision"]
    animation_cache: dict[int, Any] = {}
    animation_flags_cache: dict[int, int] = {}
    total_rows = 0
    total_unique_frames = 0
    maximum_difference = 0.0

    for digest, spec in specs_by_digest.items():
        path, capture = supplied[digest]
        require(
            capture.get("fighter") == manifest["fighter"],
            f"{spec['id']}: fighter mismatch",
        )
        require(
            capture.get("disc", {}).get("sha256") == disc_sha256,
            f"{spec['id']}: disc mismatch",
        )
        probe = capture.get("hitbox_memory_probe")
        require(isinstance(probe, dict), f"{spec['id']}: missing ECB probe")
        require(
            probe.get("engine_version") == probe_version
            and probe.get("decomp_revision") == decomp_revision,
            f"{spec['id']}: probe provenance mismatch",
        )
        rows = capture.get("rows")
        require(isinstance(rows, list), f"{spec['id']}: missing capture rows")
        cases = spec.get("cases", qualification.get("cases"))
        require(
            isinstance(cases, list) and cases,
            f"{spec['id']}: action ECB qualification has no cases",
        )
        for case in cases:
            action = str(case["source_action"])
            submotion = int(case["submotion_index"])
            compared_components = case.get(
                "compared_components",
                qualification.get(
                    "compared_components", ["top", "bottom", "right", "left"]
                ),
            )
            require(
                isinstance(compared_components, list)
                and compared_components
                and len(set(compared_components)) == len(compared_components)
                and all(
                    component in ("top", "bottom", "right", "left")
                    for component in compared_components
                ),
                f"{spec['id']}/{action}: invalid compared ECB components",
            )
            if require_motion_offset:
                require(
                    submotion in action_frame_offsets and
                    "source_frame_offset" not in case,
                    f"{spec['id']}/{action}: source-frame offset must be "
                    "owned by the motion inventory",
                )
            selected = [row for row in rows if row.get("action") == action]
            frames = sorted({float(row["action_frame"]) for row in selected})
            first_frame = int(case["first_frame"])
            last_frame = int(case["last_frame"])
            require(
                frames == [float(frame) for frame in range(first_frame, last_frame + 1)],
                f"{spec['id']}/{action}: incomplete frame sequence",
            )
            if submotion not in animation_cache:
                animation_cache[submotion] = decode_figatree(
                    fighter_animation_slice(
                        fighter_archive,
                        animation_raw,
                        fighter_root,
                        submotion,
                    )
                )
                animation_flags_cache[submotion] = fighter_animation_flags(
                    fighter_archive,
                    fighter_root,
                    submotion,
                )
            entry_submotion = int(case.get("entry_submotion_index", submotion))
            if entry_submotion not in animation_cache:
                animation_cache[entry_submotion] = decode_figatree(
                    fighter_animation_slice(
                        fighter_archive,
                        animation_raw,
                        fighter_root,
                        entry_submotion,
                    )
                )
                animation_flags_cache[entry_submotion] = fighter_animation_flags(
                    fighter_archive,
                    fighter_root,
                    entry_submotion,
                )
            case_maximum = 0
            for row in selected:
                facing = row.get("facing")
                memory = row.get("hitbox_memory")
                require(
                    facing in (-1, 1) and isinstance(memory, dict),
                    f"{spec['id']}/{action}: invalid row",
                )
                captured_ecb = memory.get("fighter_ecb")
                require(
                    isinstance(captured_ecb, dict),
                    f"{spec['id']}/{action}: missing fighter ECB",
                )
                action_frame = float(row["action_frame"])
                is_entry = (
                    "entry_source_frame" in case
                    and action_frame
                    <= float(
                        case.get(
                            "entry_pose_through_frame",
                            case["first_frame"],
                        )
                    )
                )
                evaluated_submotion = entry_submotion if is_entry else submotion
                evaluated_frame = (
                    float(case["entry_source_frame"])
                    if is_entry and "entry_source_frame" in case
                    else action_frame
                    + float(
                        case.get(
                            "source_frame_offset",
                            action_frame_offsets.get(submotion, 0),
                        )
                    )
                )
                if is_entry:
                    evaluated_grounded = bool(
                        case.get("entry_grounded", case["grounded"])
                    )
                    evaluated_bottom_locked = bool(
                        case.get("entry_bottom_locked", False)
                    )
                else:
                    evaluated_grounded = (
                        bool(row["grounded"])
                        if bool(case.get("grounded_from_capture", False))
                        else bool(case["grounded"])
                    )
                    bottom_lock_ranges = case.get(
                        "bottom_lock_frame_ranges", []
                    )
                    require(
                        isinstance(bottom_lock_ranges, list),
                        f"{spec['id']}/{action}: invalid bottom-lock ranges",
                    )
                    evaluated_bottom_locked = bool(
                        case.get("bottom_locked", False)
                    ) or bool(
                        case.get("bottom_lock_through_frame", -1)
                        >= action_frame
                    ) or any(
                        isinstance(frame_range, list)
                        and len(frame_range) == 2
                        and float(frame_range[0]) <= action_frame
                        <= float(frame_range[1])
                        for frame_range in bottom_lock_ranges
                    )
                locked_bottom_y_f32: float | None = None
                if evaluated_bottom_locked:
                    lock_source = case.get("locked_bottom_source")
                    for candidate in case.get("locked_bottom_sources", []):
                        require(
                            isinstance(candidate, dict),
                            f"{spec['id']}/{action}: invalid lock source",
                        )
                        if (
                            float(candidate["first_frame"])
                            <= action_frame
                            <= float(candidate["last_frame"])
                        ):
                            lock_source = candidate
                            break
                    if lock_source is None:
                        locked_bottom_y_f32 = 0.0
                    else:
                        require(
                            isinstance(lock_source, dict),
                            f"{spec['id']}/{action}: invalid lock source",
                        )
                        lock_submotion = int(lock_source["submotion_index"])
                        if lock_submotion not in animation_cache:
                            animation_cache[lock_submotion] = decode_figatree(
                                fighter_animation_slice(
                                    fighter_archive,
                                    animation_raw,
                                    fighter_root,
                                    lock_submotion,
                                )
                            )
                        lock_pose = source_joint_ecb_f32(
                            evaluate_joint_matrices(
                                source_joints,
                                animation_cache[lock_submotion],
                                float(lock_source["source_frame"]),
                            ),
                            ecb_source_joints,
                            int(
                                manifest[
                                    "blend_copy_target_source_joint_indices"
                                ][0]
                            ),
                            bool(lock_source["grounded"]),
                        )
                        locked_bottom_y_f32 = lock_pose["bottom"][1]
                expected = pose_f32(canonical_source_ecb(captured_ecb, int(facing)))
                actual = source_joint_ecb_f32(
                    evaluate_joint_matrices(
                        source_joints,
                        animation_cache[evaluated_submotion],
                        evaluated_frame,
                    ),
                    ecb_source_joints,
                    int(manifest["blend_copy_target_source_joint_indices"][0])
                    if animation_flags_cache[evaluated_submotion]
                    & FIGHTER_ANIMATION_TRANSLATION_FLAG
                    else None,
                    evaluated_grounded,
                    locked_bottom_y_f32,
                )
                difference = max(
                    abs(actual[point][axis] - expected[point][axis])
                    for point in compared_components
                    for axis in (0, 1)
                )
                if not args.report_only:
                    require(
                        difference <= tolerance,
                        f"{spec['id']}/{action}: trace={row['trace_frame']} "
                        f"frame={row['action_frame']} source_frame={evaluated_frame} "
                        f"float32 difference={difference} "
                        f"source={actual} capture={expected}",
                    )
                case_maximum = max(case_maximum, difference)
            print(
                "ssbm-hsd-action-ecb-case="
                f"{'report' if args.report_only else 'pass'} "
                f"capture={spec['id']} action={action} rows={len(selected)} "
                f"unique_frames={len(frames)} max_f32={case_maximum} "
                f"within_tolerance={int(case_maximum <= tolerance)} "
                f"components={','.join(compared_components)}"
            )
            total_rows += len(selected)
            total_unique_frames += len(frames)
            maximum_difference = max(maximum_difference, case_maximum)

    print(
        "ssbm-hsd-action-ecb-source="
        f"{'report' if args.report_only else 'pass'} "
        f"captures={len(capture_specs)} motions={len(animation_cache)} "
        f"rows={total_rows} unique_frames={total_unique_frames} "
        f"max_f32={maximum_difference}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
