#!/usr/bin/env python3
"""Verify DAT-owned wait selection, HSD RNG, clocks, and repeat captures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hsd_figatree import decode_figatree
from hsd_joint_pose import fighter_animation_slice
from ssbm_dat import fighter_wait_animations, read_hsd_archive


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def semantic_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        memory = row["hitbox_memory"]
        result.append(
            {
                "label": row["label"],
                "action": row["action"],
                "action_frame": row["action_frame"],
                "facing": row["facing"],
                "grounded": row["grounded"],
                "position_x": row["position_x"],
                "position_y": row["position_y"],
                "animation_id": memory["fighter_animation_id"],
                "animation_frame": memory["fighter_animation_frame"],
                "animation_rate": memory["fighter_animation_rate"],
                "blend_frames": memory["fighter_animation_blend_frames"],
                "blend_progress": memory["fighter_animation_blend_progress"],
                "hurtboxes": [
                    {
                        "state": hurtbox["state"],
                        "state_bytes": hurtbox["state_bytes"],
                        "radius": hurtbox["radius"],
                        "collision_position_a": hurtbox["collision_position_a"],
                        "collision_position_b": hurtbox["collision_position_b"],
                        "bone_index": hurtbox["bone_index"],
                        "height": hurtbox["height"],
                        "grabbable": hurtbox["grabbable"],
                    }
                    for hurtbox in memory["fighter_hurtboxes"]
                ],
                "ecb": memory["fighter_ecb"],
            }
        )
    return result


def hsd_next(seed: int) -> tuple[int, int]:
    seed = (seed * 214013 + 2531011) & 0xFFFFFFFF
    return seed, seed >> 16


def select_wait(
    seed: int,
    current: int,
    base_wait: int,
    animations: tuple[Any, ...],
) -> tuple[int, Any, int, int]:
    draws = 0
    rejected = 0
    while True:
        seed, random_u16 = hsd_next(seed)
        draws += 1
        selection = 100 * random_u16 // 65536 + 1
        cumulative = 0
        selected = None
        for animation in animations:
            cumulative += animation.weight
            if selection <= cumulative:
                selected = animation
                break
        require(selected is not None, "wait animation weights do not cover HSD_Randi")
        if current != base_wait and selected.animation_id == current:
            rejected += 1
            continue
        return seed, selected, draws, rejected


def verify_case(
    capture_name: str,
    rows: list[dict[str, Any]],
    case: dict[str, Any],
    animations: tuple[Any, ...],
    frame_counts: dict[int, int],
) -> None:
    case_id = str(case["id"])
    label = f"common_hurt_wait_{case_id}_hold"
    selected_rows = [row for row in rows if row.get("label") == label]
    hold_ticks = int(case["hold_ticks"])
    require(
        len(selected_rows) == hold_ticks,
        f"{capture_name}/{case_id}: expected {hold_ticks} rows, got {len(selected_rows)}",
    )
    base_wait = animations[0].animation_id
    require(base_wait == 2, "Falcon base wait animation changed")
    current = base_wait
    frame = 0
    blend_frames = animations[0].blend_frames
    blend_progress = 1 if blend_frames > 0 else 0
    raw_seed_writes = case.get("source_random_seed_writes")
    require(
        isinstance(raw_seed_writes, list) and raw_seed_writes,
        f"{capture_name}/{case_id}: missing RNG isolation schedule",
    )
    seed_by_tick = {
        int(write["hold_tick"]): int(write["seed"])
        for write in raw_seed_writes
    }
    require(
        len(seed_by_tick) == len(raw_seed_writes),
        f"{capture_name}/{case_id}: duplicate RNG isolation tick",
    )
    consumed_seed_ticks: set[int] = set()

    for index, row in enumerate(selected_rows):
        memory = row.get("hitbox_memory")
        require(
            isinstance(memory, dict),
            f"{capture_name}/{case_id}: row {index} has no hitbox probe",
        )
        require(
            row.get("action") == "STANDING"
            and row.get("grounded") is True
            and memory.get("fighter_motion_id") == 14
            and memory.get("fighter_animation_id") == current
            and memory.get("fighter_animation_frame") == float(frame)
            and memory.get("fighter_animation_rate") == 1.0
            and memory.get("fighter_animation_blend_frames")
            == float(blend_frames)
            and memory.get("fighter_animation_blend_progress")
            == float(blend_progress),
            f"{capture_name}/{case_id}: lifecycle differs at row {index}",
        )
        frame += 1
        if frame >= frame_counts[current]:
            require(
                index in seed_by_tick,
                f"{capture_name}/{case_id}: missing terminal RNG isolation write",
            )
            consumed_seed_ticks.add(index)
            _, selected, _, _ = select_wait(
                seed_by_tick[index], current, base_wait, animations
            )
            current = selected.animation_id
            frame = 0
            blend_frames = selected.blend_frames
            blend_progress = 1 if blend_frames > 0 else 0
        elif blend_frames > 0 and blend_progress < blend_frames:
            blend_progress += 1
    require(
        consumed_seed_ticks == set(seed_by_tick),
        f"{capture_name}/{case_id}: unused RNG isolation write",
    )


def verify_uninterrupted_rng_case(
    case: dict[str, Any],
    animations: tuple[Any, ...],
) -> tuple[int, int]:
    base_wait = animations[0].animation_id
    seed = int(case["source_random_seed"])
    current = base_wait
    selected_submotions: list[int] = []
    draw_counts: list[int] = []
    rejection_counts: list[int] = []
    for _ in case["expected_uninterrupted_submotions"]:
        seed, selected, draws, rejected = select_wait(
            seed, current, base_wait, animations
        )
        current = selected.animation_id
        selected_submotions.append(current)
        draw_counts.append(draws)
        rejection_counts.append(rejected)
    require(
        selected_submotions == case["expected_uninterrupted_submotions"]
        and draw_counts == case["expected_uninterrupted_draws"]
        and rejection_counts == case["expected_uninterrupted_rejections"],
        f"{case['id']}: uninterrupted source RNG theorem differs",
    )
    return sum(draw_counts), sum(rejection_counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lifecycle_manifest", type=Path)
    parser.add_argument("pose_manifest", type=Path)
    parser.add_argument("fighter_dat", type=Path)
    parser.add_argument("animation_dat", type=Path)
    parser.add_argument("ftwaitanim_source", type=Path)
    parser.add_argument("random_source", type=Path)
    parser.add_argument("captures", type=Path, nargs="+")
    parser.add_argument(
        "--fresh-captures",
        action="store_true",
        help=(
            "accept new raw capture digests while retaining strict provenance, "
            "lifecycle, semantic-repeat, and pinned semantic-digest checks"
        ),
    )
    args = parser.parse_args()

    lifecycle = json.loads(args.lifecycle_manifest.read_text(encoding="utf-8"))
    pose = json.loads(args.pose_manifest.read_text(encoding="utf-8"))
    qualification = lifecycle.get("live_qualification")
    checkpoint = lifecycle.get("checkpoint_pack")
    require(isinstance(qualification, dict), "missing live qualification")
    require(isinstance(checkpoint, dict), "missing checkpoint pack")
    capture_specs = qualification.get("captures")
    require(
        isinstance(capture_specs, list)
        and len(capture_specs) == len(args.captures),
        "capture set does not match the qualification",
    )

    source_specs = (
        (args.ftwaitanim_source, "ftwaitanim_sha256"),
        (args.random_source, "random_sha256"),
    )
    source_texts: list[str] = []
    for path, digest_key in source_specs:
        raw = path.read_bytes()
        require(
            sha256(raw) == qualification[digest_key],
            f"source SHA-256 changed: {path}",
        )
        source_texts.append(raw.decode("utf-8"))
    wait_source, random_source = source_texts
    for token in (
        "HSD_Randi(100) + 1",
        "fp->anim_id == 2 || fp->anim_id == 31",
        "while (!inlineA0(fp) && fp->anim_id == temp)",
    ):
        require(token in wait_source, f"ftwaitanim source theorem changed: {token}")
    for token in (
        "*seed_ptr = *seed_ptr * 214013 + 2531011",
        "return *seed_ptr >> 0x10",
        "return max_val * HSD_Rand() / (1 << 16)",
    ):
        require(token in random_source, f"HSD RNG source theorem changed: {token}")

    fighter_raw = args.fighter_dat.read_bytes()
    animation_raw = args.animation_dat.read_bytes()
    require(
        sha256(fighter_raw) == pose["source_sha256"]["fighter_dat"]
        and sha256(animation_raw) == pose["source_sha256"]["animation_dat"],
        "owner DAT SHA-256 changed",
    )
    fighter = read_hsd_archive(fighter_raw)
    fighter_root = str(pose["fighter_root"])
    animations = fighter_wait_animations(fighter, fighter_root)
    require(
        animations
        and sum(animation.weight for animation in animations) == 100,
        "DAT wait animation weights changed",
    )
    frame_counts = {
        animation.animation_id: round(
            decode_figatree(
                fighter_animation_slice(
                    fighter,
                    animation_raw,
                    fighter_root,
                    animation.animation_id,
                )
            ).frame_count
        )
        for animation in animations
    }

    cases = checkpoint.get("capture_plan", {}).get("wait_lifecycle_cases")
    require(isinstance(cases, list) and cases, "missing wait lifecycle cases")
    semantic_payloads: list[list[dict[str, Any]]] = []
    total_rows = 0
    source_rng = [
        verify_uninterrupted_rng_case(case, animations) for case in cases
    ]
    total_draws = sum(item[0] for item in source_rng) * len(args.captures)
    total_rejected = sum(item[1] for item in source_rng) * len(args.captures)
    for spec, path in zip(capture_specs, args.captures, strict=True):
        raw = path.read_bytes()
        capture_name = str(spec["id"])
        if not args.fresh_captures:
            require(
                sha256(raw) == spec["sha256"],
                f"{capture_name}: capture SHA-256 changed",
            )
        capture = json.loads(raw)
        require(
            capture.get("disc", {}).get("sha256")
            == qualification["disc_sha256"]
            and capture.get("oracle_execution", {}).get(
                "release_artifact_sha256"
            )
            == qualification["dolphin_release_artifact_sha256"]
            and capture.get("common_hurt_geometry_route") is True,
            f"{capture_name}: capture provenance changed",
        )
        probe = capture.get("hitbox_memory_probe")
        require(
            isinstance(probe, dict)
            and probe.get("engine_version")
            == qualification["probe_engine_version"]
            and probe.get("decomp_revision")
            == qualification["decomp_revision"],
            f"{capture_name}: probe provenance changed",
        )
        rows = capture.get("rows")
        require(
            isinstance(rows, list)
            and len(rows) == int(checkpoint["expected_rows"]),
            f"{capture_name}: row count changed",
        )
        for case in cases:
            verify_case(
                capture_name, rows, case, animations, frame_counts
            )
        semantic_payloads.append(semantic_payload(rows))
        total_rows += len(rows)
    require(
        all(payload == semantic_payloads[0] for payload in semantic_payloads[1:]),
        "repeat capture semantic payload differs",
    )
    semantic_digest = sha256(
        json.dumps(
            semantic_payloads[0], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    require(
        semantic_digest == qualification["semantic_sha256"],
        "wait lifecycle semantic SHA-256 changed: "
        f"expected={qualification['semantic_sha256']} actual={semantic_digest}",
    )
    print(
        "ssbm-wait-lifecycle-source=pass "
        f"captures={len(args.captures)} cases={len(cases) * len(args.captures)} "
        f"rows={total_rows} rng_draws={total_draws} rejected={total_rejected} "
        f"weights="
        + ",".join(
            f"{animation.animation_id}:{animation.weight}"
            for animation in animations
        )
        + " frames="
        + ",".join(
            f"{animation_id}:{frame_counts[animation_id]}"
            for animation_id in frame_counts
        )
        + f" semantic_sha256={semantic_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
