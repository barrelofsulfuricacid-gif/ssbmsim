#!/usr/bin/env python3
"""Qualify source-evaluated action hurt poses against Dolphin captures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hsd_figatree import decode_figatree
from hsd_joint_pose import (
    FIGHTER_ANIMATION_TRANSLATION_FLAG,
    evaluate_joint_matrices,
    fighter_animation_flags,
    fighter_animation_slice,
)
from ssbm_collision import binary32
from ssbm_ecb_pose import canonical_source_ecb, pose_f32
from verify_ssbm_dynamic_hurt_pose_source import (
    build_hurt_pose_source,
    compare_hurt_pose_f32,
    load_pinned_source,
    require,
    source_joint_ecb_f32,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("fighter_dat", type=Path)
    parser.add_argument("animation_dat", type=Path)
    parser.add_argument("common_dat", type=Path)
    parser.add_argument("model_dat", type=Path)
    parser.add_argument("captures", type=Path, nargs="+")
    parser.add_argument(
        "--fresh-captures",
        action="store_true",
        help=(
            "map captures to manifest IDs by position while retaining strict "
            "provenance, source-clock, geometry, and tolerance checks"
        ),
    )
    parser.add_argument(
        "--qualification-key",
        default="action_hurt_qualification",
        help="manifest object owning the capture/source theorem",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    qualification = manifest.get(args.qualification_key)
    require(
        isinstance(qualification, dict),
        "manifest has no action hurt qualification",
    )
    cases = qualification.get("cases")
    capture_specs = qualification.get("captures")
    require(
        cases is None or (isinstance(cases, list) and cases),
        "action hurt qualification cases are invalid",
    )
    require(
        isinstance(capture_specs, list) and capture_specs,
        "action hurt qualification has no captures",
    )
    specs_by_digest = {
        str(spec["sha256"]): spec
        for spec in capture_specs
        if isinstance(spec, dict)
    }
    specs_by_id = {
        str(spec["id"]): spec
        for spec in capture_specs
        if isinstance(spec, dict) and "id" in spec
    }
    require(
        len(specs_by_digest) == len(capture_specs),
        "action hurt capture digests must be unique",
    )
    require(
        len(specs_by_id) == len(capture_specs),
        "action hurt capture IDs must be unique",
    )
    supplied_by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    if args.fresh_captures:
        require(
            len(args.captures) == len(capture_specs),
            "fresh action hurt capture count does not match the manifest",
        )
        for spec, path in zip(capture_specs, args.captures, strict=True):
            supplied_by_id[str(spec["id"])] = (
                path,
                json.loads(path.read_bytes()),
            )
    else:
        supplied: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path in args.captures:
            raw = path.read_bytes()
            digest = sha256(raw)
            require(
                digest in specs_by_digest,
                f"undeclared capture SHA-256: {digest}",
            )
            require(
                digest not in supplied,
                f"duplicate capture SHA-256: {digest}",
            )
            supplied[digest] = (path, json.loads(raw))
        require(
            set(supplied) == set(specs_by_digest),
            "supplied action hurt captures do not match the manifest",
        )
        supplied_by_id = {
            str(spec["id"]): supplied[digest]
            for digest, spec in specs_by_digest.items()
        }

    fighter_raw = load_pinned_source(args.fighter_dat, manifest, "fighter_dat")
    animation_raw = load_pinned_source(
        args.animation_dat,
        manifest,
        "animation_dat",
    )
    common_raw = load_pinned_source(args.common_dat, manifest, "common_dat")
    model_raw = load_pinned_source(args.model_dat, manifest, "model_dat")
    source = build_hurt_pose_source(
        manifest,
        fighter_raw,
        animation_raw,
        common_raw,
        model_raw,
    )
    tolerance = float(qualification["coordinate_tolerance_f32"])
    require(tolerance >= 0, "action hurt tolerance must be nonnegative")
    frame_tolerance = float(qualification.get("frame_tolerance_f32", 0.0))
    rate_tolerance = float(qualification.get("rate_tolerance_f32", 0.0))
    require(
        frame_tolerance >= 0 and rate_tolerance >= 0,
        "action hurt clock tolerances must be nonnegative",
    )
    compare_ecb = qualification.get("compare_ecb", False)
    require(isinstance(compare_ecb, bool), "compare_ecb must be boolean")
    ecb_source_joints: tuple[int, ...] = ()
    ecb_reference_joint: int | None = None
    if compare_ecb:
        point_set_id = qualification.get("ecb_joint_point_set_id")
        point_sets = manifest.get("joint_point_sets")
        matching = [
            point_set
            for point_set in point_sets
            if isinstance(point_set, dict) and point_set.get("id") == point_set_id
        ] if isinstance(point_sets, list) else []
        require(len(matching) == 1, "ECB joint point set is not unique")
        raw_indices = matching[0].get("source_joint_indices")
        require(
            isinstance(raw_indices, list)
            and raw_indices
            and all(isinstance(index, int) for index in raw_indices),
            "ECB source joint indices are invalid",
        )
        ecb_source_joints = tuple(int(index) for index in raw_indices)
        copy_targets = manifest.get("blend_copy_target_source_joint_indices")
        require(
            isinstance(copy_targets, list)
            and len(copy_targets) == 1
            and isinstance(copy_targets[0], int),
            "ECB reference joint is invalid",
        )
        ecb_reference_joint = int(copy_targets[0])
    animations: dict[int, Any] = {}
    animation_flags: dict[int, int] = {}

    def ensure_animation(submotion: int) -> None:
        if submotion in animations:
            return
        animations[submotion] = decode_figatree(
            fighter_animation_slice(
                source.fighter_archive,
                source.animation_raw,
                source.fighter_root,
                submotion,
            )
        )
        animation_flags[submotion] = fighter_animation_flags(
            source.fighter_archive,
            source.fighter_root,
            submotion,
        )

    total_cases = 0
    total_samples = 0
    maximum_difference = 0.0
    maximum_ecb_difference = 0.0

    for spec in capture_specs:
        capture_name = str(spec["id"])
        _, capture = supplied_by_id[capture_name]
        require(
            capture.get("fighter") == manifest["fighter"],
            f"{capture_name}: fighter mismatch",
        )
        require(
            capture.get("disc", {}).get("sha256")
            == qualification["disc_sha256"],
            f"{capture_name}: disc mismatch",
        )
        require(
            capture.get("oracle_execution", {}).get("release_artifact_sha256")
            == qualification["dolphin_release_artifact_sha256"],
            f"{capture_name}: Dolphin oracle artifact mismatch",
        )
        require(
            capture.get(str(qualification["capture_route_field"])) is True,
            f"{capture_name}: wrong capture route",
        )
        probe = capture.get("hitbox_memory_probe")
        require(
            isinstance(probe, dict)
            and probe.get("engine_version")
            == qualification["probe_engine_version"]
            and probe.get("decomp_revision")
            == qualification["decomp_revision"],
            f"{capture_name}: probe provenance mismatch",
        )
        rows = capture.get("rows")
        require(isinstance(rows, list), f"{capture_name}: missing capture rows")
        capture_cases = spec.get("cases")
        repeat_of = spec.get("repeat_of")
        if capture_cases is None and repeat_of is not None:
            repeated_spec = specs_by_id.get(str(repeat_of))
            require(
                repeated_spec is not None and repeated_spec is not spec,
                f"{capture_name}: invalid repeated capture reference",
            )
            capture_cases = repeated_spec.get("cases")
        if capture_cases is None:
            capture_cases = cases
        require(
            isinstance(capture_cases, list) and capture_cases,
            f"{capture_name}: action hurt qualification has no cases",
        )
        for case in capture_cases:
            total_cases += 1
            action = str(case["source_action"])
            submotion = int(case["submotion_index"])
            label = case.get("label")
            label_suffix = case.get("label_suffix")
            excluded_label_suffixes = case.get("excluded_label_suffixes", [])
            require(
                (label is None or isinstance(label, str))
                and (
                    label_suffix is None
                    or (isinstance(label_suffix, str) and label_suffix)
                )
                and not (label is not None and label_suffix is not None),
                f"{capture_name}/{action}: invalid label filter",
            )
            require(
                isinstance(excluded_label_suffixes, list)
                and all(
                    isinstance(suffix, str) and suffix
                    for suffix in excluded_label_suffixes
                ),
                f"{capture_name}/{action}: invalid excluded label suffixes",
            )
            minimum_frame_f32 = case.get("minimum_source_frame_exclusive_f32")
            maximum_frame_f32 = case.get("maximum_source_frame_inclusive_f32")
            selected = []
            row_indices: dict[int, int] = {}
            for row_index, row in enumerate(rows):
                if row.get("action") != action or (
                    label is not None and row.get("label") != label
                ) or (
                    label_suffix is not None
                    and not str(row.get("label", "")).endswith(label_suffix)
                ) or any(
                    str(row.get("label", "")).endswith(suffix)
                    for suffix in excluded_label_suffixes
                ):
                    continue
                memory = row.get("hitbox_memory")
                require(
                    isinstance(memory, dict),
                    f"{capture_name}/{action}: missing hitbox memory",
                )
                if memory.get("fighter_animation_id") != submotion:
                    continue
                source_frame = memory.get("fighter_animation_frame")
                require(
                    isinstance(source_frame, (int, float)),
                    f"{capture_name}/{action}: invalid source frame",
                )
                source_frame_f32 = binary32(float(source_frame))
                if (
                    minimum_frame_f32 is not None
                    and source_frame_f32 <= float(minimum_frame_f32)
                ):
                    continue
                if (
                    maximum_frame_f32 is not None
                    and source_frame_f32 > float(maximum_frame_f32)
                ):
                    continue
                selected.append(row)
                row_indices[id(row)] = row_index
            require(
                len(selected) == int(case["expected_samples"]),
                f"{capture_name}/{action}: expected "
                f"{case['expected_samples']} rows, got {len(selected)}",
            )
            source_frames_f32 = [
                binary32(
                    float(row["hitbox_memory"]["fighter_animation_frame"])
                )
                for row in selected
            ]
            expected_frames_f32 = case.get("expected_source_frames_f32")
            expected_frame_pattern_f32 = case.get(
                "expected_source_frame_pattern_f32"
            )
            require(
                expected_frames_f32 is None or expected_frame_pattern_f32 is None,
                f"{capture_name}/{action}: source-frame expectations overlap",
            )
            if expected_frames_f32 is not None:
                require(
                    isinstance(expected_frames_f32, list)
                    and len(expected_frames_f32) == len(selected)
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in expected_frames_f32
                    ),
                    f"{capture_name}/{action}: invalid expected source frames",
                )
                require(
                    all(
                        abs(actual - expected) <= frame_tolerance
                        for actual, expected in zip(
                            source_frames_f32,
                            [binary32(value) for value in expected_frames_f32],
                            strict=True,
                        )
                    ),
                    f"{capture_name}/{action}: source-frame sequence differs",
                )
            elif expected_frame_pattern_f32 is not None:
                repetitions = case.get("expected_source_frame_pattern_repetitions")
                require(
                    isinstance(expected_frame_pattern_f32, list)
                    and expected_frame_pattern_f32
                    and all(
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        for value in expected_frame_pattern_f32
                    )
                    and isinstance(repetitions, int)
                    and repetitions > 0,
                    f"{capture_name}/{action}: invalid source-frame pattern",
                )
                expected_frames_f32 = (
                    expected_frame_pattern_f32 * repetitions
                )
                require(
                    len(expected_frames_f32) == len(selected)
                    and all(
                        abs(actual - expected) <= frame_tolerance
                        for actual, expected in zip(
                            source_frames_f32,
                            [binary32(value) for value in expected_frames_f32],
                            strict=True,
                        )
                    ),
                    f"{capture_name}/{action}: source-frame pattern differs",
                )
            else:
                first_source_frame = int(case["first_source_frame"])
                last_source_frame = int(case["last_source_frame"])
                source_frame_cycle = case.get("source_frame_cycle")
                if source_frame_cycle is None:
                    expected_frames_f32 = [
                        binary32(float(frame))
                        for frame in range(
                            first_source_frame,
                            last_source_frame + 1,
                        )
                    ]
                else:
                    cycle = int(source_frame_cycle)
                    require(
                        cycle > 0
                        and first_source_frame >= 0
                        and last_source_frame == cycle - 1,
                        f"{capture_name}/{action}: invalid source-frame cycle",
                    )
                    expected_frames_f32 = [
                        binary32(float((first_source_frame + index) % cycle))
                        for index in range(int(case["expected_samples"]))
                    ]
                require(
                    source_frames_f32 == expected_frames_f32,
                    f"{capture_name}/{action}: incomplete source-frame sequence",
                )
            expected_rate_f32 = case.get("expected_animation_rate_f32")
            if expected_rate_f32 is not None:
                require(
                    isinstance(expected_rate_f32, (int, float))
                    and not isinstance(expected_rate_f32, bool),
                    "invalid animation rate",
                )
                expected_rate_f32 = binary32(float(expected_rate_f32))
                actual_rates_f32 = [
                    binary32(
                        float(row["hitbox_memory"]["fighter_animation_rate"])
                    )
                    for row in selected
                ]
                require(
                    all(
                        abs(actual - expected_rate_f32) <= rate_tolerance
                        for actual in actual_rates_f32
                    ),
                    f"{capture_name}/{action}: animation rate differs",
                )
            ensure_animation(submotion)
            case_maximum = 0
            case_ecb_maximum = 0
            compared_ecb_components = case.get(
                "compared_ecb_components",
                ["top", "bottom", "right", "left"],
            )
            require(
                isinstance(compared_ecb_components, list)
                and compared_ecb_components
                and len(set(compared_ecb_components))
                    == len(compared_ecb_components)
                and all(
                    component in ("top", "bottom", "right", "left")
                    for component in compared_ecb_components
                ),
                f"{capture_name}/{action}: invalid compared ECB components",
            )
            for row in selected:
                case_maximum = max(
                    case_maximum,
                    compare_hurt_pose_f32(
                        row,
                        source.source_joints,
                        animations[submotion],
                        source.capsules,
                        source.layout,
                        source.coordinate_scale_f32,
                        source.axis_sign,
                        tolerance,
                        f"{capture_name}/{action}",
                    ),
                )
                if compare_ecb and bool(case.get("compare_ecb", True)):
                    memory = row["hitbox_memory"]
                    frame = float(memory["fighter_animation_frame"])
                    facing = int(row["facing"])
                    ecb_submotion = submotion
                    ecb_grounded = bool(row["grounded"])
                    ecb_owner = case.get("ecb_owner", "current-action")
                    require(
                        ecb_owner in (
                            "current-action",
                            "previous-row-post-animation",
                        ),
                        f"{capture_name}/{action}: invalid ECB owner",
                    )
                    if ecb_owner == "previous-row-post-animation":
                        row_index = row_indices[id(row)]
                        require(
                            row_index > 0,
                            f"{capture_name}/{action}: mixed ECB row has no predecessor",
                        )
                        previous_row = rows[row_index - 1]
                        previous_memory = previous_row.get("hitbox_memory")
                        require(
                            isinstance(previous_memory, dict)
                            and isinstance(
                                previous_memory.get("fighter_animation_id"), int
                            )
                            and isinstance(
                                previous_memory.get("fighter_animation_frame"),
                                (int, float),
                            )
                            and isinstance(
                                previous_memory.get("fighter_animation_rate"),
                                (int, float),
                            ),
                            f"{capture_name}/{action}: invalid preceding ECB owner",
                        )
                        ecb_submotion = int(
                            previous_memory["fighter_animation_id"]
                        )
                        frame = float(
                            previous_memory["fighter_animation_frame"]
                        ) + float(previous_memory["fighter_animation_rate"])
                        facing = int(previous_row["facing"])
                        ecb_grounded = bool(previous_row["grounded"])
                        ensure_animation(ecb_submotion)
                    ecb_owner_facing = case.get("ecb_owner_facing")
                    require(
                        ecb_owner_facing is None
                        or (
                            isinstance(ecb_owner_facing, int)
                            and not isinstance(ecb_owner_facing, bool)
                            and ecb_owner_facing in (-1, 1)
                        ),
                        f"{capture_name}/{action}: invalid ECB owner facing",
                    )
                    if ecb_owner_facing is not None:
                        facing = int(ecb_owner_facing)
                    captured_ecb = memory.get("fighter_ecb")
                    require(
                        isinstance(captured_ecb, dict),
                        f"{capture_name}/{action}: missing fighter ECB",
                    )
                    expected_ecb = pose_f32(
                        canonical_source_ecb(captured_ecb, facing)
                    )
                    actual_ecb = source_joint_ecb_f32(
                        evaluate_joint_matrices(
                            source.source_joints,
                            animations[ecb_submotion],
                            frame,
                        ),
                        ecb_source_joints,
                        ecb_reference_joint
                        if animation_flags[ecb_submotion]
                        & FIGHTER_ANIMATION_TRANSLATION_FLAG
                        else None,
                        ecb_grounded
                        if bool(case.get("ecb_grounded_from_capture", False))
                        else True,
                        0
                        if bool(case.get("ecb_lock_ticks_from_capture", False))
                        and int(memory.get("fighter_ecb_lock_ticks", 0)) > 0
                        else None,
                    )
                    ecb_component_differences = {
                        point: max(
                            abs(
                                actual_ecb[point][axis]
                                - expected_ecb[point][axis]
                            )
                            for axis in (0, 1)
                        )
                        for point in compared_ecb_components
                    }
                    ecb_difference = max(ecb_component_differences.values())
                    require(
                        ecb_difference <= tolerance,
                        f"{capture_name}/{action}: trace={row['trace_frame']} "
                        f"ECB float32 difference={ecb_difference} "
                        f"components={ecb_component_differences} "
                        f"actual={actual_ecb} expected={expected_ecb}",
                    )
                    case_ecb_maximum = max(case_ecb_maximum, ecb_difference)
            print(
                "ssbm-hsd-action-hurt-source-case=pass "
                f"capture={capture_name} action={action} "
                f"samples={len(selected)} max_f32={case_maximum} "
                f"ecb_max_f32={case_ecb_maximum}"
            )
            total_samples += len(selected)
            maximum_difference = max(maximum_difference, case_maximum)
            maximum_ecb_difference = max(
                maximum_ecb_difference, case_ecb_maximum
            )

    print(
        "ssbm-hsd-action-hurt-source=pass "
        f"captures={len(capture_specs)} cases={total_cases} "
        f"motions={len(animations)} samples={total_samples} "
        f"capsules={total_samples * len(source.capsules)} "
        f"max_f32={maximum_difference} ecb_max_f32={maximum_ecb_difference}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
