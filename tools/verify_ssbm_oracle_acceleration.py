#!/usr/bin/env python3
"""Compare accelerated/control or independent same-runner oracle captures."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


POSITION_FIELDS = {
    "position_a",
    "position_b",
    "collision_position_a",
    "collision_position_b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_idle_pose_phase(
    row: dict[str, Any],
    *,
    action_key: str,
    action_frame_key: str,
    hurtbox_key: str,
    ecb_key: str,
) -> None:
    if row[action_key] != "STANDING":
        return

    # Menu timing can enter the looping idle animation at a different phase.
    # Active actions reset their animation cursor and remain strictly compared.
    row.pop(action_frame_key, None)
    memory = row.get("hitbox_memory")
    if not isinstance(memory, dict):
        return
    memory.pop(ecb_key, None)
    for hurtbox in memory.get(hurtbox_key, []):
        for field in POSITION_FIELDS:
            hurtbox.pop(field, None)


def remove_hitlag_pose_sample(
    row: dict[str, Any], *, hitlag_key: str, hurtbox_key: str
) -> None:
    # ExiAI intentionally skips display-side bone evaluation while fast-
    # forwarding. The collision decision is already complete on the first
    # post-hit frame, so qualify that decision but never use this pose sample
    # as imported geometry.
    if row.get(hitlag_key, 0) <= 0:
        return
    memory = row.get("hitbox_memory")
    if not isinstance(memory, dict):
        return
    for hurtbox in memory.get(hurtbox_key, []):
        for field in POSITION_FIELDS:
            hurtbox.pop(field, None)


def remove_inherited_pose_sample(
    row: dict[str, Any],
    *,
    action_key: str,
    hurtbox_key: str,
    ecb_key: str,
) -> None:
    # ftCo_8009388C enters GuardReflect with Ft_MF_SkipAnim and the current
    # animation cursor.  The motion state therefore inherits the preceding
    # pose instead of defining a GuardReflect pose of its own.  A menu-origin
    # idle phase can legitimately remain different across launches; continue
    # comparing all gameplay state and collision outcomes, but never import
    # these inherited display bones as GuardReflect geometry.
    if row[action_key] != "SHIELD_REFLECT":
        return
    memory = row.get("hitbox_memory")
    if not isinstance(memory, dict):
        return
    memory.pop(ecb_key, None)
    for hurtbox in memory.get(hurtbox_key, []):
        for field in POSITION_FIELDS:
            hurtbox.pop(field, None)


def normalized_capture(document: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(document)
    normalized.pop("oracle_execution", None)
    for row in normalized["rows"]:
        memory = row.get("hitbox_memory")
        if isinstance(memory, dict):
            memory.pop("fighter_address", None)
            memory.pop("opponent_fighter_address", None)
        remove_idle_pose_phase(
            row,
            action_key="action",
            action_frame_key="action_frame",
            hurtbox_key="fighter_hurtboxes",
            ecb_key="fighter_ecb",
        )
        remove_idle_pose_phase(
            row,
            action_key="opponent_action",
            action_frame_key="opponent_action_frame",
            hurtbox_key="opponent_hurtboxes",
            ecb_key="opponent_ecb",
        )
        remove_hitlag_pose_sample(
            row,
            hitlag_key="hitlag_left",
            hurtbox_key="fighter_hurtboxes",
        )
        remove_hitlag_pose_sample(
            row,
            hitlag_key="opponent_hitlag_left",
            hurtbox_key="opponent_hurtboxes",
        )
        remove_inherited_pose_sample(
            row,
            action_key="action",
            hurtbox_key="fighter_hurtboxes",
            ecb_key="fighter_ecb",
        )
        remove_inherited_pose_sample(
            row,
            action_key="opponent_action",
            hurtbox_key="opponent_hurtboxes",
            ecb_key="opponent_ecb",
        )
    return normalized


def first_difference(left: Any, right: Any, path: str = "root") -> str:
    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return f"{path}: keys {sorted(left)} != {sorted(right)}"
        for key in left:
            if left[key] != right[key]:
                return first_difference(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_value, right_value) in enumerate(zip(left, right)):
            if left_value != right_value:
                return first_difference(
                    left_value,
                    right_value,
                    f"{path}[{index}]",
                )
    elif left != right:
        return f"{path}: {left!r} != {right!r}"
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("control", type=Path)
    parser.add_argument("accelerated", type=Path)
    parser.add_argument(
        "--same-runner-repeat",
        action="store_true",
        help=(
            "compare two captures from the same oracle mode after removing "
            "address and non-action-owned idle-pose noise"
        ),
    )
    args = parser.parse_args()

    control = json.loads(args.control.read_text(encoding="utf-8"))
    accelerated = json.loads(args.accelerated.read_text(encoding="utf-8"))
    control_execution = control.get("oracle_execution", {})
    accelerated_execution = accelerated.get("oracle_execution", {})
    if args.same_runner_repeat:
        if control_execution.get("mode") != accelerated_execution.get("mode"):
            parser.error("repeat captures must use the same oracle mode")
    else:
        if control_execution.get("mode") != "stock":
            parser.error("control capture must use oracle_execution.mode=stock")
        if (
            accelerated_execution.get("mode")
            != "exiai-headless-null-fast-forward"
        ):
            parser.error("accelerated capture must use the ExiAI fast-forward mode")

    normalized_control = normalized_capture(control)
    normalized_accelerated = normalized_capture(accelerated)
    if normalized_control != normalized_accelerated:
        result = (
            "ssbm-oracle-repeat"
            if args.same_runner_repeat
            else "ssbm-oracle-acceleration"
        )
        raise SystemExit(
            f"{result}=fail "
            + first_difference(normalized_control, normalized_accelerated)
        )

    active_fighter_rows = sum(
        row["action"] != "STANDING" for row in control["rows"]
    )
    active_opponent_rows = sum(
        row["opponent_action"] != "STANDING" for row in control["rows"]
    )
    qualified_fighter_pose_rows = sum(
        row["action"] not in {"STANDING", "SHIELD_REFLECT"}
        and row["hitlag_left"] <= 0
        for row in control["rows"]
    )
    qualified_opponent_pose_rows = sum(
        row["opponent_action"] not in {"STANDING", "SHIELD_REFLECT"}
        and row["opponent_hitlag_left"] <= 0
        for row in control["rows"]
    )
    result = (
        "ssbm-oracle-repeat"
        if args.same_runner_repeat
        else "ssbm-oracle-acceleration"
    )
    digest_labels = (
        ("first_sha256", "repeat_sha256")
        if args.same_runner_repeat
        else ("control_sha256", "accelerated_sha256")
    )
    print(
        f"{result}=pass "
        f"rows={len(control['rows'])} "
        f"active_fighter_rows={active_fighter_rows} "
        f"active_opponent_rows={active_opponent_rows} "
        f"qualified_fighter_pose_rows={qualified_fighter_pose_rows} "
        f"qualified_opponent_pose_rows={qualified_opponent_pose_rows} "
        f"{digest_labels[0]}={sha256(args.control)} "
        f"{digest_labels[1]}={sha256(args.accelerated)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
