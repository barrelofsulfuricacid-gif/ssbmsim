#!/usr/bin/env python3
"""Capture deterministic SSBM movement from Dolphin with scripted inputs.

This developer tool intentionally depends on a separately installed libmelee,
Dolphin/Slippi build, and an owner-supplied GALE01 revision 2 image. None of
those external assets are copied into the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import math
import mmap
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import time
import types

import melee
from melee import console as melee_console

from ssbm_checkpoint_manifest import projected_manifest
from ssbm_ucf_oracle import (
    configure_ucf084_oracle,
    ucf084_runtime_hook_target,
    verify_ucf084_oracle,
)


SPECIAL_GEOMETRY_SOURCE_KEYS = {
    "neutral_ground": "0x12d",
    "neutral_air": "0x12e",
    "side_ground_miss": "0x12f",
    "side_ground_edge": "0x12f",
    "side_ground_hit": "0x130",
    "side_ground_item_hit": "0x130",
    "side_air_miss": "0x131",
    "side_air_hit": "0x132",
    "side_air_hit_floor": "0x132",
    "up_ground_miss": "0x133",
    "up_air_miss": "0x134",
    "up_air_miss_natural": "0x134",
    "up_air_ledge_grab": "0x134",
    "up_air_ledge_grab_behind": "0x134",
    "up_ground_catch": "0x135",
    "up_air_catch": "0x135",
    "down_ground": "0x137",
    "down_ground_hit": "0x137",
    "down_ground_wall": "0x137",
    "down_ground_edge": "0x13b",
    "down_air": "0x139",
    "down_air_land": "0x13a",
}

EXIAI_020_APPIMAGE_SHA256 = (
    "87e9ef6d80ed03354a1647d0616016dbc91399aa9e86a69ae5a398edd0a0c2bd"
)

# baselib/random.c owns this global LCG seed. gmmain.c initializes it from
# OSGetTick(), so checkpoint packs that exercise gameplay randomness must pin
# it as part of their declared initial state to remain reproducible across
# independent Dolphin boots.
HSD_RANDOM_SEED_ADDRESS = 0x804D5F90
HSD_RANDOM_SEED_POINTER_ADDRESS = 0x804D5F94
CHECKPOINT_SLOT_COUNT = 16

# MnSlMap.usd's stage-entry table maps St_Kind_Shrine (0x0E) to entry 5. The
# matching x90 anchor animation resolves to (-3.3, 15.7), and odd entry 5 uses
# the x40 template's y=-5.6 child. Keep the resulting source-derived cursor
# coordinate here instead of relying on a hand-tuned menu click.
HYRULE_TEMPLE_STAGE_CURSOR = (-3.3, 10.1)


def input_trace(
    platform_only: bool = False,
    platform_drop_ecb_only: bool = False,
    airborne_ecb_only: bool = False,
    airborne_landing_only: bool = False,
    push_only: bool = False,
    shield_only: bool = False,
    shield_break_orientation_only: bool = False,
    shield_geometry_only: bool = False,
    shield_geometry_sweep_only: bool = False,
    shield_guardon_landing_only: bool = False,
    shield_hit_only: bool = False,
    shield_collision_only: bool = False,
    moving_hit_sweep_only: bool = False,
    common_hurt_geometry_only: bool = False,
    checkpoint_isolated: bool = False,
    damage_hit_only: bool = False,
    defense_state_only: bool = False,
    special_acquisition_only: bool = False,
    attack_iasa_only: bool = False,
    aerial_iasa_only: bool = False,
    aerial_attack_ecb_only: bool = False,
    aerial_attack_landing_only: bool = False,
    ground_attack_iasa_only: bool = False,
    hitbox_geometry_only: bool = False,
    throw_geometry_only: bool = False,
    special_geometry_only: bool = False,
    ground_attack_moves: tuple[str, ...] | None = None,
    special_geometry_moves: tuple[str, ...] | None = None,
    falcon_frame_data: dict[str, object] | None = None,
    checkpoint_capture_plan: dict[str, object] | None = None,
    selected_checkpoint_start_labels: tuple[str, ...] = (),
    shield_hit_pressure: float = 0.35,
) -> list[dict[str, object]]:
    trace: list[dict[str, object]] = []

    def extend(label: str, xs: list[float]) -> None:
        for x in xs:
            trace.append(command(label, main_x=x))

    def command(
        label: str,
        *,
        main_x: float = 0.5,
        main_y: float = 0.5,
        c_x: float = 0.5,
        c_y: float = 0.5,
        left_shoulder: float = 0.0,
        right_shoulder: float = 0.0,
        digital_left: bool = False,
        digital_right: bool = False,
        jump: bool = False,
        attack: bool = False,
        special: bool = False,
        grab: bool = False,
        taunt: bool = False,
        opponent_main_x: float = 0.5,
        opponent_main_y: float = 0.5,
        opponent_attack: bool = False,
        opponent_grab: bool = False,
        opponent_jump: bool = False,
        fighter_x_override: float | None = None,
        fighter_x_from_item_offset: float | None = None,
        fighter_y_override: float | None = None,
        fighter_facing_override: float | None = None,
        fighter_damage_override: float | None = None,
        fighter_self_velocity_x_override: float | None = None,
        fighter_self_velocity_y_override: float | None = None,
        fighter_knockback_velocity_x_override: float | None = None,
        fighter_knockback_velocity_y_override: float | None = None,
        fighter_position_state_reset: bool = False,
        opponent_x_override: float | None = None,
        opponent_x_from_item_offset: float | None = None,
        opponent_y_override: float | None = None,
        opponent_facing_override: float | None = None,
        opponent_position_state_reset: bool = False,
        source_random_seed_override: int | None = None,
    ) -> dict[str, object]:
        return {
            "label": label,
            "main_x": main_x,
            "main_y": main_y,
            "c_x": c_x,
            "c_y": c_y,
            "left_shoulder": left_shoulder,
            "right_shoulder": right_shoulder,
            "digital_left": digital_left,
            "digital_right": digital_right,
            "jump": jump,
            "attack": attack,
            "special": special,
            "grab": grab,
            "taunt": taunt,
            "opponent_main_x": opponent_main_x,
            "opponent_main_y": opponent_main_y,
            "opponent_attack": opponent_attack,
            "opponent_grab": opponent_grab,
            "opponent_jump": opponent_jump,
            "fighter_x_override": fighter_x_override,
            "fighter_x_from_item_offset": fighter_x_from_item_offset,
            "fighter_y_override": fighter_y_override,
            "fighter_facing_override": fighter_facing_override,
            "fighter_damage_override": fighter_damage_override,
            "fighter_self_velocity_x_override": fighter_self_velocity_x_override,
            "fighter_self_velocity_y_override": fighter_self_velocity_y_override,
            "fighter_knockback_velocity_x_override": (
                fighter_knockback_velocity_x_override
            ),
            "fighter_knockback_velocity_y_override": (
                fighter_knockback_velocity_y_override
            ),
            "fighter_position_state_reset": fighter_position_state_reset,
            "opponent_x_override": opponent_x_override,
            "opponent_x_from_item_offset": opponent_x_from_item_offset,
            "opponent_y_override": opponent_y_override,
            "opponent_facing_override": opponent_facing_override,
            "opponent_position_state_reset": opponent_position_state_reset,
            "source_random_seed_override": source_random_seed_override,
        }

    raw_repeat_count_overrides = (
        checkpoint_capture_plan.get("trace_repeat_counts_by_label", {})
        if checkpoint_capture_plan is not None
        else {}
    )
    if not isinstance(raw_repeat_count_overrides, dict) or any(
        not isinstance(label, str)
        or not label
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
        for label, count in raw_repeat_count_overrides.items()
    ):
        raise ValueError("checkpoint trace repeat counts are invalid")
    repeat_count_overrides = {
        str(label): int(count)
        for label, count in raw_repeat_count_overrides.items()
    }

    def repeat(label: str, count: int, **inputs: object) -> None:
        effective_count = repeat_count_overrides.get(label, count)
        trace.extend(command(label, **inputs) for _ in range(effective_count))

    def repeat_unrecorded(label: str, count: int, **inputs: object) -> None:
        trace.extend(
            {**command(label, **inputs), "record": False}
            for _ in range(count)
        )

    def controller_axis(source_axis: object) -> float:
        if (
            not isinstance(source_axis, int)
            or isinstance(source_axis, bool)
            or not -32767 <= source_axis <= 32767
        ):
            raise ValueError("checkpoint stick axis is invalid")
        return (float(source_axis) / 32767.0 + 1.0) * 0.5

    aerial_attack_inputs: dict[str, dict[str, object]] = {
        "nair": {"attack": True},
        "fair": {"c_x": 1.0},
        "bair": {"c_x": 0.0},
        "uair": {"c_y": 1.0},
        "dair": {"c_y": 0.0},
    }

    def reset_reference_airborne_route(prefix: str) -> None:
        trace.append(
            command(
                f"{prefix}_reset",
                fighter_x_override=-38.8,
                fighter_y_override=28.0,
                fighter_self_velocity_x_override=0.0,
                fighter_self_velocity_y_override=0.0,
                fighter_knockback_velocity_x_override=0.0,
                fighter_knockback_velocity_y_override=0.0,
                fighter_position_state_reset=True,
            )
        )
        repeat(f"{prefix}_settle", 60)

    if special_acquisition_only:
        if not checkpoint_isolated or checkpoint_capture_plan is None:
            raise ValueError(
                "special acquisition requires a checkpoint capture plan"
            )
        raw_cases = checkpoint_capture_plan.get("special_acquisition_cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("special acquisition checkpoint cases are required")
        case_ids: set[str] = set()
        for raw_case in raw_cases:
            if not isinstance(raw_case, dict):
                raise ValueError("special acquisition case must be an object")
            case_id = raw_case.get("id")
            source_state = raw_case.get("source_state")
            edge_main = raw_case.get("edge_main")
            edge_c = raw_case.get("edge_c", [0, 0])
            raw_pre_source_phases = raw_case.get("pre_source_phases", [])
            raw_pre_edge_phases = raw_case.get("pre_edge_phases", [])
            raw_edge_actions = raw_case.get("edge_actions")
            edge_left_trigger = raw_case.get("edge_left_trigger", 0)
            edge_right_trigger = raw_case.get("edge_right_trigger", 0)
            edge_digital_left = raw_case.get("edge_digital_left", False)
            edge_digital_right = raw_case.get("edge_digital_right", False)
            edge_actions = (
                [raw_case.get("edge_action", "special")]
                if raw_edge_actions is None
                else raw_edge_actions
            )
            observe_ticks = raw_case.get("observe_ticks", 5)
            checkpoint_slot = raw_case.get("checkpoint_slot", 0)
            if (
                not isinstance(case_id, str)
                or not case_id
                or case_id in case_ids
                or source_state not in {
                    "squat_wait",
                    "squat_rv",
                    "powershield_release",
                    "dash",
                    "teeter",
                    "turn",
                    "walk",
                    "wait",
                    "platform_guard",
                    "platform_wait",
                }
                or not isinstance(edge_main, list)
                or len(edge_main) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or not -32767 <= value <= 32767
                    for value in edge_main
                )
                or not isinstance(edge_c, list)
                or len(edge_c) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or not -32767 <= value <= 32767
                    for value in edge_c
                )
                or not isinstance(raw_pre_edge_phases, list)
                or not isinstance(raw_pre_source_phases, list)
                or (raw_pre_source_phases and source_state != "turn")
                or not isinstance(edge_actions, list)
                or not edge_actions
                or any(
                    not isinstance(edge_action, str)
                    or edge_action not in {
                        "attack",
                        "grab",
                        "jump",
                        "none",
                        "special",
                        "spot_dodge",
                        "taunt",
                    }
                    for edge_action in edge_actions
                )
                or len(set(edge_actions)) != len(edge_actions)
                or ("none" in edge_actions and len(edge_actions) != 1)
                or not isinstance(edge_left_trigger, int)
                or isinstance(edge_left_trigger, bool)
                or not 0 <= edge_left_trigger <= 65535
                or not isinstance(edge_right_trigger, int)
                or isinstance(edge_right_trigger, bool)
                or not 0 <= edge_right_trigger <= 65535
                or not isinstance(edge_digital_left, bool)
                or not isinstance(edge_digital_right, bool)
                or not isinstance(observe_ticks, int)
                or isinstance(observe_ticks, bool)
                or not 1 <= observe_ticks <= 16
                or not isinstance(checkpoint_slot, int)
                or isinstance(checkpoint_slot, bool)
                or not 0 <= checkpoint_slot < CHECKPOINT_SLOT_COUNT
            ):
                raise ValueError(
                    f"invalid special acquisition case {case_id!r}"
                )
            def parse_input_phases(
                raw_phases: list[object], phase_kind: str
            ) -> list[tuple[int, dict[str, object]]]:
                phases: list[tuple[int, dict[str, object]]] = []
                for phase_index, raw_phase in enumerate(raw_phases):
                    if not isinstance(raw_phase, dict):
                        raise ValueError(
                            f"invalid special acquisition {phase_kind} phase "
                            f"case={case_id!r} phase={phase_index}"
                        )
                    phase_ticks = raw_phase.get("ticks")
                    phase_main = raw_phase.get("main", [0, 0])
                    phase_c = raw_phase.get("c_stick", [0, 0])
                    phase_actions = raw_phase.get("actions", [])
                    phase_left_trigger = raw_phase.get("left_trigger", 0)
                    phase_right_trigger = raw_phase.get("right_trigger", 0)
                    phase_digital_left = raw_phase.get("digital_left", False)
                    phase_digital_right = raw_phase.get("digital_right", False)
                    if (
                        set(raw_phase)
                        - {
                            "ticks",
                            "main",
                            "c_stick",
                            "actions",
                            "left_trigger",
                            "right_trigger",
                            "digital_left",
                            "digital_right",
                        }
                        or not isinstance(phase_ticks, int)
                        or isinstance(phase_ticks, bool)
                        or not 1 <= phase_ticks <= 254
                        or not isinstance(phase_main, list)
                        or len(phase_main) != 2
                        or any(
                            not isinstance(value, int)
                            or isinstance(value, bool)
                            or not -32767 <= value <= 32767
                            for value in phase_main
                        )
                        or not isinstance(phase_c, list)
                        or len(phase_c) != 2
                        or any(
                            not isinstance(value, int)
                            or isinstance(value, bool)
                            or not -32767 <= value <= 32767
                            for value in phase_c
                        )
                        or not isinstance(phase_actions, list)
                        or any(
                            not isinstance(action, str)
                            or action
                            not in {
                                "attack",
                                "grab",
                                "jump",
                                "special",
                                "taunt",
                            }
                            for action in phase_actions
                        )
                        or len(set(phase_actions)) != len(phase_actions)
                        or not isinstance(phase_left_trigger, int)
                        or isinstance(phase_left_trigger, bool)
                        or not 0 <= phase_left_trigger <= 65535
                        or not isinstance(phase_right_trigger, int)
                        or isinstance(phase_right_trigger, bool)
                        or not 0 <= phase_right_trigger <= 65535
                        or not isinstance(phase_digital_left, bool)
                        or not isinstance(phase_digital_right, bool)
                    ):
                        raise ValueError(
                            f"invalid special acquisition {phase_kind} phase "
                            f"case={case_id!r} phase={phase_index}"
                        )
                    phases.append(
                        (
                            phase_ticks,
                            {
                                "main_x": controller_axis(phase_main[0]),
                                "main_y": controller_axis(-phase_main[1]),
                                "c_x": controller_axis(phase_c[0]),
                                "c_y": controller_axis(-phase_c[1]),
                                "left_shoulder": phase_left_trigger / 65535.0,
                                "right_shoulder": phase_right_trigger / 65535.0,
                                "digital_left": phase_digital_left,
                                "digital_right": phase_digital_right,
                                "attack": "attack" in phase_actions,
                                "grab": "grab" in phase_actions,
                                "jump": "jump" in phase_actions,
                                "special": "special" in phase_actions,
                                "taunt": "taunt" in phase_actions,
                            },
                        )
                    )
                return phases

            pre_source_phases = parse_input_phases(
                raw_pre_source_phases, "pre-source"
            )
            pre_edge_phases = parse_input_phases(
                raw_pre_edge_phases, "pre-edge"
            )
            if source_state == "platform_guard" and (
                not pre_edge_phases
                or not any(
                    bool(inputs["digital_left"])
                    or bool(inputs["digital_right"])
                    or float(inputs["left_shoulder"]) > 0.0
                    or float(inputs["right_shoulder"]) > 0.0
                    for _, inputs in pre_edge_phases
                )
            ):
                raise ValueError(
                    f"platform guard case {case_id!r} requires a "
                    "trigger-valued pre-edge phase"
                )
            prefix = f"special_acquisition_{case_id}"
            first = command(
                f"{prefix}_setup",
                main_x=(
                    controller_axis(-16384)
                    if source_state == "turn"
                    else (
                        1.0
                        if source_state == "dash"
                        else (
                            0.65
                            if source_state == "teeter"
                            else (
                                controller_axis(12000)
                                if source_state == "walk"
                                else 0.5
                            )
                        )
                    )
                ),
                main_y=(
                    0.5
                    if source_state in {
                        "powershield_release",
                        "dash",
                        "teeter",
                        "turn",
                        "walk",
                        "wait",
                        "platform_guard",
                    }
                    else 0.0
                ),
                fighter_x_override=(
                    -38.8 if source_state == "platform_guard" else (
                        0.0 if source_state == "platform_wait" else (
                        85.0 if source_state == "teeter" else None
                        )
                    )
                ),
                fighter_y_override=(
                    27.2001 if source_state == "platform_guard" else (
                        54.4001 if source_state == "platform_wait" else (
                        0.0001 if source_state == "teeter" else None
                        )
                    )
                ),
                fighter_facing_override=(
                    1.0
                    if source_state in {
                        "teeter",
                        "platform_guard",
                        "platform_wait",
                    }
                    else None
                ),
                fighter_position_state_reset=source_state in {
                    "teeter",
                    "platform_guard",
                    "platform_wait",
                },
            )
            if pre_source_phases:
                phase_ticks, phase_inputs = (
                    pre_source_phases[0]
                )
                trace.append(
                    {
                        **command(f"{prefix}_setup", **phase_inputs),
                        "restore_before": True,
                        "checkpoint_slot": checkpoint_slot,
                        "record": True,
                    }
                )
                repeat(
                    f"{prefix}_setup",
                    phase_ticks - 1,
                    **phase_inputs,
                )
                for phase_ticks, phase_inputs in (
                    pre_source_phases[1:]
                ):
                    repeat(
                        f"{prefix}_setup",
                        phase_ticks,
                        **phase_inputs,
                    )
                trace.append(first)
            else:
                trace.append(
                    {
                        **first,
                        "restore_before": True,
                        "checkpoint_slot": checkpoint_slot,
                        "record": source_state not in {
                            "powershield_release",
                            "teeter",
                            "walk",
                            "wait",
                            "platform_guard",
                            "platform_wait",
                        },
                    }
                )
            if source_state in {"squat_wait", "squat_rv"}:
                repeat(f"{prefix}_setup", 19, main_y=0.0)
                if source_state == "squat_rv":
                    trace.append(command(f"{prefix}_release"))
            elif source_state == "platform_guard":
                # The restored Battlefield checkpoint begins on the left soft
                # platform. Reuse the established neutral jump/landing route
                # to settle on source line 2. Acquisition stays outside the
                # retained theorem; the trigger-valued phases below begin the
                # recorded guard rows.
                repeat_unrecorded(f"{prefix}_setup", 59)
                trace.append(
                    {
                        **command(f"{prefix}_platform_jump", jump=True),
                        "record": False,
                    }
                )
                repeat_unrecorded(f"{prefix}_platform_jump_squat", 5)
                repeat_unrecorded(f"{prefix}_platform_landing_setup", 100)
                repeat_unrecorded(f"{prefix}_platform_landing_settle", 30)
            elif source_state == "platform_wait":
                # A position-reset Battlefield setup used by generic natural
                # edge/fall acquisition. Let collision bind the fighter to
                # the centre platform before any retained input history.
                repeat_unrecorded(f"{prefix}_platform_settle", 30)
            elif source_state == "teeter":
                for _ in range(2):
                    trace.append(
                        {
                            **command(f"{prefix}_setup", main_x=0.65),
                            "record": False,
                        }
                    )
                trace.append(
                    {**command(f"{prefix}_setup"), "record": False}
                )
                trace.append(command(f"{prefix}_setup"))
            elif source_state == "walk":
                trace.append(
                    command(
                        f"{prefix}_setup",
                        main_x=controller_axis(12000),
                    )
                )
            elif source_state == "powershield_release":
                # Reach GuardOff's powershield-only IASA branch through an
                # actual Falcon Jab 1 collision. Placement and the complete
                # causal setup stay outside the retained theorem, but no
                # action or guard work variable is written directly.
                trace[-1].update(
                    fighter_x_override=0.0,
                    fighter_y_override=0.0001,
                    fighter_facing_override=1.0,
                    fighter_position_state_reset=True,
                    opponent_x_override=22.0,
                    opponent_y_override=0.0001,
                    opponent_facing_override=-1.0,
                    opponent_position_state_reset=True,
                )
                for _ in range(10):
                    trace.append(
                        {**command(f"{prefix}_setup"), "record": False}
                    )
                shield_start_ticks = raw_case.get("shield_start_ticks", 0)
                if (
                    not isinstance(shield_start_ticks, int)
                    or isinstance(shield_start_ticks, bool)
                    or not 0 <= shield_start_ticks <= 32
                ):
                    raise ValueError(
                        "invalid powershield shield-start ticks "
                        f"{shield_start_ticks!r}"
                    )
                for _ in range(shield_start_ticks):
                    trace.append(
                        {
                            **command(
                                f"{prefix}_setup",
                                left_shoulder=1.0,
                                digital_left=True,
                            ),
                            "record": False,
                        }
                    )
                trace.append(
                    {
                        **command(
                            f"{prefix}_setup",
                            left_shoulder=1.0,
                            digital_left=True,
                            opponent_attack=True,
                        ),
                        "record": False,
                    }
                )
                if shield_start_ticks == 0:
                    shield_edge = {
                        "id": f"{case_id}_jab_shield",
                        "owner": "opponent",
                        "action": "NEUTRAL_ATTACK_1",
                        "frame": 1,
                        "inputs": {
                            "left_shoulder": 1.0,
                            "digital_left": True,
                        },
                    }
                    for _ in range(4):
                        trace.append(
                            {
                                **command(f"{prefix}_setup"),
                                "conditional_edge": shield_edge,
                                "record": False,
                            }
                        )
                else:
                    trace.append(
                        {
                            **command(
                                f"{prefix}_setup",
                                left_shoulder=1.0,
                                digital_left=True,
                            ),
                            "record": False,
                        }
                    )
                release_ticks = raw_case.get("release_ticks", 8)
                if (
                    not isinstance(release_ticks, int)
                    or isinstance(release_ticks, bool)
                    or not 1 <= release_ticks <= 32
                ):
                    raise ValueError(
                        f"invalid powershield release ticks {release_ticks!r}"
                    )
                for _ in range(release_ticks):
                    trace.append(
                        {**command(f"{prefix}_setup"), "record": False}
                    )
                trace.append(command(f"{prefix}_setup"))
            for phase_ticks, phase_inputs in pre_edge_phases:
                repeat(
                    f"{prefix}_setup",
                    phase_ticks,
                    **phase_inputs,
                )
            edge_x = controller_axis(edge_main[0])
            edge_y = controller_axis(-edge_main[1])
            edge_c_x = controller_axis(edge_c[0])
            edge_c_y = controller_axis(-edge_c[1])
            trace.append(
                command(
                    f"{prefix}_edge",
                    main_x=edge_x,
                    main_y=edge_y,
                    c_x=edge_c_x,
                    c_y=edge_c_y,
                    left_shoulder=edge_left_trigger / 65535.0,
                    right_shoulder=edge_right_trigger / 65535.0,
                    digital_left=edge_digital_left,
                    digital_right=edge_digital_right,
                    attack="attack" in edge_actions,
                    grab="grab" in edge_actions,
                    jump="jump" in edge_actions,
                    special="special" in edge_actions,
                    taunt="taunt" in edge_actions,
                )
            )
            repeat(f"{prefix}_observe", observe_ticks)
            case_ids.add(case_id)
        return trace

    if push_only:
        if checkpoint_isolated:
            if checkpoint_capture_plan is None:
                raise ValueError("checkpoint capture plan is required")
            raw_cases = checkpoint_capture_plan.get("player_push_cases")
            if not isinstance(raw_cases, list) or not raw_cases:
                raise ValueError("player push checkpoint cases are required")
            case_ids: set[str] = set()
            for raw_case in raw_cases:
                if not isinstance(raw_case, dict):
                    raise ValueError("player push case must be an object")
                case_id = raw_case.get("id")
                positions = raw_case.get("start_x")
                facings = raw_case.get("facing")
                mains = raw_case.get("main")
                settle_ticks = raw_case.get("settle_ticks", 4)
                observe_ticks = raw_case.get("observe_ticks")
                recovery_ticks = raw_case.get("recovery_ticks")
                if (
                    not isinstance(case_id, str)
                    or not case_id
                    or case_id in case_ids
                    or not isinstance(positions, list)
                    or len(positions) != 2
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        for value in positions
                    )
                    or not isinstance(facings, list)
                    or len(facings) != 2
                    or any(value not in (-1, 1) for value in facings)
                    or not isinstance(mains, list)
                    or len(mains) != 2
                    or any(
                        not isinstance(stick, list) or len(stick) != 2
                        for stick in mains
                    )
                    or not isinstance(settle_ticks, int)
                    or isinstance(settle_ticks, bool)
                    or not 1 <= settle_ticks <= 30
                    or not isinstance(observe_ticks, int)
                    or isinstance(observe_ticks, bool)
                    or not 1 <= observe_ticks <= 64
                    or not isinstance(recovery_ticks, int)
                    or isinstance(recovery_ticks, bool)
                    or not 0 <= recovery_ticks < observe_ticks
                ):
                    raise ValueError(f"invalid player push case {case_id!r}")
                fighter_main = tuple(controller_axis(value) for value in mains[0])
                opponent_main = tuple(controller_axis(value) for value in mains[1])
                prefix = f"player_push_{case_id}"
                place = command(
                    f"{prefix}_place",
                    fighter_x_override=float(positions[0]),
                    fighter_facing_override=float(facings[0]),
                    opponent_x_override=float(positions[1]),
                    opponent_facing_override=float(facings[1]),
                )
                trace.append({**place, "restore_before": True, "record": False})
                for _ in range(settle_ticks):
                    settle = command(
                        f"{prefix}_settle",
                        fighter_x_override=float(positions[0]),
                        fighter_facing_override=float(facings[0]),
                        opponent_x_override=float(positions[1]),
                        opponent_facing_override=float(facings[1]),
                    )
                    trace.append({**settle, "record": False})
                for _ in range(observe_ticks - recovery_ticks):
                    trace.append(
                        command(
                            f"{prefix}_observe",
                            main_x=fighter_main[0],
                            main_y=fighter_main[1],
                            opponent_main_x=opponent_main[0],
                            opponent_main_y=opponent_main[1],
                        )
                    )
                repeat(f"{prefix}_recovery", recovery_ticks)
                case_ids.add(case_id)
            return trace
        repeat("push_settle", 60)
        repeat("push_walk_right", 240, main_x=0.7)
        repeat("push_recovery", 60)
        repeat(
            "push_opponent_walk_left",
            120,
            opponent_main_x=0.3,
        )
        repeat("push_opponent_recovery", 60)
        return trace

    if attack_iasa_only:
        # The generated NTSC 1.02 table records Jab 1 IASA on displayed frame
        # 16. Pulse edge-triggered inputs both one frame early and exactly on
        # that boundary; a held stick route independently exposes the first
        # continuous-input transition. These are oracle assertions over the
        # imported value, not a second authored timing source.
        if falcon_frame_data is None:
            raise ValueError("attack IASA capture requires Falcon frame data")
        falcon_jab1_iasa_frame = int(dict(falcon_frame_data["jab1"])["iasa"])

        def jab_interrupt_route(
            label: str,
            interrupt_frame: int,
            **interrupt_inputs: object,
        ) -> None:
            repeat(f"{label}_settle", 30)
            trace.append(command(f"{label}_jab", attack=True))
            repeat(
                f"{label}_before_interrupt",
                interrupt_frame - 2,
            )
            trace.append(
                command(
                    f"{label}_interrupt",
                    **interrupt_inputs,
                )
            )
            repeat(f"{label}_recover", 60)

        for frame_label, interrupt_frame in (
            ("early", falcon_jab1_iasa_frame - 1),
            ("exact", falcon_jab1_iasa_frame),
        ):
            jab_interrupt_route(
                f"attack_iasa_jump_{frame_label}",
                interrupt_frame,
                jump=True,
            )
            jab_interrupt_route(
                f"attack_iasa_guard_{frame_label}",
                interrupt_frame,
                left_shoulder=1.0,
                digital_left=True,
            )

        repeat("attack_iasa_walk_settle", 30)
        trace.append(command("attack_iasa_walk_jab", attack=True))
        repeat("attack_iasa_walk_hold", 30, main_x=1.0)
        repeat("attack_iasa_walk_recover", 60)
        return trace

    if aerial_iasa_only:
        if falcon_frame_data is None:
            raise ValueError("aerial IASA capture requires Falcon frame data")

        def aerial_interrupt_route(
            move: str,
            route: str,
            interrupt_frame: int,
        ) -> None:
            prefix = f"aerial_iasa_{move}_{route}"
            repeat(f"{prefix}_settle", 45)
            trace.append(command(f"{prefix}_jump", jump=True))
            repeat(f"{prefix}_jump_squat", 4, jump=True)
            trace.append(
                command(
                    f"{prefix}_start",
                    **aerial_attack_inputs[move],
                )
            )
            repeat(f"{prefix}_before", interrupt_frame - 2)
            trace.append(command(f"{prefix}_jump_interrupt", jump=True))
            repeat(f"{prefix}_recover", 55)

        for move in ("fair", "bair", "uair", "dair"):
            iasa = int(dict(falcon_frame_data[move])["iasa"])
            aerial_interrupt_route(move, "jump_early", iasa - 1)
            aerial_interrupt_route(move, "jump_exact", iasa)

        # Falcon's neutral aerial has no IASA command. A penultimate-frame
        # jump edge must remain locked and must not buffer into the following
        # ordinary Fall state.
        aerial_interrupt_route(
            "nair",
            "jump_no_iasa",
            int(dict(falcon_frame_data["nair"])["totalFrames"]) - 1,
        )
        return trace

    if aerial_attack_ecb_only:
        if falcon_frame_data is None:
            raise ValueError(
                "aerial-attack ECB capture requires Falcon frame data"
            )

        def capture_aerial_pose_route(move: str) -> None:
            prefix = f"aerial_attack_ecb_{move}"
            reset_reference_airborne_route(prefix)
            trace.append(command(f"{prefix}_jump", jump=True))
            repeat(f"{prefix}_jump_squat", 4, jump=True)
            repeat(f"{prefix}_ascent", 2)
            trace.append(command(f"{prefix}_double_jump", jump=True))
            trace.append(
                command(f"{prefix}_start", **aerial_attack_inputs[move])
            )
            total_frames = int(dict(falcon_frame_data[move])["totalFrames"])
            for _ in range(total_frames + 8):
                trace.append(
                    command(
                        f"{prefix}_observe",
                        fighter_y_override=40.0,
                    )
                )

        for move in aerial_attack_inputs:
            capture_aerial_pose_route(move)
        return trace

    if aerial_attack_landing_only:
        for move, attack_input in aerial_attack_inputs.items():
            prefix = f"aerial_attack_landing_{move}"
            reset_reference_airborne_route(prefix)
            trace.append(command(f"{prefix}_jump", jump=True))
            repeat(f"{prefix}_jump_squat_release", 4)
            trace.append(command(f"{prefix}_start", **attack_input))
            repeat(f"{prefix}_observe", 70)
        return trace

    if hitbox_geometry_only:
        if falcon_frame_data is None:
            raise ValueError("hitbox-geometry capture requires Falcon frame data")

        def move_total(move: str) -> int:
            return int(dict(falcon_frame_data[move])["totalFrames"])

        def isolated_route(
            move: str,
            starter: list[dict[str, object]],
            recovery_padding: int = 40,
        ) -> None:
            # Reset the remote Falcon's idle animation phase without moving
            # either fighter. Its 21-frame Jab 1 completes inside this fixed
            # settle window, making every later hurt-capsule pose independent
            # of nondeterministic menu-entry timing.
            trace.append(
                command(
                    f"hitbox_geometry_{move}_opponent_pose_reset",
                    attack=True,
                    opponent_attack=True,
                    fighter_x_override=-60.0,
                    fighter_y_override=0.0001,
                    fighter_self_velocity_x_override=0.0,
                    fighter_self_velocity_y_override=0.0,
                    fighter_knockback_velocity_x_override=0.0,
                    fighter_knockback_velocity_y_override=0.0,
                    fighter_position_state_reset=True,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"hitbox_geometry_{move}_settle", 29)
            trace.extend(starter)
            repeat(
                f"hitbox_geometry_{move}_observe",
                move_total(move) + recovery_padding,
            )

        isolated_route(
            "jab1",
            [command("hitbox_geometry_jab1_start", attack=True)],
        )
        isolated_route(
            "jab2",
            [
                command("hitbox_geometry_jab2_jab1", attack=True),
                command("hitbox_geometry_jab2_wait"),
                command("hitbox_geometry_jab2_chain", attack=True),
            ],
        )
        isolated_route(
            "jab3",
            [
                command(
                    f"hitbox_geometry_jab3_input_{index}",
                    attack=index in {0, 8, 16},
                )
                for index in range(17)
            ],
        )

        # Four fresh A presses arm Falcon's source rapid-jab counter. Keep
        # alternating press/release through Attack13 and Attack100Loop, then
        # release long enough for the script-owned loop-exit gate to select
        # Attack100End. One natural route therefore captures all three source
        # submotions without action/frame mutation.
        rapid_starter: list[dict[str, object]] = []
        for index in range(40):
            rapid_starter.append(
                command(
                    f"hitbox_geometry_rapidjabs_input_{index}",
                    attack=index % 2 == 0,
                )
            )
        isolated_route(
            "rapidjabs_loop",
            rapid_starter,
            recovery_padding=(
                move_total("rapidjabs_start")
                + move_total("rapidjabs_end")
                + 80
            ),
        )
        isolated_route(
            "dashattack",
            [
                command("hitbox_geometry_dashattack_dash", main_x=1.0),
                command("hitbox_geometry_dashattack_hold", main_x=1.0),
                command("hitbox_geometry_dashattack_hold", main_x=1.0),
                command("hitbox_geometry_dashattack_hold", main_x=1.0),
                command(
                    "hitbox_geometry_dashattack_start",
                    main_x=1.0,
                    attack=True,
                ),
            ],
        )
        def angled_ftilt_starter(
            move: str, main_x: float, main_y: float
        ) -> None:
            # Age the diagonal while Falcon is locked in ordinary Landing,
            # then press A on the first source IASA frame. This reaches the
            # source angle bands naturally without a fresh smash input or an
            # action/frame override.
            isolated_route(
                move,
                [
                    command(
                        f"hitbox_geometry_{move}_jump",
                        jump=True,
                    ),
                    command(f"hitbox_geometry_{move}_jump_squat_1"),
                    command(f"hitbox_geometry_{move}_jump_squat_2"),
                    command(f"hitbox_geometry_{move}_jump_squat_3"),
                    command(f"hitbox_geometry_{move}_jump_squat_4"),
                    command(
                        f"hitbox_geometry_{move}_land",
                        main_x=main_x,
                        main_y=main_y,
                        fighter_y_override=1.0,
                        fighter_self_velocity_x_override=0.0,
                        fighter_self_velocity_y_override=-2.0,
                        fighter_knockback_velocity_x_override=0.0,
                        fighter_knockback_velocity_y_override=0.0,
                    ),
                    command(
                        f"hitbox_geometry_{move}_landing_2",
                        main_x=main_x,
                        main_y=main_y,
                    ),
                    command(
                        f"hitbox_geometry_{move}_landing_3",
                        main_x=main_x,
                        main_y=main_y,
                    ),
                    command(
                        f"hitbox_geometry_{move}_landing_4",
                        main_x=main_x,
                        main_y=main_y,
                    ),
                    command(
                        f"hitbox_geometry_{move}_start",
                        main_x=main_x,
                        main_y=main_y,
                        attack=True,
                    ),
                ],
            )

        angled_ftilt_starter("ftilt_h", 0.90, 0.65)
        angled_ftilt_starter("ftilt_mh", 0.975, 0.645)
        isolated_route(
            "ftilt_m",
            [
                command(
                    "hitbox_geometry_ftilt_m_start",
                    main_x=0.70,
                    attack=True,
                )
            ],
        )
        angled_ftilt_starter("ftilt_ml", 0.975, 0.355)
        angled_ftilt_starter("ftilt_l", 0.90, 0.35)
        isolated_route(
            "utilt",
            [command("hitbox_geometry_utilt_start", main_y=0.65, attack=True)],
        )
        isolated_route(
            "dtilt",
            [command("hitbox_geometry_dtilt_start", main_y=0.35, attack=True)],
        )
        isolated_route(
            "fsmash_h",
            [
                command(
                    "hitbox_geometry_fsmash_h_start",
                    main_x=1.0,
                    main_y=0.85,
                    attack=True,
                )
            ],
        )
        isolated_route(
            "fsmash_m",
            [command("hitbox_geometry_fsmash_m_start", c_x=1.0)],
        )
        isolated_route(
            "fsmash_l",
            [
                command(
                    "hitbox_geometry_fsmash_l_start",
                    main_x=1.0,
                    main_y=0.15,
                    attack=True,
                )
            ],
        )
        isolated_route(
            "usmash",
            [command("hitbox_geometry_usmash_start", c_y=1.0)],
        )
        isolated_route(
            "dsmash",
            [command("hitbox_geometry_dsmash_start", c_y=0.0)],
        )
        isolated_route(
            "grab",
            [command("hitbox_geometry_grab_start", grab=True)],
        )
        isolated_route(
            "dashgrab",
            [
                command("hitbox_geometry_dashgrab_dash", main_x=1.0),
                command("hitbox_geometry_dashgrab_hold", main_x=1.0),
                command("hitbox_geometry_dashgrab_hold", main_x=1.0),
                command("hitbox_geometry_dashgrab_hold", main_x=1.0),
                command(
                    "hitbox_geometry_dashgrab_start",
                    main_x=1.0,
                    grab=True,
                ),
            ],
        )

        # Capture CatchAttack together with the naturally linked victim's
        # CaptureDamage action.  Keep both fighters on the ordinary grab path:
        # the position override only establishes a repeatable collision setup,
        # while the grab, capture wait, and fresh A press are real inputs.
        pummel_starter = [
            command(
                "hitbox_geometry_pummel_preposition",
                fighter_x_override=-2.0,
                fighter_y_override=0.0001,
                fighter_facing_override=1.0,
                fighter_self_velocity_x_override=0.0,
                fighter_self_velocity_y_override=0.0,
                fighter_knockback_velocity_x_override=0.0,
                fighter_knockback_velocity_y_override=0.0,
                fighter_position_state_reset=True,
                opponent_x_override=2.0,
                opponent_y_override=0.0001,
                opponent_facing_override=-1.0,
            )
        ]
        pummel_starter.extend(
            command(f"hitbox_geometry_pummel_settle_{index}")
            for index in range(60)
        )
        pummel_starter.append(
            command("hitbox_geometry_pummel_grab", grab=True)
        )
        pummel_starter.extend(
            command(f"hitbox_geometry_pummel_capture_{index}")
            for index in range(12)
        )
        pummel_starter.append(
            command("hitbox_geometry_pummel_start", attack=True)
        )
        isolated_route("pummel", pummel_starter)

        def aerial_starter(move: str, **attack_input: object) -> None:
            isolated_route(
                move,
                [
                    command(f"hitbox_geometry_{move}_jump", jump=True),
                    command(
                        f"hitbox_geometry_{move}_jump_squat",
                        jump=True,
                    ),
                    command(
                        f"hitbox_geometry_{move}_jump_squat",
                        jump=True,
                    ),
                    command(
                        f"hitbox_geometry_{move}_jump_squat",
                        jump=True,
                    ),
                    command(
                        f"hitbox_geometry_{move}_jump_squat",
                        jump=True,
                    ),
                    command(f"hitbox_geometry_{move}_ascent"),
                    command(f"hitbox_geometry_{move}_ascent"),
                    command(
                        f"hitbox_geometry_{move}_double_jump",
                        jump=True,
                    ),
                    command(
                        f"hitbox_geometry_{move}_start",
                        **attack_input,
                    ),
                ],
                recovery_padding=70,
            )

        aerial_starter("nair", attack=True)
        aerial_starter("fair", c_x=1.0)
        aerial_starter("bair", c_x=0.0)
        aerial_starter("uair", c_y=1.0)
        aerial_starter("dair", c_y=0.0)
        return trace

    if throw_geometry_only:
        if falcon_frame_data is None:
            raise ValueError("throw-geometry capture requires Falcon frame data")

        throw_inputs = {
            "fthrow": {"main_x": 1.0},
            "bthrow": {"main_x": 0.0},
            "dthrow": {"main_y": 0.0},
            "uthrow": {"main_y": 1.0},
        }
        for move, throw_input in throw_inputs.items():
            trace.append(
                command(
                    f"throw_geometry_{move}_preposition",
                    fighter_x_override=-2.0,
                    opponent_x_override=2.0,
                )
            )
            repeat(f"throw_geometry_{move}_settle", 60)
            trace.append(command(f"throw_geometry_{move}_grab", grab=True))
            repeat(f"throw_geometry_{move}_capture", 12)
            trace.append(command(f"throw_geometry_{move}_start", **throw_input))
            repeat(
                f"throw_geometry_{move}_observe",
                int(dict(falcon_frame_data[move])["totalFrames"]) + 45,
            )
            trace.append(
                command(f"throw_geometry_{move}_victim_wakeup", opponent_attack=True)
            )
            repeat(f"throw_geometry_{move}_victim_recover", 60)
        return trace

    if special_geometry_only:
        if falcon_frame_data is None:
            raise ValueError("special-geometry capture requires Falcon frame data")

        special_moves = special_geometry_moves or ("neutral_ground",)
        unsupported = set(special_moves) - set(SPECIAL_GEOMETRY_SOURCE_KEYS)
        if unsupported:
            raise ValueError(
                f"unsupported special-geometry routes: {sorted(unsupported)}"
            )

        def special_total(route: str) -> int:
            return int(
                dict(falcon_frame_data[SPECIAL_GEOMETRY_SOURCE_KEYS[route]])[
                    "totalFrames"
                ]
            )

        for route in special_moves:
            ledge_grab_route = route in {
                "up_air_ledge_grab",
                "up_air_ledge_grab_behind",
            }
            behind_facing_ledge_route = route == "up_air_ledge_grab_behind"
            trace.append(
                command(
                    f"special_geometry_{route}_opponent_pose_reset",
                    opponent_attack=True,
                    opponent_x_from_item_offset=(
                        100.0 if route == "side_ground_item_hit" else None
                    ),
                )
            )
            repeat(
                f"special_geometry_{route}_settle",
                29,
                opponent_x_from_item_offset=(
                    100.0 if route == "side_ground_item_hit" else None
                ),
            )
            airborne = route in {
                "neutral_air",
                "side_air_miss",
                "side_air_hit",
                "side_air_hit_floor",
                "up_air_miss",
                "up_air_miss_natural",
                "up_air_ledge_grab",
                "up_air_ledge_grab_behind",
                "up_air_catch",
                "down_air",
                "down_air_land",
            }
            low_airborne = route == "down_air_land"
            elevated_airborne = airborne and not low_airborne
            position_isolated_airborne = (
                elevated_airborne and route != "up_air_miss_natural"
            )
            native_air_hit = route == "side_air_hit_floor"
            if airborne:
                airborne_opponent = route in {
                    "side_air_hit",
                    "side_air_hit_floor",
                    "up_air_catch",
                }

                if ledge_grab_route:
                    # Start from a safe grounded point, then create the
                    # recovery setup entirely through native movement. This
                    # preserves Melee's collision history and ledge flags.
                    trace.append(
                        command(
                            f"special_geometry_{route}_preposition",
                            fighter_x_override=-45.0,
                        )
                    )
                    repeat(f"special_geometry_{route}_preposition_settle", 3)
                    trace.extend(
                        command(
                            f"special_geometry_{route}_jump",
                            main_x=0.0,
                            jump=True,
                        )
                        for _ in range(5)
                    )
                    repeat(
                        f"special_geometry_{route}_drift_out",
                        25,
                        main_x=0.0,
                    )
                    repeat(
                        f"special_geometry_{route}_descend",
                        32,
                    )
                    airborne_commands = []
                else:

                    def airborne_setup(
                        suffix: str, *, jump: bool = False
                    ) -> dict[str, object]:
                        opponent_elevated = (
                            airborne_opponent and suffix == "opponent_elevate"
                        )
                        native_jump_setup = native_air_hit and suffix == "jump"
                        native_jump_held = suffix in {"jump", "jump_squat"}
                        return command(
                            f"special_geometry_{route}_{suffix}",
                            jump=jump,
                            opponent_jump=(
                                airborne_opponent
                                and (not native_air_hit or native_jump_held)
                            ),
                            fighter_x_override=(-10.0 if native_jump_setup else None),
                            opponent_x_override=(
                                0.0
                                if native_jump_setup
                                or (airborne_opponent and not native_air_hit)
                                else None
                            ),
                            opponent_y_override=(
                                500.0
                                if opponent_elevated and not native_air_hit
                                else None
                            ),
                        )

                    airborne_commands = [
                        airborne_setup("jump", jump=True),
                        airborne_setup("jump_squat", jump=True),
                        airborne_setup("jump_squat", jump=True),
                        airborne_setup("jump_squat", jump=True),
                        airborne_setup("jump_squat", jump=True),
                        airborne_setup("ascent"),
                        airborne_setup("ascent"),
                    ]
                    if not low_airborne:
                        airborne_commands.extend(
                            (
                                airborne_setup("double_jump", jump=True),
                                airborne_setup("airborne_hold"),
                                airborne_setup("airborne_hold"),
                                airborne_setup("opponent_elevate"),
                            )
                        )
                    if native_air_hit:
                        airborne_commands.extend(
                            airborne_setup("descent") for _ in range(6)
                        )
                trace.extend(airborne_commands)
            if route == "neutral_ground":
                trace.append(
                    command(
                        "special_geometry_neutral_ground_start",
                        special=True,
                    )
                )
            elif route == "neutral_air":
                trace.append(
                    command(
                        "special_geometry_neutral_air_start",
                        special=True,
                        fighter_y_override=500.0,
                    )
                )
            elif route in {
                "side_ground_miss",
                "side_ground_edge",
                "side_ground_hit",
                "side_ground_item_hit",
                "side_air_miss",
                "side_air_hit",
                "side_air_hit_floor",
            }:
                collision_route = route.endswith("_hit") or native_air_hit
                trace.append(
                    command(
                        f"special_geometry_{route}_start",
                        main_x=1.0,
                        special=True,
                        fighter_x_override=(
                            78.0
                            if route == "side_ground_edge"
                            else (
                                -10.0
                                if collision_route
                                and not native_air_hit
                                and route != "side_ground_item_hit"
                                else None
                            )
                        ),
                        fighter_x_from_item_offset=(
                            -10.0 if route == "side_ground_item_hit" else None
                        ),
                        fighter_y_override=(
                            500.0 if elevated_airborne and not native_air_hit else None
                        ),
                        opponent_x_override=(
                            0.0
                            if collision_route
                            and not native_air_hit
                            and route != "side_ground_item_hit"
                            else None
                        ),
                        opponent_x_from_item_offset=(
                            100.0 if route == "side_ground_item_hit" else None
                        ),
                        opponent_y_override=(
                            500.0
                            if collision_route and airborne and not native_air_hit
                            else None
                        ),
                        opponent_main_x=(0.0 if route == "side_ground_edge" else 0.5),
                    )
                )
            elif route in {
                "up_ground_miss",
                "up_air_miss",
                "up_air_miss_natural",
                "up_air_ledge_grab",
                "up_air_ledge_grab_behind",
                "up_ground_catch",
                "up_air_catch",
            }:
                collision_route = route.endswith("_catch")
                trace.append(
                    command(
                        f"special_geometry_{route}_start",
                        main_y=1.0,
                        main_x=(0.75 if ledge_grab_route else 0.5),
                        special=True,
                        fighter_x_override=(-5.0 if collision_route else None),
                        fighter_y_override=(
                            500.0
                            if position_isolated_airborne and not ledge_grab_route
                            else None
                        ),
                        opponent_x_override=(0.0 if collision_route else None),
                        opponent_y_override=(
                            500.0 if collision_route and airborne else None
                        ),
                    )
                )
                if ledge_grab_route:
                    repeat(
                        f"special_geometry_{route}_steer_toward",
                        11 if behind_facing_ledge_route else 12,
                        main_x=1.0,
                    )
                    if behind_facing_ledge_route:
                        repeat(
                            f"special_geometry_{route}_face_away",
                            1,
                            main_x=0.0,
                        )
                    repeat(
                        f"special_geometry_{route}_steer_away",
                        52,
                        main_x=(0.775 if behind_facing_ledge_route else 0.24),
                    )
            elif route in {
                "down_ground",
                "down_ground_hit",
                "down_ground_wall",
                "down_ground_edge",
                "down_air",
                "down_air_land",
            }:
                if route == "down_ground_wall":
                    # Use GrSh.dat's local floor-5/left-wall-79 collision group
                    # as the relocation target. Relocate only after a real jump
                    # has cleared the old floor-support line, then let Melee's
                    # joint transforms and collision code choose the supported
                    # surface naturally. The kick itself is unmodified.
                    trace.extend(
                        command(
                            "special_geometry_down_ground_wall_jump",
                            jump=True,
                        )
                        for _ in range(5)
                    )
                    repeat("special_geometry_down_ground_wall_air_wait", 35)
                    repeat(
                        "special_geometry_down_ground_wall_air_relocate",
                        3,
                        fighter_x_override=-187.0,
                        fighter_y_override=20.0,
                    )
                    repeat("special_geometry_down_ground_wall_land", 40)
                trace.append(
                    command(
                        f"special_geometry_{route}_start",
                        main_y=0.0,
                        special=True,
                        fighter_x_override=(
                            80.0
                            if route == "down_ground_edge"
                            else (-20.0 if route == "down_ground_hit" else None)
                        ),
                        opponent_x_override=(
                            0.0 if route == "down_ground_hit" else None
                        ),
                        fighter_y_override=(500.0 if elevated_airborne else None),
                    )
                )
            repeat(
                f"special_geometry_{route}_observe",
                special_total(route) + 100,
                opponent_main_x=(0.0 if route == "side_ground_edge" else 0.5),
                fighter_y_override=(
                    500.0
                    if position_isolated_airborne
                    and route
                    not in {
                        "neutral_air",
                        "side_air_hit_floor",
                        "up_air_ledge_grab",
                        "up_air_ledge_grab_behind",
                    }
                    else None
                ),
                opponent_x_override=(
                    0.0
                    if route
                    in {
                        "side_ground_hit",
                        "side_air_hit",
                        "up_ground_catch",
                        "up_air_catch",
                        "down_ground_hit",
                    }
                    else None
                ),
                opponent_y_override=(
                    500.0 if route in {"side_air_hit", "up_air_catch"} else None
                ),
            )
        return trace

    if ground_attack_iasa_only:
        if falcon_frame_data is None:
            raise ValueError("ground-attack IASA capture requires Falcon frame data")

        starters: dict[str, list[dict[str, object]]] = {
            "dashattack": [
                command("dashattack_dash", main_x=1.0),
                command("dashattack_hold", main_x=1.0),
                command("dashattack_hold", main_x=1.0),
                command("dashattack_hold", main_x=1.0),
                # Keep the already-aged dash direction held while A arrives.
                # Releasing it drops the controller below the dash-attack
                # branch; re-flicking it with A requests forward smash.
                command("dashattack_start", main_x=1.0, attack=True),
            ],
            "ftilt_m": [command("ftilt_m_start", main_x=0.70, attack=True)],
            "utilt": [command("utilt_start", main_y=0.65, attack=True)],
            "dtilt": [command("dtilt_start", main_y=0.35, attack=True)],
            "fsmash_m": [command("fsmash_m_start", c_x=1.0)],
            "usmash": [command("usmash_start", c_y=1.0)],
            "dsmash": [command("dsmash_start", c_y=0.0)],
        }

        def move_value(move: str, field: str) -> int:
            return int(dict(falcon_frame_data[move])[field])

        route_index = 0
        capture_facing = 1

        def interrupt_route(
            move: str,
            route: str,
            interrupt_frame: int,
            **interrupt_inputs: object,
        ) -> None:
            nonlocal capture_facing, route_index
            prefix = f"ground_iasa_{move}_{route}"
            if route == "special" and capture_facing < 0:
                # Falcon Punch carries substantial facing-relative root
                # motion. Face back toward stage center before testing a
                # special IASA branch so the isolated character-specific body
                # cannot walk later routes into an edge clamp.
                trace.append(command(f"{prefix}_face_center", main_x=1.0))
                capture_facing = 1
            # Mirror every other route.  Long matrix captures otherwise push
            # Falcon onto Final Destination's x=85.5657 edge, where Melee
            # retains the authored root velocity but collision correctly
            # clamps world position.  Alternation keeps this timing oracle
            # away from stage geometry without resetting game state.
            mirrored = bool(route_index & 1)
            if move == "ftilt_m":
                # Melee's forward-tilt input is facing-relative; an opposite
                # horizontal A press falls through to Jab 1 instead of
                # turning the fighter. Preserve the facing left by the last
                # horizontal route.
                mirrored = capture_facing < 0
            elif move == "fsmash_m" and route == "special":
                mirrored = False
            route_index += 1
            recovery_frames = move_value(move, "totalFrames") + 45
            if route == "special":
                recovery_frames = max(
                    recovery_frames,
                    move_value("0x12d", "totalFrames") + 45,
                )
            repeat(f"{prefix}_settle", 40)
            for starter in starters[move]:
                mirrored_starter = dict(starter)
                if mirrored:
                    # libmelee's normalized controller axes use 0.5 as
                    # neutral, so reflection is 1-x rather than negation.
                    mirrored_starter["main_x"] = 1.0 - float(mirrored_starter["main_x"])
                    mirrored_starter["c_x"] = 1.0 - float(mirrored_starter["c_x"])
                trace.append(mirrored_starter)
            if move in {"dashattack", "fsmash_m"}:
                capture_facing = -1 if mirrored else 1
            repeat(f"{prefix}_before", interrupt_frame - 2)
            trace.append(command(f"{prefix}_interrupt", **interrupt_inputs))
            repeat(
                f"{prefix}_recover",
                recovery_frames,
            )

        # Match setup already places the target on the opposite side. Keep it
        # there: running farther right walks it off Final Destination and its
        # later respawn beside Falcon would inject hitlag into timing routes.
        repeat("ground_iasa_opponent_settle", 60)

        selected_moves = set(ground_attack_moves or starters)
        routed_moves = tuple(
            move
            for move in (
                "dashattack",
                "utilt",
                "dtilt",
                "fsmash_m",
                "usmash",
                "dsmash",
            )
            if move in selected_moves
        )
        for move in routed_moves:
            iasa = move_value(move, "iasa")
            interrupt_route(move, "jump_early", iasa - 1, jump=True)
            interrupt_route(move, "jump_exact", iasa, jump=True)

        # Forward tilt has no IASA command. A late jump must remain locked
        # through its penultimate displayed animation frame.
        if "ftilt_m" in selected_moves:
            interrupt_route(
                "ftilt_m",
                "jump_no_iasa",
                move_value("ftilt_m", "totalFrames") - 1,
                jump=True,
            )

        wait_inputs = {
            "guard": {"left_shoulder": 1.0, "digital_left": True},
            "special": {"special": True},
            "grab": {"grab": True},
            "taunt": {"taunt": True},
            "spot": {
                "main_y": 0.0,
                "left_shoulder": 1.0,
                "digital_left": True,
            },
        }
        if "utilt" in selected_moves:
            for route, inputs in wait_inputs.items():
                interrupt_route(
                    "utilt",
                    route,
                    move_value("utilt", "iasa"),
                    **inputs,
                )

        restricted_inputs = {
            **wait_inputs,
            "up_attack": {"main_y": 0.65, "attack": True},
        }
        for move in ("dtilt", "fsmash_m"):
            if move not in selected_moves:
                continue
            for route, inputs in restricted_inputs.items():
                interrupt_route(
                    move,
                    route,
                    move_value(move, "iasa"),
                    **inputs,
                )
        return trace

    if shield_break_orientation_only:
        repeat("shield_break_orientation_settle", 60)
        repeat(
            "shield_break_orientation_drain",
            260,
            left_shoulder=1.0,
            digital_left=True,
        )
        repeat("shield_break_orientation_observe", 180)
        return trace

    if shield_only:
        repeat("shield_formula_settle", 60)
        repeat(
            "shield_formula_below_dead_zone",
            8,
            left_shoulder=0.29,
        )
        repeat("shield_formula_below_release", 8)
        repeat(
            "shield_formula_threshold_sample",
            12,
            left_shoulder=0.30,
        )
        repeat("shield_formula_threshold_release", 12)
        repeat(
            "shield_formula_light",
            30,
            left_shoulder=0.35,
        )
        repeat("shield_formula_light_release", 20)
        repeat(
            "shield_formula_low_mid",
            30,
            left_shoulder=0.40,
        )
        repeat("shield_formula_low_mid_release", 20)
        repeat(
            "shield_formula_high_mid",
            30,
            left_shoulder=0.65,
        )
        repeat("shield_formula_high_mid_release", 20)
        repeat(
            "shield_formula_near_dense",
            30,
            right_shoulder=0.99,
        )
        repeat("shield_formula_near_dense_release", 20)
        repeat(
            "shield_formula_both_shoulders",
            30,
            left_shoulder=0.40,
            right_shoulder=0.70,
        )
        repeat("shield_formula_both_release", 20)
        repeat(
            "shield_formula_digital_full",
            30,
            left_shoulder=1.0,
            digital_left=True,
        )
        repeat("shield_formula_regeneration", 120)
        return trace

    if shield_geometry_only:
        repeat("shield_geometry_settle", 60)
        repeat(
            "shield_geometry_neutral",
            20,
            left_shoulder=0.35,
        )
        for label, main_x, main_y in (
            ("right", 0.68, 0.5),
            ("up_right", 0.625, 0.625),
            ("up", 0.5, 0.68),
            ("up_left", 0.375, 0.625),
            ("left", 0.32, 0.5),
            ("down_left", 0.375, 0.375),
            ("down", 0.5, 0.32),
            ("down_right", 0.625, 0.375),
        ):
            repeat(
                f"shield_geometry_{label}",
                12,
                main_x=main_x,
                main_y=main_y,
                left_shoulder=0.35,
            )
            repeat(
                f"shield_geometry_{label}_recenter",
                8,
                left_shoulder=0.35,
            )
        repeat("shield_geometry_release", 30)
        return trace

    if shield_geometry_sweep_only:
        repeat("shield_geometry_sweep_settle", 60)
        repeat(
            "shield_geometry_sweep_neutral",
            20,
            left_shoulder=0.35,
        )
        for angle_index in range(256):
            angle = 2.0 * math.pi * angle_index / 256.0
            signed_x = 0.55 * math.cos(angle)
            signed_y = 0.55 * math.sin(angle)
            repeat(
                f"shield_geometry_sweep_{angle_index:03d}",
                8,
                main_x=0.5 + signed_x / 3.125,
                main_y=0.5 + signed_y / 3.125,
                left_shoulder=0.35,
            )
        repeat("shield_geometry_sweep_release", 30)
        return trace

    if shield_guardon_landing_only:
        # Reproduce the action-owner chain used by complete-match shield
        # collisions: a late back-air reaches LandingAirB, its terminal Anim
        # callback installs Wait, and held L lets Wait IASA enter GuardOn on
        # that same update. Keep the shield held through landing so this route
        # does not depend on a guessed terminal-frame button edge.
        prefix = "shield_guardon_landing"
        reset_reference_airborne_route(prefix)
        trace.append(command(f"{prefix}_jump", jump=True))
        repeat(f"{prefix}_jump_squat_release", 17)
        trace.append(command(f"{prefix}_bair", c_x=0.0))
        repeat(
            f"{prefix}_hold",
            70,
            main_x=0.0,
            left_shoulder=1.0,
            digital_left=True,
        )
        repeat(f"{prefix}_release", 20)
        return trace

    if shield_hit_only:
        repeat("shield_hit_settle", 60)
        trace.append(
            command(
                "shield_hit_place",
                fighter_x_override=0.0,
                fighter_y_override=0.0001,
                opponent_x_override=22.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("shield_hit_neutral_settle", 10)
        repeat(
            "shield_hit_hold",
            12,
            left_shoulder=shield_hit_pressure,
        )
        trace.append(
            command(
                "shield_hit_jab",
                left_shoulder=shield_hit_pressure,
                opponent_attack=True,
            )
        )
        repeat(
            "shield_hit_recovery",
            45,
            left_shoulder=shield_hit_pressure,
        )
        repeat("shield_hit_release", 30)
        return trace

    if shield_collision_only:
        # Sweep Jab 1 in 0.05-unit steps across the transformed shield sphere
        # at neutral and two diagonal offsets. Explicit relocation makes every
        # trial independent of locomotion, while the unshielded recovery
        # interval restores the small amount of health spent by the preceding
        # trial.
        repeat("shield_collision_settle", 60)
        for direction, main_x, main_y, first_hundredth in (
            ("neutral", 0.5, 0.5, 2840),
            ("up_right", 0.625, 0.625, 2940),
            ("down_right", 0.625, 0.375, 2940),
        ):
            for hundredth in range(first_hundredth, first_hundredth + 51, 5):
                distance = hundredth / 100.0
                trial = f"shield_collision_{direction}_{distance:.2f}"
                trace.append(
                    command(
                        f"{trial}_place",
                        fighter_x_override=0.0,
                        fighter_y_override=0.0001,
                        opponent_x_override=distance,
                        opponent_y_override=0.0001,
                    )
                )
                repeat(
                    f"{trial}_settle",
                    10,
                )
                repeat(
                    f"{trial}_hold",
                    12,
                    main_x=main_x,
                    main_y=main_y,
                    left_shoulder=0.35,
                )
                trace.append(
                    command(
                        f"{trial}_jab",
                        main_x=main_x,
                        main_y=main_y,
                        left_shoulder=0.35,
                        opponent_attack=True,
                    )
                )
                repeat(
                    f"{trial}_observe",
                    12,
                    main_x=main_x,
                    main_y=main_y,
                    left_shoulder=0.35,
                )
                repeat(
                    f"{trial}_recover",
                    40,
                )
        return trace

    if moving_hit_sweep_only:
        # Falcon down tilt frame 12 versus standing grab frame 12 is a
        # source-derived discriminator: at 27.40 units, the live x4c sphere
        # misses while the continuing x58->x4c capsule hits. Both action hurt
        # poses are imported, avoiding the incomplete common-idle pose route;
        # the grab volume has already ended and cannot create a reciprocal hit.
        repeat("moving_hit_sweep_settle", 60)
        trace.append(
            command(
                "moving_hit_sweep_place",
                fighter_x_override=0.0,
                fighter_y_override=0.0001,
                opponent_x_override=27.4,
                opponent_y_override=0.0001,
            )
        )
        repeat("moving_hit_sweep_place_settle", 10)
        trace.append(
            command(
                "moving_hit_sweep_down_tilt_vs_grab",
                main_y=0.35,
                attack=True,
                opponent_grab=True,
            )
        )
        repeat("moving_hit_sweep_observe", 35)
        repeat("moving_hit_sweep_recover", 60)
        trace.append(
            command(
                "moving_hit_sweep_miss_place",
                fighter_x_override=0.0,
                fighter_y_override=0.0001,
                opponent_x_override=28.3,
                opponent_y_override=0.0001,
            )
        )
        repeat("moving_hit_sweep_miss_place_settle", 10)
        trace.append(
            command(
                "moving_hit_sweep_miss_down_tilt_vs_grab",
                main_y=0.35,
                attack=True,
                opponent_grab=True,
            )
        )
        repeat("moving_hit_sweep_miss_observe", 35)
        repeat("moving_hit_sweep_miss_recover", 60)
        return trace

    if common_hurt_geometry_only:
        def checkpoint_isolated_common_hurt_trace(
            source: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            """Replace cross-case settling with checkpoint isolation."""

            result: list[dict[str, object]] = []
            pending_restore = False
            if checkpoint_capture_plan is None:
                raise ValueError("checkpoint capture plan is required")
            raw_record_actions = checkpoint_capture_plan.get(
                "record_actions_by_label"
            )
            raw_command_limits = checkpoint_capture_plan.get(
                "command_limits_by_label"
            )
            raw_always_record_prefixes = checkpoint_capture_plan.get(
                "always_record_prefixes"
            )
            raw_command_overrides = checkpoint_capture_plan.get(
                "command_overrides"
            )
            raw_trace_start_label = checkpoint_capture_plan.get(
                "trace_start_label"
            )
            source_random_seed = checkpoint_capture_plan.get(
                "source_random_seed"
            )
            if (
                not isinstance(raw_record_actions, dict)
                or not isinstance(raw_command_limits, dict)
                or not isinstance(raw_always_record_prefixes, list)
                or not isinstance(raw_command_overrides, list)
            ):
                raise ValueError("checkpoint capture plan is incomplete")
            if raw_trace_start_label is not None and (
                not isinstance(raw_trace_start_label, str)
                or not raw_trace_start_label
            ):
                raise ValueError("checkpoint trace start label is invalid")
            if source_random_seed is not None and (
                not isinstance(source_random_seed, int)
                or isinstance(source_random_seed, bool)
                or not 0 <= source_random_seed <= 0xFFFFFFFF
            ):
                raise ValueError("checkpoint source random seed is invalid")
            recorded_actions_by_label = {
                str(label): tuple(str(action) for action in actions)
                for label, actions in raw_record_actions.items()
                if (
                    isinstance(label, str)
                    and label
                    and isinstance(actions, list)
                    and actions
                    and all(isinstance(action, str) and action for action in actions)
                )
            }
            retained_command_limits = {
                str(label): int(limit)
                for label, limit in raw_command_limits.items()
                if (
                    isinstance(label, str)
                    and label
                    and isinstance(limit, int)
                    and not isinstance(limit, bool)
                    and limit > 0
                )
            }
            if (
                len(recorded_actions_by_label) != len(raw_record_actions)
                or len(retained_command_limits) != len(raw_command_limits)
            ):
                raise ValueError("checkpoint capture labels or limits are invalid")
            if any(
                not isinstance(prefix, str) or not prefix
                for prefix in raw_always_record_prefixes
            ):
                raise ValueError("checkpoint record prefix is invalid")
            always_record_prefixes = tuple(
                str(prefix) for prefix in raw_always_record_prefixes
            )
            command_overrides: dict[
                tuple[str, int], dict[str, object]
            ] = {}
            allowed_override_fields = {
                "fighter_x_override",
                "fighter_y_override",
                "fighter_facing_override",
                "opponent_x_override",
                "opponent_y_override",
                "opponent_facing_override",
            }
            for override in raw_command_overrides:
                if not isinstance(override, dict):
                    raise ValueError("checkpoint command override must be an object")
                override_label = override.get("label")
                values = override.get("values")
                if (
                    not isinstance(override_label, str)
                    or not override_label
                    or not isinstance(values, dict)
                    or not values
                    or set(values) - allowed_override_fields
                ):
                    raise ValueError("checkpoint command override has no values")
                key = (
                    override_label,
                    int(override.get("retained_index", -1)),
                )
                if key[1] < 0 or key in command_overrides:
                    raise ValueError("invalid checkpoint command override")
                command_overrides[key] = dict(values)
            retained_counts = dict.fromkeys(retained_command_limits, 0)
            direct_boundaries = {
                "common_hurt_dash_place",
                "common_hurt_wait_place",
                "common_hurt_standing_turn_place",
                "common_hurt_run_turn_place",
                "common_hurt_guard_place",
                "common_hurt_crouch_place",
                "common_hurt_spot_dodge_shield",
                "common_hurt_crouch_wait_place",
                "common_hurt_walk_slow_place",
                "common_hurt_walk_middle_place",
                "common_hurt_walk_fast_place",
                "common_hurt_run_place",
                "common_hurt_taunt_right_place",
                "common_hurt_taunt_left_place",
            }
            positive_facing_opponent_cases = (
                "common_hurt_spot_dodge_collision_",
                "common_hurt_roll_forward_collision_",
                "common_hurt_roll_backward_collision_",
                "common_hurt_air_dodge_collision_",
                "common_hurt_fall_special_collision_",
                "common_hurt_landing_fall_special_collision_",
                "common_hurt_landing_collision_",
            )
            for sample in source:
                label = str(sample["label"])
                # The complete action-owned pose tracks already supply every
                # capsule used by the importer. Keep one live hit/miss pair to
                # qualify the end-to-end collision integration; the remaining
                # per-pose boundaries are zero-I/O offline evaluations of the
                # same captured capsules against the pinned decomp routine.
                if (
                    "_collision_" in label
                    and not label.startswith("common_hurt_dash_collision_")
                ):
                    continue
                if label in retained_command_limits:
                    retained_index = retained_counts[label]
                    retained_counts[label] += 1
                    if retained_index >= retained_command_limits[label]:
                        continue
                    override_values = command_overrides.get(
                        (label, retained_index)
                    )
                    if override_values is not None:
                        sample = {**sample, **override_values}
                if label.endswith("_reset_place"):
                    pending_restore = True
                    continue
                if (
                    label == "common_hurt_dash_settle"
                    or label.endswith("_reset_place_settle")
                    or label.endswith("_face_right")
                    or label.endswith("_face_right_recover")
                    or label.endswith("_place_settle")
                    or label.endswith("_settle")
                    or (
                        label.endswith("_recover")
                        and label
                        not in (
                            "common_hurt_dash_recover",
                            "common_hurt_knee_bend_recover",
                            "common_hurt_air_dodge_recover",
                        )
                    )
                ):
                    continue
                isolated = sample
                if (
                    label.endswith("_place")
                    and label.startswith(positive_facing_opponent_cases)
                ):
                    isolated = {**isolated, "opponent_facing_override": 1.0}
                direct_boundary = label in direct_boundaries and (
                    not result or result[-1]["label"] != label
                )
                if pending_restore or direct_boundary:
                    isolated = {**isolated, "restore_before": True}
                    if source_random_seed is not None:
                        isolated = {
                            **isolated,
                            "source_random_seed_override": source_random_seed,
                        }
                    pending_restore = False
                recorded_actions = recorded_actions_by_label.get(label)
                if recorded_actions is not None:
                    isolated = {
                        **isolated,
                        "record_actions": recorded_actions,
                    }
                elif not label.startswith(always_record_prefixes):
                    isolated = {**isolated, "record": False}
                result.append(isolated)
            if raw_trace_start_label is not None:
                start_indices = [
                    index
                    for index, sample in enumerate(result)
                    if sample["label"] == raw_trace_start_label
                ]
                if len(start_indices) != 1:
                    raise ValueError(
                        "checkpoint trace start label must occur exactly once"
                    )
                result = result[start_indices[0] :]
            if selected_checkpoint_start_labels:
                selected = set(selected_checkpoint_start_labels)
                retained_labels: set[str] = set()
                retained = False
                filtered: list[dict[str, object]] = []
                for sample in result:
                    if bool(sample.get("restore_before", False)):
                        label = str(sample["label"])
                        retained = label in selected
                        if retained:
                            retained_labels.add(label)
                    if retained:
                        filtered.append(sample)
                if retained_labels != selected:
                    missing = sorted(selected - retained_labels)
                    raise ValueError(
                        "checkpoint start label(s) not found: "
                        + ", ".join(missing)
                    )
                result = filtered
            return result

        def reset_common_hurt_route(
            prefix: str,
            opponent_main_x: float = 1.0,
        ) -> None:
            """Give both ports safe, explicit-facing, zero-velocity entry."""

            trace.append(
                command(
                    f"{prefix}_reset_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=20.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_reset_place_settle", 10)
            repeat(
                f"{prefix}_face_right",
                3,
                main_x=1.0,
                opponent_main_x=opponent_main_x,
            )
            repeat(f"{prefix}_face_right_recover", 45)

        # Initial dash is the first common-state hurt-pose route. Keep the
        # fighter isolated and hold the same full input through Falcon's
        # complete 15-frame Dash animation; later common states can append
        # similarly labelled routes without changing the capture schema.
        repeat("common_hurt_dash_settle", 60)
        trace.append(
            command(
                "common_hurt_dash_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("common_hurt_dash_place_settle", 10)
        repeat("common_hurt_dash_hold", 18, main_x=1.0)
        repeat("common_hurt_dash_recover", 45)

        if (
            checkpoint_capture_plan is not None
            and checkpoint_capture_plan.get("trace_start_label")
            == "common_hurt_wait_place"
        ):
            # Force an ordinary Wait entry through SquatRv instead of sampling
            # the arbitrary menu-origin idle phase. Stop before Wait's endpoint:
            # ftCo_Wait_Anim can select Wait2/Wait3 there through HSD_Randi.
            reset_common_hurt_route("common_hurt_wait")
            trace.append(
                command(
                    "common_hurt_wait_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat("common_hurt_wait_settle", 10)
            repeat("common_hurt_wait_crouch", 12, main_y=0.0)
            repeat("common_hurt_wait_release", 10)
            repeat("common_hurt_wait_hold", 60)

        if checkpoint_capture_plan is not None:
            raw_wait_lifecycle_cases = checkpoint_capture_plan.get(
                "wait_lifecycle_cases"
            )
            if raw_wait_lifecycle_cases is not None:
                if (
                    not isinstance(raw_wait_lifecycle_cases, list)
                    or not raw_wait_lifecycle_cases
                ):
                    raise ValueError("wait lifecycle cases are required")
                wait_lifecycle_case_ids: set[str] = set()
                for raw_case in raw_wait_lifecycle_cases:
                    if not isinstance(raw_case, dict):
                        raise ValueError(
                            "wait lifecycle case must be an object"
                        )
                    case_id = raw_case.get("id")
                    source_random_seed = raw_case.get("source_random_seed")
                    raw_seed_writes = raw_case.get(
                        "source_random_seed_writes",
                        [
                            {
                                "hold_tick": 59,
                                "seed": source_random_seed,
                            }
                        ],
                    )
                    hold_ticks = raw_case.get("hold_ticks")
                    if (
                        not isinstance(case_id, str)
                        or not case_id
                        or case_id in wait_lifecycle_case_ids
                        or not isinstance(source_random_seed, int)
                        or isinstance(source_random_seed, bool)
                        or not 0 <= source_random_seed <= 0xFFFFFFFF
                        or not isinstance(hold_ticks, int)
                        or isinstance(hold_ticks, bool)
                        or hold_ticks <= 60
                    ):
                        raise ValueError("wait lifecycle case is invalid")
                    if (
                        not isinstance(raw_seed_writes, list)
                        or not raw_seed_writes
                    ):
                        raise ValueError("wait lifecycle seed writes are required")
                    seed_writes: list[tuple[int, int]] = []
                    for raw_write in raw_seed_writes:
                        if not isinstance(raw_write, dict):
                            raise ValueError(
                                "wait lifecycle seed write must be an object"
                            )
                        hold_tick = raw_write.get("hold_tick")
                        seed = raw_write.get("seed")
                        if (
                            not isinstance(hold_tick, int)
                            or isinstance(hold_tick, bool)
                            or not 0 <= hold_tick < hold_ticks
                            or not isinstance(seed, int)
                            or isinstance(seed, bool)
                            or not 0 <= seed <= 0xFFFFFFFF
                            or (
                                seed_writes
                                and hold_tick <= seed_writes[-1][0]
                            )
                        ):
                            raise ValueError(
                                "wait lifecycle seed write is invalid"
                            )
                        seed_writes.append((hold_tick, seed))
                    if seed_writes[0] != (59, source_random_seed):
                        raise ValueError(
                            "wait lifecycle first seed write must select base Wait"
                        )
                    wait_lifecycle_case_ids.add(case_id)
                    prefix = f"common_hurt_wait_{case_id}"
                    reset_common_hurt_route(prefix)
                    trace.append(
                        command(
                            f"{prefix}_place",
                            fighter_x_override=-20.0,
                            fighter_y_override=0.0001,
                            opponent_x_override=60.0,
                            opponent_y_override=0.0001,
                            opponent_main_y=0.0,
                        )
                    )
                    repeat(f"{prefix}_settle", 10, opponent_main_y=0.0)
                    repeat(
                        f"{prefix}_crouch",
                        12,
                        main_y=0.0,
                        opponent_main_y=0.0,
                    )
                    repeat(f"{prefix}_release", 10, opponent_main_y=0.0)
                    # Recorded hold row 0 is Wait frame 0. Reassert the
                    # expected source RNG state on each terminal row,
                    # immediately before ftCo_Wait_Anim selects the next idle.
                    # This isolates gameplay selection from unrelated global
                    # HSD consumers while still exercising the real callback.
                    hold_label = f"{prefix}_hold"
                    next_hold_tick = 0
                    for hold_tick, seed in seed_writes:
                        repeat(
                            hold_label,
                            hold_tick - next_hold_tick,
                            opponent_main_y=0.0,
                        )
                        trace.append(
                            command(
                                hold_label,
                                opponent_main_y=0.0,
                                source_random_seed_override=seed,
                            )
                        )
                        next_hold_tick = hold_tick + 1
                    repeat(
                        hold_label,
                        hold_ticks - next_hold_tick,
                        opponent_main_y=0.0,
                    )
                return (
                    checkpoint_isolated_common_hurt_trace(trace)
                    if checkpoint_isolated
                    else trace
                )

        trace.append(
            command(
                "common_hurt_crouch_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("common_hurt_crouch_place_settle", 10)
        repeat("common_hurt_crouch_hold", 12, main_y=0.0)
        repeat("common_hurt_crouch_release", 20)
        repeat("common_hurt_knee_bend_hold", 4, jump=True)
        # KneeBend launches Falcon into a full jump.  Wait for the ordinary
        # landing before entering the grounded EscapeN route; otherwise the
        # same down+shield sample correctly becomes EscapeAir instead.
        repeat("common_hurt_knee_bend_recover", 110)
        # GuardOn and Guard do not expose useful action frames through
        # libmelee, so retain their collision-authoritative animation cursor
        # from the memory probe.  Release then supplies GuardOff's complete
        # ordinary action clock.  Keep this route isolated from the escape
        # cases below so a held shoulder cannot leak into their entry edge.
        reset_common_hurt_route("common_hurt_guard")
        trace.append(
            command(
                "common_hurt_guard_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("common_hurt_guard_settle", 10)
        repeat(
            "common_hurt_guard_hold",
            24,
            left_shoulder=1.0,
        )
        repeat("common_hurt_guard_release", 20)
        repeat(
            "common_hurt_spot_dodge_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "common_hurt_spot_dodge_hold",
                main_y=0.0,
                left_shoulder=1.0,
                digital_left=True,
            )
        )
        repeat("common_hurt_spot_dodge_hold", 35)
        repeat("common_hurt_spot_dodge_recover", 10)
        for motion, main_x in (
            ("roll_forward", 1.0),
            ("roll_backward", -1.0),
        ):
            prefix = f"common_hurt_{motion}"
            # EscapeF flips facing during its animation, and position
            # overrides do not clear residual motion.  Give each source track
            # the same facing-right, fully settled entry state so the two
            # animation poses can be compared and imported independently.
            reset_common_hurt_route(prefix)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            repeat(
                f"{prefix}_shield",
                10,
                left_shoulder=1.0,
                digital_left=True,
            )
            trace.append(
                command(
                    f"{prefix}_hold",
                    main_x=main_x,
                    left_shoulder=1.0,
                    digital_left=True,
                )
            )
            repeat(f"{prefix}_hold", 35)
            repeat(f"{prefix}_recover", 10)
        prefix = "common_hurt_air_dodge"
        # EscapeAir's complete animation cannot be observed near the stage:
        # Falcon lands before its final displayed pose. Enter it through a
        # native jump, then relocate the already-airborne fighter high above
        # Final Destination so all action-owned frames remain collision-free.
        # Neutral stick plus a fresh digital shoulder produces a zero-force
        # air dodge and keeps world translation out of the pose oracle.
        reset_common_hurt_route(prefix)
        trace.append(
            command(
                f"{prefix}_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat(f"{prefix}_settle", 10)
        trace.append(command(f"{prefix}_jump", jump=True))
        repeat(f"{prefix}_jump_rise", 5)
        trace.append(
            command(f"{prefix}_elevate", fighter_y_override=80.0)
        )
        trace.append(
            command(
                f"{prefix}_entry",
                right_shoulder=1.0,
                digital_right=True,
            )
        )
        repeat(f"{prefix}_hold", 55)
        # The first twelve recovery samples finish two FallSpecial cycles;
        # ten more then expose LandingFallSpecial's complete 10-tick,
        # animation-speed-scaled 1,4,...,28 displayed-frame sequence.
        repeat(f"{prefix}_recover", 22)
        for route, distance in (("hit", 31.0), ("miss", 31.5)):
            prefix = f"common_hurt_dash_collision_{route}"
            reset_common_hurt_route(prefix, opponent_main_x=0.0)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=0.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=distance,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            trace.append(
                command(
                    f"{prefix}_jab_vs_dash",
                    attack=True,
                    opponent_main_x=0.0,
                )
            )
            repeat(f"{prefix}_observe", 12, opponent_main_x=0.0)
            repeat(f"{prefix}_recover", 40)
        for route, distance in (("hit", 17.7), ("miss", 17.84)):
            prefix = f"common_hurt_crouch_collision_{route}"
            reset_common_hurt_route(prefix, opponent_main_x=0.0)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=0.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=distance,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            trace.append(
                command(
                    f"{prefix}_jab_vs_crouch",
                    attack=True,
                    opponent_main_y=0.0,
                )
            )
            repeat(f"{prefix}_observe", 12, opponent_main_y=0.0)
            repeat(f"{prefix}_recover", 40)
        for route, distance in (("hit", 16.5), ("miss", 16.8)):
            prefix = f"common_hurt_knee_bend_collision_{route}"
            reset_common_hurt_route(prefix, opponent_main_x=0.0)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=0.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=distance,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            trace.append(
                command(
                    f"{prefix}_jab_start",
                    attack=True,
                )
            )
            trace.append(
                command(
                    f"{prefix}_knee_bend_start",
                    opponent_jump=True,
                )
            )
            repeat(f"{prefix}_observe", 11)
            repeat(f"{prefix}_recover", 60)
        prefix = "common_hurt_spot_dodge_collision"
        # Port 2 begins facing left.  Reorient both ports before memory
        # placement so Jab points toward the positive-x SpotDodge target.
        # Position overrides do not change facing or residual velocity.
        for route, distance in (("hit", 21.0), ("miss", 22.0)):
            route_prefix = f"{prefix}_{route}"
            # Damage turns its victim toward the attacker.  Re-establish the
            # same facing and zero-velocity state before each route so the
            # positive and negative controls differ only by separation.
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=distance,
                    fighter_y_override=0.0001,
                    opponent_x_override=0.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            repeat(
                f"{route_prefix}_shield",
                10,
                left_shoulder=1.0,
                digital_left=True,
            )
            trace.append(
                command(
                    f"{route_prefix}_entry",
                    main_y=0.0,
                    left_shoulder=1.0,
                    digital_left=True,
                )
            )
            # Jab 1's first live geometry is displayed frame 3. Starting it
            # here aligns frame 3 with tangible SpotDodge frame 22; continued
            # frame 4 checks the pending frame-24 pose used by the discriminator.
            repeat(f"{route_prefix}_advance", 18)
            trace.append(
                command(f"{route_prefix}_jab_start", opponent_attack=True)
            )
            repeat(f"{route_prefix}_observe", 15)
            repeat(f"{route_prefix}_recover", 60)
        # The source TransN stream moves EscapeF about +33.38 Melee units by
        # the frame-22 collision pose.  These start positions place that pose
        # at the pre-swept +12.98/+14.18 boundaries: the real hurt
        # capsules miss the latter while the generic rectangle still hits.
        for route, start_x in (("hit", -20.4), ("miss", -19.2)):
            route_prefix = f"common_hurt_roll_forward_collision_{route}"
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=start_x,
                    fighter_y_override=0.0001,
                    opponent_x_override=0.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            repeat(
                f"{route_prefix}_shield",
                10,
                left_shoulder=1.0,
                digital_left=True,
            )
            trace.append(
                command(
                    f"{route_prefix}_entry",
                    main_x=1.0,
                    left_shoulder=1.0,
                    digital_left=True,
                )
            )
            repeat(f"{route_prefix}_advance", 18)
            trace.append(
                command(f"{route_prefix}_jab_start", opponent_attack=True)
            )
            repeat(f"{route_prefix}_observe", 15)
            repeat(f"{route_prefix}_recover", 60)
        # EscapeB from facing right moves about 31.51 Melee units left by the
        # frame-24 pose.  The chosen controls put it at +20.0/+20.75: the
        # real capsules hit only the first, while the generic rectangle misses
        # even that positive route.
        for route, start_x in (("hit", 51.5), ("miss", 52.25)):
            route_prefix = f"common_hurt_roll_backward_collision_{route}"
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=start_x,
                    fighter_y_override=0.0001,
                    opponent_x_override=0.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            repeat(
                f"{route_prefix}_shield",
                10,
                left_shoulder=1.0,
                digital_left=True,
            )
            trace.append(
                command(
                    f"{route_prefix}_entry",
                    main_x=-1.0,
                    left_shoulder=1.0,
                    digital_left=True,
                )
            )
            repeat(f"{route_prefix}_advance", 18)
            trace.append(
                command(f"{route_prefix}_jab_start", opponent_attack=True)
            )
            repeat(f"{route_prefix}_observe", 15)
            repeat(f"{route_prefix}_recover", 60)
        # Keep the AirDodge target just beyond Final Destination's +85.5657
        # floor edge. At displayed frame 31 this preserves the requested low
        # root height without turning the action into LandingFallSpecial.
        # The +21.0 control intersects Falcon's live capsules while +21.8
        # misses; Falcon's former generic rectangle misses both positions.
        # Run the non-damaging control first. The positive route can catch the
        # ledge during its post-hit observation, and ledge-hang intentionally
        # ignores position overrides; keeping it last prevents that terminal
        # state from leaking into another experiment.
        for route, target_x in (("miss", 86.6), ("hit", 85.8)):
            route_prefix = f"common_hurt_air_dodge_collision_{route}"
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=40.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=64.8,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            trace.append(command(f"{route_prefix}_jump", jump=True))
            repeat(f"{route_prefix}_jump_rise", 5)
            trace.append(
                command(
                    f"{route_prefix}_offstage_place",
                    fighter_x_override=target_x,
                    fighter_y_override=1.75,
                    opponent_x_override=64.8,
                    opponent_y_override=0.0001,
                )
            )
            trace.append(
                command(
                    f"{route_prefix}_entry",
                    right_shoulder=1.0,
                    digital_right=True,
                )
            )
            repeat(f"{route_prefix}_advance", 27)
            trace.append(
                command(f"{route_prefix}_jab_start", opponent_attack=True)
            )
            repeat(f"{route_prefix}_observe", 15)
            # Relocate before AirDodge/Falcon's Jab damage can reach a ledge,
            # blast zone, or other state that intentionally ignores memory
            # placement. Both controls then recover naturally over the stage.
            trace.append(
                command(
                    f"{route_prefix}_post_relocate",
                    fighter_x_override=-20.0,
                    fighter_y_override=20.0,
                    opponent_x_override=20.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_recover", 90)
        # FallSpecial is an eight-frame looping common motion.  Enter it
        # natively through EscapeAir before relocating the already-helpless
        # fighter for a low, offstage collision probe.  Holding down during
        # the probe suppresses the otherwise eligible ledge grab without
        # changing the already-entered helpless animation.
        # Jab 1 frame 3 is observed beside FallSpecial frame 4 and evaluates
        # the pending frame-5 pose: the robust 15.5/16.2 controls hit and miss
        # respectively, while the old generic rectangle hits both.
        for route, target_x in (("miss", 86.8), ("hit", 86.1)):
            route_prefix = f"common_hurt_fall_special_collision_{route}"
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            trace.append(command(f"{route_prefix}_jump", jump=True))
            repeat(f"{route_prefix}_jump_rise", 5)
            trace.append(
                command(
                    f"{route_prefix}_elevate",
                    fighter_y_override=80.0,
                )
            )
            trace.append(
                command(
                    f"{route_prefix}_air_dodge_entry",
                    right_shoulder=1.0,
                    digital_right=True,
                )
            )
            # EscapeAir contributes frames 2-49; the final sample enters
            # FallSpecial frame 1.  Relocation on the following command is
            # pre-physics; the held-down fast fall makes 13.5 produce the
            # requested frame-4 root near y=3.0.
            repeat(f"{route_prefix}_advance", 49)
            trace.append(
                command(
                    f"{route_prefix}_jab_start",
                    fighter_x_override=target_x,
                    fighter_y_override=13.5,
                    opponent_x_override=70.6,
                    opponent_y_override=0.0001,
                    main_y=0.0,
                    opponent_attack=True,
                )
            )
            repeat(f"{route_prefix}_observe", 8, main_y=0.0)
            trace.append(
                command(
                    f"{route_prefix}_post_relocate",
                    fighter_x_override=-20.0,
                    fighter_y_override=20.0,
                    opponent_x_override=20.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_recover", 90)
        # A native downward EscapeAir from jump height enters
        # LandingFallSpecial on the following sample.  Starting Jab 1 with
        # EscapeAir aligns its first live frame with the second landing tick
        # (displayed frame 4), whose collision evaluates the pending frame-7
        # pose.  The robust 18.5/19.3 controls hit and miss respectively,
        # while the former generic rectangle misses both.
        for route, target_x in (("miss", 19.3), ("hit", 18.5)):
            route_prefix = (
                f"common_hurt_landing_fall_special_collision_{route}"
            )
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=target_x,
                    fighter_y_override=0.0001,
                    opponent_x_override=0.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            trace.append(command(f"{route_prefix}_jump", jump=True))
            repeat(f"{route_prefix}_jump_rise", 5)
            trace.append(
                command(
                    f"{route_prefix}_entry_and_jab",
                    main_y=0.0,
                    right_shoulder=1.0,
                    digital_right=True,
                    opponent_attack=True,
                )
            )
            repeat(f"{route_prefix}_observe", 12, main_y=0.0)
            repeat(f"{route_prefix}_recover", 90)
        # Ordinary Landing keeps playing its complete 30-frame source motion
        # after the frame-4 interrupt gate when no input is supplied.  Starting
        # the opponent's Jab 1 on displayed Landing frame 19 makes its first
        # live collision evaluate the pending frame-22 pose.  That pose reaches
        # the 20.3-unit control but not 20.6; the generic rectangle misses both.
        for route, target_x in (("miss", 20.6), ("hit", 20.3)):
            route_prefix = f"common_hurt_landing_collision_{route}"
            reset_common_hurt_route(route_prefix)
            trace.append(
                command(
                    f"{route_prefix}_place",
                    fighter_x_override=target_x,
                    fighter_y_override=0.0001,
                    opponent_x_override=0.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{route_prefix}_settle", 10)
            repeat(f"{route_prefix}_jump", 4, jump=True)
            repeat(f"{route_prefix}_advance", 67)
            trace.append(
                command(
                    f"{route_prefix}_jab_start",
                    opponent_attack=True,
                )
            )
            repeat(f"{route_prefix}_observe", 8)
            repeat(f"{route_prefix}_recover", 40)

        # Long-lived grounded motions form a compact supplemental pose pack.
        # Each route starts from the same checkpoint and records one complete
        # source animation cycle; one extra held sample on looping motions
        # proves the terminal-to-first-frame wrap without another oracle.
        reset_common_hurt_route("common_hurt_crouch_wait")
        trace.append(
            command(
                "common_hurt_crouch_wait_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("common_hurt_crouch_wait_settle", 10)
        trace.append(command("common_hurt_crouch_wait_prime"))
        repeat("common_hurt_crouch_wait_entry", 8, main_y=0.0)
        repeat("common_hurt_crouch_wait_hold", 160, main_y=0.0)

        for walk_name, main_x, sample_count in (
            ("slow", 0.65, 55),
            ("middle", 0.75, 41),
            ("fast", 0.95, 40),
        ):
            prefix = f"common_hurt_walk_{walk_name}"
            reset_common_hurt_route(prefix)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            trace.append(command(f"{prefix}_prime"))
            if walk_name == "fast":
                # Enter Walk below its fast-gait velocity threshold before
                # raising the stick. A fresh 0.9 source-axis sample would be
                # eligible for Dash; once Walk owns the callback, 0.9 reaches
                # Falcon's 0.8 * walk_max_vel fast-gait boundary naturally.
                repeat(f"{prefix}_ramp", 8, main_x=0.85)
            repeat(f"{prefix}_hold", sample_count, main_x=main_x)

        reset_common_hurt_route("common_hurt_run")
        trace.append(
            command(
                "common_hurt_run_place",
                fighter_x_override=-20.0,
                fighter_y_override=0.0001,
                opponent_x_override=60.0,
                opponent_y_override=0.0001,
            )
        )
        repeat("common_hurt_run_settle", 10)
        trace.append(command("common_hurt_run_prime"))
        repeat("common_hurt_run_entry", 20, main_x=1.0)
        repeat("common_hurt_run_hold", 21, main_x=1.0)

        for taunt_name in ("right", "left"):
            prefix = f"common_hurt_taunt_{taunt_name}"
            reset_common_hurt_route(prefix)
            trace.append(
                command(
                    f"{prefix}_place",
                    fighter_x_override=(
                        0.0 if taunt_name == "left" else -20.0
                    ),
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat(f"{prefix}_settle", 10)
            trace.append(command(f"{prefix}_prime"))
            if taunt_name == "left":
                trace.append(command(f"{prefix}_orient", main_x=0.0))
                repeat(f"{prefix}_orient_neutral", 15)
            trace.append(command(f"{prefix}_entry", taunt=True))
            repeat(f"{prefix}_hold", 60)

        if (
            checkpoint_capture_plan is not None
            and checkpoint_capture_plan.get("trace_start_label")
            == "common_hurt_standing_turn_place"
        ):
            # Turn and TurnRun form a compact supplemental profile. Keep them
            # consecutive so trace_start_label can omit every unrelated common
            # route before the first checkpoint, and end on the held reverse
            # direction because no later case may inherit host controller state.
            reset_common_hurt_route("common_hurt_standing_turn")
            trace.append(
                command(
                    "common_hurt_standing_turn_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat("common_hurt_standing_turn_settle", 10)
            trace.append(command("common_hurt_standing_turn_entry", main_x=0.0))
            repeat("common_hurt_standing_turn_hold", 14)

            reset_common_hurt_route("common_hurt_run_turn")
            trace.append(
                command(
                    "common_hurt_run_turn_place",
                    fighter_x_override=-20.0,
                    fighter_y_override=0.0001,
                    opponent_x_override=60.0,
                    opponent_y_override=0.0001,
                )
            )
            repeat("common_hurt_run_turn_settle", 10)
            repeat("common_hurt_run_turn_run", 25, main_x=1.0)
            trace.append(command("common_hurt_run_turn_entry", main_x=0.0))
            repeat("common_hurt_run_turn_hold", 35, main_x=0.0)
        return (
            checkpoint_isolated_common_hurt_trace(trace)
            if checkpoint_isolated
            else trace
        )

    if damage_hit_only:
        if checkpoint_isolated:
            if checkpoint_capture_plan is None:
                raise ValueError("checkpoint capture plan is required")

            def response_observation_segments(
                raw_segments: object,
                fallback_main: list[object],
            ) -> list[
                tuple[
                    str,
                    int,
                    dict[str, object],
                    dict[str, object] | list[dict[str, object]] | None,
                    tuple[int, ...] | None,
                    dict[str, int] | None,
                    tuple[int, ...] | None,
                ]
            ]:
                if not isinstance(raw_segments, list) or not raw_segments:
                    raise ValueError("response observation segments are invalid")
                segments: list[
                    tuple[
                        str,
                        int,
                        dict[str, object],
                        dict[str, object] | list[dict[str, object]] | None,
                        tuple[int, ...] | None,
                        dict[str, int] | None,
                        tuple[int, ...] | None,
                    ]
                ] = []
                segment_ids: set[str] = set()
                total_ticks = 0
                for raw_segment in raw_segments:
                    if not isinstance(raw_segment, dict):
                        raise ValueError(
                            "response observation segment must be an object"
                        )
                    segment_id = raw_segment.get("id")
                    ticks = raw_segment.get("ticks")
                    main = raw_segment.get("main", fallback_main)
                    secondary = raw_segment.get("secondary", [0, 0])
                    button_fields = (
                        "digital_left",
                        "digital_right",
                        "jump",
                        "attack",
                        "special",
                        "grab",
                        "taunt",
                    )
                    allowed_fields = {
                        "id",
                        "ticks",
                        "main",
                        "secondary",
                        "fighter_x_override",
                        "fighter_y_override",
                        "fighter_facing_override",
                        "conditional_edge",
                        "record_cliff_wait_timers",
                        "cliff_wait_timer_jump",
                        "record_ledge_regrab_cooldowns",
                        *button_fields,
                    }
                    raw_conditional_edge = raw_segment.get(
                        "conditional_edge"
                    )
                    raw_record_cliff_wait_timers = raw_segment.get(
                        "record_cliff_wait_timers"
                    )
                    raw_cliff_wait_timer_jump = raw_segment.get(
                        "cliff_wait_timer_jump"
                    )
                    raw_record_ledge_regrab_cooldowns = raw_segment.get(
                        "record_ledge_regrab_cooldowns"
                    )
                    segment_fighter_x = raw_segment.get(
                        "fighter_x_override"
                    )
                    segment_fighter_y = raw_segment.get(
                        "fighter_y_override"
                    )
                    segment_fighter_facing = raw_segment.get(
                        "fighter_facing_override"
                    )
                    if (
                        not isinstance(segment_id, str)
                        or not segment_id
                        or segment_id in segment_ids
                        or any(
                            character
                            not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                            for character in segment_id
                        )
                        or not isinstance(ticks, int)
                        or isinstance(ticks, bool)
                        or not 1 <= ticks <= 720
                        or not isinstance(main, list)
                        or len(main) != 2
                        or not isinstance(secondary, list)
                        or len(secondary) != 2
                        or not set(raw_segment).issubset(allowed_fields)
                        or any(
                            value is not None
                            and (
                                not isinstance(value, (int, float))
                                or isinstance(value, bool)
                                or not -1000.0 <= float(value) <= 1000.0
                            )
                            for value in (
                                segment_fighter_x,
                                segment_fighter_y,
                            )
                        )
                        or (
                            segment_fighter_facing is not None
                            and (
                                not isinstance(
                                    segment_fighter_facing, (int, float)
                                )
                                or isinstance(segment_fighter_facing, bool)
                                or float(segment_fighter_facing)
                                not in (-1.0, 1.0)
                            )
                        )
                        or any(
                            not isinstance(raw_segment.get(field, False), bool)
                            for field in button_fields
                        )
                    ):
                        raise ValueError(
                            f"invalid response observation segment {segment_id!r}"
                        )
                    record_cliff_wait_timers: tuple[int, ...] | None = None
                    if raw_record_cliff_wait_timers is not None:
                        if (
                            not isinstance(raw_record_cliff_wait_timers, list)
                            or not raw_record_cliff_wait_timers
                            or any(
                                not isinstance(timer, int)
                                or isinstance(timer, bool)
                                or not 0 <= timer <= 1000
                                for timer in raw_record_cliff_wait_timers
                            )
                            or len(raw_record_cliff_wait_timers)
                            != len(set(raw_record_cliff_wait_timers))
                        ):
                            raise ValueError(
                                "record_cliff_wait_timers must contain unique "
                                "non-negative integer timers"
                            )
                        record_cliff_wait_timers = tuple(
                            raw_record_cliff_wait_timers
                        )
                    cliff_wait_timer_jump: dict[str, int] | None = None
                    if raw_cliff_wait_timer_jump is not None:
                        if (
                            not isinstance(raw_cliff_wait_timer_jump, dict)
                            or set(raw_cliff_wait_timer_jump)
                            != {"write_on_action_frame", "value"}
                            or any(
                                not isinstance(
                                    raw_cliff_wait_timer_jump.get(field), int
                                )
                                or isinstance(
                                    raw_cliff_wait_timer_jump.get(field), bool
                                )
                                for field in ("write_on_action_frame", "value")
                            )
                            or not 1
                            <= raw_cliff_wait_timer_jump["write_on_action_frame"]
                            <= 500
                            or not 2 <= raw_cliff_wait_timer_jump["value"] <= 1000
                            or record_cliff_wait_timers is None
                            or max(record_cliff_wait_timers)
                            <= raw_cliff_wait_timer_jump["value"]
                            or not all(
                                timer == max(record_cliff_wait_timers)
                                or timer < raw_cliff_wait_timer_jump["value"]
                                for timer in record_cliff_wait_timers
                            )
                        ):
                            raise ValueError(
                                "cliff_wait_timer_jump must declare a valid "
                                "action frame and a value between the initial "
                                "timer and every sparse boundary"
                            )
                        cliff_wait_timer_jump = {
                            "write_on_action_frame": int(
                                raw_cliff_wait_timer_jump[
                                    "write_on_action_frame"
                                ]
                            ),
                            "value": int(raw_cliff_wait_timer_jump["value"]),
                        }
                    record_ledge_regrab_cooldowns: tuple[int, ...] | None = None
                    if raw_record_ledge_regrab_cooldowns is not None:
                        if (
                            not isinstance(
                                raw_record_ledge_regrab_cooldowns, list
                            )
                            or not raw_record_ledge_regrab_cooldowns
                            or any(
                                not isinstance(cooldown, int)
                                or isinstance(cooldown, bool)
                                or not 0 <= cooldown <= 1000
                                for cooldown in raw_record_ledge_regrab_cooldowns
                            )
                            or len(raw_record_ledge_regrab_cooldowns)
                            != len(set(raw_record_ledge_regrab_cooldowns))
                        ):
                            raise ValueError(
                                "record_ledge_regrab_cooldowns must contain "
                                "unique non-negative integer timers"
                            )
                        record_ledge_regrab_cooldowns = tuple(
                            raw_record_ledge_regrab_cooldowns
                        )
                    inputs: dict[str, object] = {
                        "main_x": controller_axis(main[0]),
                        "main_y": controller_axis(main[1]),
                        "c_x": controller_axis(secondary[0]),
                        "c_y": controller_axis(secondary[1]),
                        "fighter_x_override": segment_fighter_x,
                        "fighter_y_override": segment_fighter_y,
                        "fighter_facing_override": segment_fighter_facing,
                    }
                    inputs.update(
                        {
                            field: raw_segment.get(field, False)
                            for field in button_fields
                        }
                    )
                    conditional_edge: (
                        dict[str, object] | list[dict[str, object]] | None
                    ) = None
                    if raw_conditional_edge is not None:
                        raw_conditional_edges = (
                            [raw_conditional_edge]
                            if isinstance(raw_conditional_edge, dict)
                            else raw_conditional_edge
                        )
                        if (
                            not isinstance(raw_conditional_edges, list)
                            or not raw_conditional_edges
                            or any(
                                not isinstance(edge, dict)
                                for edge in raw_conditional_edges
                            )
                        ):
                            raise ValueError(
                                "conditional response edge must be an object or "
                                "a non-empty object list"
                            )
                        edge_allowed_fields = {
                            "owner",
                            "action",
                            "frame",
                            "main",
                            "secondary",
                            "damage_percent",
                            "opponent_x_override",
                            "opponent_y_override",
                            "opponent_facing_override",
                            "opponent_attack",
                            *button_fields,
                        }
                        parsed_edges: list[dict[str, object]] = []
                        edge_boundaries: set[tuple[str, str, int]] = set()
                        for raw_edge in raw_conditional_edges:
                            edge_owner = raw_edge.get("owner", "fighter")
                            edge_action = raw_edge.get("action")
                            edge_frame = raw_edge.get("frame")
                            edge_main = raw_edge.get("main", main)
                            edge_secondary = raw_edge.get("secondary", secondary)
                            edge_damage = raw_edge.get("damage_percent")
                            edge_opponent_x = raw_edge.get("opponent_x_override")
                            edge_opponent_y = raw_edge.get("opponent_y_override")
                            edge_opponent_facing = raw_edge.get(
                                "opponent_facing_override"
                            )
                            if (
                                edge_owner not in {"fighter", "opponent"}
                                or not isinstance(edge_action, str)
                                or edge_action not in melee.Action.__members__
                                or not isinstance(edge_frame, int)
                                or isinstance(edge_frame, bool)
                                or not 0 <= edge_frame <= 500
                                or not isinstance(edge_main, list)
                                or len(edge_main) != 2
                                or not isinstance(edge_secondary, list)
                                or len(edge_secondary) != 2
                                or not set(raw_edge).issubset(edge_allowed_fields)
                                or (
                                    edge_damage is not None
                                    and (
                                        not isinstance(edge_damage, (int, float))
                                        or isinstance(edge_damage, bool)
                                        or not 0.0 <= float(edge_damage) <= 999.0
                                    )
                                )
                                or any(
                                    value is not None
                                    and (
                                        not isinstance(value, (int, float))
                                        or isinstance(value, bool)
                                        or not -1000.0 <= float(value) <= 1000.0
                                    )
                                    for value in (
                                        edge_opponent_x,
                                        edge_opponent_y,
                                    )
                                )
                                or (
                                    edge_opponent_facing is not None
                                    and edge_opponent_facing not in (-1, 1)
                                )
                                or any(
                                    not isinstance(raw_edge.get(field, False), bool)
                                    for field in (
                                        *button_fields,
                                        "opponent_attack",
                                    )
                                )
                                or (
                                    edge_owner,
                                    edge_action,
                                    edge_frame,
                                )
                                in edge_boundaries
                            ):
                                raise ValueError(
                                    f"invalid conditional response edge in "
                                    f"{segment_id!r}"
                                )
                            edge_boundaries.add(
                                (edge_owner, edge_action, edge_frame)
                            )
                            edge_inputs: dict[str, object] = {
                                "main_x": controller_axis(edge_main[0]),
                                "main_y": controller_axis(edge_main[1]),
                                "c_x": controller_axis(edge_secondary[0]),
                                "c_y": controller_axis(edge_secondary[1]),
                            }
                            edge_inputs.update(
                                {
                                    field: raw_edge.get(field, False)
                                    for field in button_fields
                                }
                            )
                            edge_inputs["fighter_damage_override"] = (
                                None
                                if edge_damage is None
                                else float(edge_damage)
                            )
                            edge_inputs["opponent_x_override"] = (
                                None
                                if edge_opponent_x is None
                                else float(edge_opponent_x)
                            )
                            edge_inputs["opponent_y_override"] = (
                                None
                                if edge_opponent_y is None
                                else float(edge_opponent_y)
                            )
                            edge_inputs["opponent_facing_override"] = (
                                None
                                if edge_opponent_facing is None
                                else float(edge_opponent_facing)
                            )
                            edge_inputs["opponent_attack"] = raw_edge.get(
                                "opponent_attack", False
                            )
                            parsed_edges.append(
                                {
                                    "owner": edge_owner,
                                    "action": edge_action,
                                    "frame": edge_frame,
                                    "inputs": edge_inputs,
                                }
                            )
                        conditional_edge = (
                            parsed_edges[0]
                            if len(parsed_edges) == 1
                            else parsed_edges
                        )
                    segment_ids.add(segment_id)
                    total_ticks += ticks
                    segments.append(
                        (
                            segment_id,
                            ticks,
                            inputs,
                            conditional_edge,
                            record_cliff_wait_timers,
                            cliff_wait_timer_jump,
                            record_ledge_regrab_cooldowns,
                        )
                    )
                if total_ticks > 720:
                    raise ValueError(
                        "response observation segments exceed 720 ticks"
                    )
                return segments

            raw_surface_cases = checkpoint_capture_plan.get(
                "surface_response_cases"
            )
            surface_response_prefix = "surface_response"
            if raw_surface_cases is None:
                raw_surface_cases = checkpoint_capture_plan.get(
                    "floor_response_cases"
                )
                surface_response_prefix = "floor_response"
            if raw_surface_cases is not None:
                if not isinstance(raw_surface_cases, list) or not raw_surface_cases:
                    raise ValueError("surface response cases are invalid")
                record_response_only = checkpoint_capture_plan.get(
                    "record_response_only", False
                )
                if not isinstance(record_response_only, bool):
                    raise ValueError("record_response_only must be boolean")
                case_ids: set[str] = set()
                for raw_case in raw_surface_cases:
                    if not isinstance(raw_case, dict):
                        raise ValueError(
                            "surface response case must be an object"
                        )
                    case_id = raw_case.get("id")
                    damage = raw_case.get("damage_percent")
                    impact_x = raw_case.get("impact_x")
                    impact_y = raw_case.get("impact_y")
                    impact_opponent_x = raw_case.get("impact_opponent_x")
                    impact_waypoints = raw_case.get("impact_waypoints", [])
                    impact_waypoint_main = raw_case.get(
                        "impact_waypoint_main", [0, 0]
                    )
                    trigger_waypoint_index = raw_case.get(
                        "trigger_waypoint_index"
                    )
                    target_start = raw_case.get("target_start")
                    opponent_start = raw_case.get("opponent_start")
                    approach_main = raw_case.get("approach_main")
                    attack_main = raw_case.get(
                        "attack_main",
                        [approach_main, 0],
                    )
                    default_facing = (
                        -1
                        if isinstance(approach_main, int) and approach_main < 0
                        else 1
                    )
                    target_facing = raw_case.get(
                        "target_facing",
                        default_facing,
                    )
                    opponent_facing = raw_case.get(
                        "opponent_facing",
                        default_facing,
                    )
                    setup_settle_ticks = raw_case.get("setup_settle_ticks", 5)
                    setup_jump_ticks = raw_case.get("setup_jump_ticks", 4)
                    setup_air_wait_ticks = raw_case.get("setup_air_wait_ticks", 12)
                    placement_ticks = raw_case.get("placement_ticks", 3)
                    settle_ticks = raw_case.get("settle_ticks", 30)
                    approach_ticks = raw_case.get("approach_ticks", 4)
                    post_hit_ticks = raw_case.get("post_hit_ticks", 8)
                    raw_observe_segments = raw_case.get("observe_segments")
                    raw_record_actions = raw_case.get("record_actions")
                    response_start_position = raw_case.get(
                        "response_start_position"
                    )
                    response_zero_velocity = raw_case.get(
                        "response_zero_velocity", False
                    )
                    observe_ticks = raw_case.get(
                        "observe_ticks",
                        60 if raw_observe_segments is None else None,
                    )
                    main = raw_case.get("impact_main", [0, 0])
                    pre_impact_y = raw_case.get("pre_impact_y")
                    impact_input_delay_ticks = raw_case.get(
                        "impact_input_delay_ticks", 0
                    )
                    impact_x_hold_ticks = raw_case.get(
                        "impact_x_hold_ticks", 0
                    )
                    impact_trigger_hold_index = raw_case.get(
                        "impact_trigger_hold_index"
                    )
                    trigger = raw_case.get("trigger", "none")
                    jump = raw_case.get("jump", False)
                    source_random_seed = raw_case.get(
                        "source_random_seed",
                        checkpoint_capture_plan.get("source_random_seed"),
                    )
                    source_random_seed_before_attack = raw_case.get(
                        "source_random_seed_before_attack",
                        checkpoint_capture_plan.get(
                            "source_random_seed_before_attack"
                        ),
                    )
                    source_random_seed_post_hit_index = raw_case.get(
                        "source_random_seed_post_hit_index",
                        checkpoint_capture_plan.get(
                            "source_random_seed_post_hit_index"
                        ),
                    )
                    if (
                        not isinstance(case_id, str)
                        or not case_id
                        or case_id in case_ids
                        or not isinstance(damage, (int, float))
                        or isinstance(damage, bool)
                        or not 0.0 <= float(damage) <= 999.0
                        or (
                            (impact_x is None) != (impact_y is None)
                            or (
                                impact_x is not None
                                and (
                                    not isinstance(impact_x, (int, float))
                                    or isinstance(impact_x, bool)
                                    or not isinstance(impact_y, (int, float))
                                    or isinstance(impact_y, bool)
                                )
                            )
                        )
                        or (
                            impact_opponent_x is not None
                            and (
                                not isinstance(impact_opponent_x, (int, float))
                                or isinstance(impact_opponent_x, bool)
                                or (impact_x is None and not impact_waypoints)
                            )
                        )
                        or not isinstance(impact_waypoints, list)
                        or any(
                            not isinstance(point, list)
                            or len(point) != 2
                            or any(
                                not isinstance(value, (int, float))
                                or isinstance(value, bool)
                                for value in point
                            )
                            for point in impact_waypoints
                        )
                        or len(impact_waypoints) > 8
                        or not isinstance(impact_waypoint_main, list)
                        or len(impact_waypoint_main) != 2
                        or (
                            impact_x is not None and bool(impact_waypoints)
                        )
                        or (
                            trigger_waypoint_index is not None
                            and (
                                not isinstance(trigger_waypoint_index, int)
                                or isinstance(trigger_waypoint_index, bool)
                                or not impact_waypoints
                                or not 0
                                <= trigger_waypoint_index
                                < len(impact_waypoints)
                                or trigger == "none"
                            )
                        )
                        or not isinstance(target_start, list)
                        or len(target_start) != 2
                        or not all(
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            for value in target_start
                        )
                        or not isinstance(opponent_start, list)
                        or len(opponent_start) != 2
                        or not all(
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            for value in opponent_start
                        )
                        or not isinstance(approach_main, int)
                        or isinstance(approach_main, bool)
                        or not -32767 <= approach_main <= 32767
                        or not isinstance(attack_main, list)
                        or len(attack_main) != 2
                        or target_facing not in {-1, 1}
                        or isinstance(target_facing, bool)
                        or opponent_facing not in {-1, 1}
                        or isinstance(opponent_facing, bool)
                        or not isinstance(setup_settle_ticks, int)
                        or isinstance(setup_settle_ticks, bool)
                        or not 1 <= setup_settle_ticks <= 30
                        or not isinstance(setup_jump_ticks, int)
                        or isinstance(setup_jump_ticks, bool)
                        or not 1 <= setup_jump_ticks <= 8
                        or not isinstance(setup_air_wait_ticks, int)
                        or isinstance(setup_air_wait_ticks, bool)
                        or not 1 <= setup_air_wait_ticks <= 60
                        or not isinstance(placement_ticks, int)
                        or isinstance(placement_ticks, bool)
                        or not 1 <= placement_ticks <= 8
                        or not isinstance(settle_ticks, int)
                        or isinstance(settle_ticks, bool)
                        or not 1 <= settle_ticks <= 120
                        or not isinstance(approach_ticks, int)
                        or isinstance(approach_ticks, bool)
                        or not 1 <= approach_ticks <= 30
                        or not isinstance(post_hit_ticks, int)
                        or isinstance(post_hit_ticks, bool)
                        or not 1 <= post_hit_ticks <= 120
                        or (
                            raw_observe_segments is None
                            and (
                                not isinstance(observe_ticks, int)
                                or isinstance(observe_ticks, bool)
                                or not 1 <= observe_ticks <= 180
                            )
                        )
                        or (
                            raw_observe_segments is not None
                            and "observe_ticks" in raw_case
                        )
                        or (
                            raw_record_actions is not None
                            and (
                                not isinstance(raw_record_actions, list)
                                or not raw_record_actions
                                or any(
                                    not isinstance(action, str)
                                    or action not in melee.Action.__members__
                                    for action in raw_record_actions
                                )
                            )
                        )
                        or (
                            response_start_position is not None
                            and (
                                not isinstance(response_start_position, list)
                                or len(response_start_position) != 2
                                or any(
                                    not isinstance(value, (int, float))
                                    or isinstance(value, bool)
                                    or not -1000.0 <= float(value) <= 1000.0
                                    for value in response_start_position
                                )
                            )
                        )
                        or not isinstance(response_zero_velocity, bool)
                        or not isinstance(main, list)
                        or len(main) != 2
                        or (
                            pre_impact_y is not None
                            and (
                                not isinstance(pre_impact_y, (int, float))
                                or isinstance(pre_impact_y, bool)
                            )
                        )
                        or not isinstance(impact_input_delay_ticks, int)
                        or isinstance(impact_input_delay_ticks, bool)
                        or not 0 <= impact_input_delay_ticks <= 10
                        or not isinstance(impact_x_hold_ticks, int)
                        or isinstance(impact_x_hold_ticks, bool)
                        or not 0 <= impact_x_hold_ticks <= 60
                        or (impact_x_hold_ticks != 0 and impact_x is None)
                        or (
                            impact_trigger_hold_index is not None
                            and (
                                not isinstance(impact_trigger_hold_index, int)
                                or isinstance(impact_trigger_hold_index, bool)
                                or trigger == "none"
                                or not 0
                                <= impact_trigger_hold_index
                                < impact_x_hold_ticks
                            )
                        )
                        or trigger not in {"none", "left", "right"}
                        or not isinstance(jump, bool)
                        or (
                            source_random_seed is not None
                            and (
                                not isinstance(source_random_seed, int)
                                or isinstance(source_random_seed, bool)
                                or not 0 <= source_random_seed <= 0xFFFFFFFF
                            )
                        )
                        or (
                            source_random_seed_before_attack is not None
                            and (
                                not isinstance(
                                    source_random_seed_before_attack,
                                    int,
                                )
                                or isinstance(
                                    source_random_seed_before_attack,
                                    bool,
                                )
                                or not 0
                                <= source_random_seed_before_attack
                                <= 0xFFFFFFFF
                            )
                        )
                        or (
                            source_random_seed is not None
                            and source_random_seed_before_attack is not None
                        )
                        or (
                            (source_random_seed is None)
                            != (source_random_seed_post_hit_index is None)
                        )
                        or (
                            source_random_seed_post_hit_index is not None
                            and (
                                not isinstance(
                                    source_random_seed_post_hit_index, int
                                )
                                or isinstance(
                                    source_random_seed_post_hit_index, bool
                                )
                                or not 0
                                <= source_random_seed_post_hit_index
                                < post_hit_ticks
                            )
                        )
                    ):
                        raise ValueError(
                            f"invalid surface response case {case_id!r}"
                        )
                    main_x = controller_axis(main[0])
                    main_y = controller_axis(main[1])
                    observe_segments = (
                        response_observation_segments(
                            raw_observe_segments,
                            main,
                        )
                        if raw_observe_segments is not None
                        else [
                            (
                                "observe",
                                observe_ticks,
                                {"main_x": main_x, "main_y": main_y},
                                None,
                                None,
                                None,
                                None,
                            )
                        ]
                    )
                    waypoint_main_x = controller_axis(
                        impact_waypoint_main[0]
                    )
                    waypoint_main_y = controller_axis(
                        impact_waypoint_main[1]
                    )
                    approach_x = controller_axis(approach_main)
                    attack_main_x = controller_axis(attack_main[0])
                    attack_main_y = controller_axis(attack_main[1])
                    case_ids.add(case_id)
                    prefix = f"{surface_response_prefix}_{case_id}"
                    case_trace_start = len(trace)
                    setup = command(
                        f"{prefix}_setup",
                        fighter_damage_override=float(damage),
                    )
                    trace.append({**setup, "restore_before": True})
                    repeat(f"{prefix}_setup_settle", setup_settle_ticks)
                    repeat(
                        f"{prefix}_setup_jump",
                        setup_jump_ticks,
                        jump=True,
                        opponent_jump=True,
                    )
                    repeat(f"{prefix}_setup_air_wait", setup_air_wait_ticks)
                    place = command(
                        f"{prefix}_place",
                        fighter_x_override=float(target_start[0]),
                        fighter_y_override=float(target_start[1]),
                        fighter_facing_override=float(target_facing),
                        fighter_damage_override=float(damage),
                        opponent_x_override=float(opponent_start[0]),
                        opponent_y_override=float(opponent_start[1]),
                        opponent_facing_override=float(opponent_facing),
                    )
                    trace.append(place)
                    if placement_ticks > 1:
                        repeat(
                            f"{prefix}_place_hold",
                            placement_ticks - 1,
                            fighter_x_override=float(target_start[0]),
                            fighter_y_override=float(target_start[1]),
                            fighter_facing_override=float(target_facing),
                            fighter_damage_override=float(damage),
                            opponent_x_override=float(opponent_start[0]),
                            opponent_y_override=float(opponent_start[1]),
                            opponent_facing_override=float(opponent_facing),
                        )
                    repeat(f"{prefix}_settle", settle_ticks)
                    repeat(
                        f"{prefix}_approach",
                        approach_ticks,
                        opponent_main_x=approach_x,
                    )
                    trace.append(
                        command(
                            f"{prefix}_attack",
                            opponent_main_x=attack_main_x,
                            opponent_main_y=attack_main_y,
                            opponent_attack=True,
                            source_random_seed_override=(
                                source_random_seed_before_attack
                            ),
                        )
                    )
                    for post_hit_index in range(post_hit_ticks):
                        trace.append(
                            command(
                                f"{prefix}_post_hit",
                                source_random_seed_override=(
                                    source_random_seed
                                    if post_hit_index
                                    == source_random_seed_post_hit_index
                                    else None
                                ),
                            )
                        )
                    if pre_impact_y is not None:
                        trace.append(
                            command(
                                f"{prefix}_pre_impact_lift",
                                main_x=main_x,
                                main_y=main_y,
                                digital_left=trigger == "left",
                                digital_right=trigger == "right",
                                jump=jump,
                                fighter_y_override=float(pre_impact_y),
                            )
                        )
                    if impact_x is not None:
                        trace.append(
                            command(
                                f"{prefix}_impact_place",
                                fighter_x_override=float(impact_x),
                                fighter_y_override=float(impact_y),
                                opponent_x_override=(
                                    float(impact_opponent_x)
                                    if impact_opponent_x is not None
                                    else None
                                ),
                            )
                        )
                        for hold_index in range(impact_x_hold_ticks):
                            trigger_active = (
                                trigger != "none"
                                and (
                                    impact_trigger_hold_index is None
                                    or hold_index
                                    >= impact_trigger_hold_index
                                )
                            )
                            trace.append(
                                command(
                                    f"{prefix}_impact_x_hold",
                                    main_x=main_x,
                                    main_y=main_y,
                                    digital_left=(
                                        trigger_active
                                        and trigger == "left"
                                    ),
                                    digital_right=(
                                        trigger_active
                                        and trigger == "right"
                                    ),
                                    jump=trigger_active and jump,
                                    fighter_x_override=float(impact_x),
                                )
                            )
                        repeat(
                            f"{prefix}_impact_wait",
                            impact_input_delay_ticks,
                        )
                    elif impact_waypoints:
                        for waypoint_index, point in enumerate(
                            impact_waypoints
                        ):
                            trigger_on_waypoint = (
                                waypoint_index == trigger_waypoint_index
                            )
                            trace.append(
                                command(
                                    f"{prefix}_impact_waypoint_"
                                    f"{waypoint_index}",
                                    main_x=waypoint_main_x,
                                    main_y=waypoint_main_y,
                                    digital_left=(
                                        trigger_on_waypoint
                                        and trigger == "left"
                                    ),
                                    digital_right=(
                                        trigger_on_waypoint
                                        and trigger == "right"
                                    ),
                                    jump=trigger_on_waypoint and jump,
                                    fighter_x_override=float(point[0]),
                                    fighter_y_override=float(point[1]),
                                    opponent_x_override=(
                                        float(impact_opponent_x)
                                        if impact_opponent_x is not None
                                        and waypoint_index
                                        == len(impact_waypoints) - 1
                                        else None
                                    ),
                                )
                            )
                        repeat(
                            f"{prefix}_impact_wait",
                            impact_input_delay_ticks,
                        )
                    trace.append(
                        command(
                            f"{prefix}_impact",
                            main_x=main_x,
                            main_y=main_y,
                            digital_left=(
                                trigger_waypoint_index is None
                                and impact_x_hold_ticks == 0
                                and trigger == "left"
                            ),
                            digital_right=(
                                trigger_waypoint_index is None
                                and impact_x_hold_ticks == 0
                                and trigger == "right"
                            ),
                            jump=(
                                trigger_waypoint_index is None
                                and impact_x_hold_ticks == 0
                                and jump
                            ),
                        )
                    )
                    for (
                        segment_id,
                        segment_ticks,
                        segment_inputs,
                        conditional_edge,
                        record_cliff_wait_timers,
                        cliff_wait_timer_jump,
                        record_ledge_regrab_cooldowns,
                    ) in observe_segments:
                        segment_label = (
                            f"{prefix}_observe"
                            if raw_observe_segments is None
                            else f"{prefix}_observe_{segment_id}"
                        )
                        segment_commands = [
                            command(
                                segment_label,
                                **segment_inputs,
                            )
                            for _ in range(segment_ticks)
                        ]
                        if response_start_position is not None:
                            segment_commands[0]["fighter_x_override"] = float(
                                response_start_position[0]
                            )
                            segment_commands[0]["fighter_y_override"] = float(
                                response_start_position[1]
                            )
                            segment_commands[0]["fighter_position_state_reset"] = True
                            response_start_position = None
                        if response_zero_velocity:
                            segment_commands[0][
                                "fighter_self_velocity_x_override"
                            ] = 0.0
                            segment_commands[0][
                                "fighter_self_velocity_y_override"
                            ] = 0.0
                            segment_commands[0][
                                "fighter_knockback_velocity_x_override"
                            ] = 0.0
                            segment_commands[0][
                                "fighter_knockback_velocity_y_override"
                            ] = 0.0
                            response_zero_velocity = False
                        if raw_record_actions is not None:
                            recorded_actions = tuple(
                                str(action) for action in raw_record_actions
                            )
                            for segment_command in segment_commands:
                                segment_command["record_actions"] = (
                                    recorded_actions
                                )
                        if conditional_edge is not None:
                            source_edges = (
                                conditional_edge
                                if isinstance(conditional_edge, list)
                                else [conditional_edge]
                            )
                            edges = [
                                {
                                    **edge,
                                    "id": (
                                        f"{prefix}:{segment_id}"
                                        if len(source_edges) == 1
                                        else f"{prefix}:{segment_id}:{edge_index}"
                                    ),
                                }
                                for edge_index, edge in enumerate(source_edges)
                            ]
                            command_edges: object = (
                                edges[0] if len(edges) == 1 else tuple(edges)
                            )
                            for segment_command in segment_commands:
                                segment_command["conditional_edge"] = command_edges
                        if record_cliff_wait_timers is not None:
                            for segment_command in segment_commands:
                                segment_command["record_cliff_wait_timers"] = (
                                    record_cliff_wait_timers
                                )
                        if cliff_wait_timer_jump is not None:
                            for segment_command in segment_commands:
                                segment_command["cliff_wait_timer_jump"] = (
                                    cliff_wait_timer_jump
                                )
                        if record_ledge_regrab_cooldowns is not None:
                            for segment_command in segment_commands:
                                segment_command[
                                    "record_ledge_regrab_cooldowns"
                                ] = record_ledge_regrab_cooldowns
                        trace.extend(
                            segment_commands
                        )
                    if record_response_only:
                        for case_sample in trace[case_trace_start:]:
                            case_sample["record"] = str(
                                case_sample["label"]
                            ).startswith(f"{prefix}_observe")
                return trace

            raw_ground_cases = checkpoint_capture_plan.get(
                "ground_knockback_cases"
            )
            if raw_ground_cases is not None:
                if not isinstance(raw_ground_cases, list) or not raw_ground_cases:
                    raise ValueError(
                        "ground knockback checkpoint cases are invalid"
                    )
                case_ids: set[str] = set()
                for raw_case in raw_ground_cases:
                    if not isinstance(raw_case, dict):
                        raise ValueError(
                            "ground knockback case must be an object"
                        )
                    case_id = raw_case.get("id")
                    target_x = raw_case.get("target_x")
                    approach_ticks = raw_case.get("approach_ticks")
                    observe_ticks = raw_case.get("observe_ticks")
                    if (
                        not isinstance(case_id, str)
                        or not case_id
                        or case_id in case_ids
                        or not isinstance(target_x, (int, float))
                        or isinstance(target_x, bool)
                        or not isinstance(approach_ticks, int)
                        or isinstance(approach_ticks, bool)
                        or not 1 <= approach_ticks <= 30
                        or not isinstance(observe_ticks, int)
                        or isinstance(observe_ticks, bool)
                        or not 1 <= observe_ticks <= 120
                    ):
                        raise ValueError(
                            f"invalid ground knockback case {case_id!r}"
                        )
                    case_ids.add(case_id)
                    prefix = f"ground_knockback_{case_id}"
                    place = command(
                        f"{prefix}_place",
                        fighter_x_override=float(target_x),
                        fighter_facing_override=-1.0,
                        opponent_x_override=0.0,
                        opponent_facing_override=1.0,
                    )
                    trace.append({**place, "restore_before": True})
                    repeat(
                        f"{prefix}_settle",
                        8,
                        fighter_x_override=float(target_x),
                        fighter_facing_override=-1.0,
                        opponent_x_override=0.0,
                        opponent_facing_override=1.0,
                    )
                    repeat(
                        f"{prefix}_approach",
                        approach_ticks,
                        opponent_main_x=1.0,
                    )
                    trace.append(
                        command(
                            f"{prefix}_attack",
                            opponent_main_x=1.0,
                            opponent_attack=True,
                        )
                    )
                    repeat(f"{prefix}_observe", observe_ticks)
                return trace

            raw_cases = checkpoint_capture_plan.get("damage_response_cases")
            if not isinstance(raw_cases, list) or not raw_cases:
                raise ValueError("damage response checkpoint cases are required")
            record_input_window_only = checkpoint_capture_plan.get(
                "record_input_window_only", False
            )
            if not isinstance(record_input_window_only, bool):
                raise ValueError("record_input_window_only must be boolean")

            def case_sticks(
                raw: object,
            ) -> tuple[float, float, float, float]:
                if not isinstance(raw, dict):
                    raise ValueError("damage response input phase must be an object")
                main = raw.get("main", [0, 0])
                c_stick = raw.get("c_stick", [0, 0])
                if (
                    not isinstance(main, list)
                    or len(main) != 2
                    or not isinstance(c_stick, list)
                    or len(c_stick) != 2
                ):
                    raise ValueError("damage response stick pair is invalid")
                return (
                    controller_axis(main[0]),
                    controller_axis(main[1]),
                    controller_axis(c_stick[0]),
                    controller_axis(c_stick[1]),
                )

            case_ids: set[str] = set()
            for raw_case in raw_cases:
                if not isinstance(raw_case, dict):
                    raise ValueError("damage response case must be an object")
                case_id = raw_case.get("id")
                if (
                    not isinstance(case_id, str)
                    or not case_id
                    or case_id in case_ids
                ):
                    raise ValueError("damage response case id is invalid")
                case_ids.add(case_id)
                raw_pre_hit = raw_case.get("pre_hit", {})
                pre_hit_sequence = (
                    tuple(case_sticks(raw) for raw in raw_pre_hit)
                    if isinstance(raw_pre_hit, list)
                    else (case_sticks(raw_pre_hit),) * 2
                )
                setup = case_sticks(
                    raw_case.get(
                        "setup",
                        raw_pre_hit if isinstance(raw_pre_hit, dict) else {},
                    )
                )
                shield = raw_case.get("shield", False)
                if (
                    len(pre_hit_sequence) != 2
                    or not isinstance(shield, bool)
                ):
                    raise ValueError("damage response pre-hit/shield is invalid")
                raw_hitlag = raw_case.get("hitlag")
                if not isinstance(raw_hitlag, list) or len(raw_hitlag) != 3:
                    raise ValueError(
                        "damage response case must define three hitlag inputs"
                    )
                hitlag = tuple(case_sticks(raw) for raw in raw_hitlag)
                prefix = f"damage_response_{case_id}"
                case_trace_start = len(trace)
                trigger_inputs = {
                    "left_shoulder": 1.0 if shield else 0.0,
                    "digital_left": shield,
                }
                place = command(
                    f"{prefix}_place",
                    main_x=setup[0],
                    main_y=setup[1],
                    c_x=setup[2],
                    c_y=setup[3],
                    fighter_x_override=12.0,
                    fighter_facing_override=-1.0,
                    opponent_x_override=0.0,
                    opponent_facing_override=1.0,
                    **trigger_inputs,
                )
                trace.append({**place, "restore_before": True})
                repeat(
                    f"{prefix}_settle",
                    8,
                    main_x=setup[0],
                    main_y=setup[1],
                    c_x=setup[2],
                    c_y=setup[3],
                    fighter_x_override=12.0,
                    fighter_facing_override=-1.0,
                    opponent_x_override=0.0,
                    opponent_facing_override=1.0,
                    **trigger_inputs,
                )
                if shield:
                    repeat(
                        f"{prefix}_shield",
                        12,
                        main_x=setup[0],
                        main_y=setup[1],
                        c_x=setup[2],
                        c_y=setup[3],
                        **trigger_inputs,
                    )
                trace.append(
                    command(
                        f"{prefix}_jab",
                        main_x=setup[0],
                        main_y=setup[1],
                        c_x=setup[2],
                        c_y=setup[3],
                        opponent_attack=True,
                        fighter_x_override=12.0,
                        fighter_facing_override=-1.0,
                        opponent_x_override=0.0,
                        opponent_facing_override=1.0,
                        **trigger_inputs,
                    )
                )
                for pre_hit_index, sticks in enumerate(
                    pre_hit_sequence, start=1
                ):
                    trace.append(
                        command(
                            f"{prefix}_pre_hit_{pre_hit_index}"
                            if isinstance(raw_pre_hit, list)
                            else f"{prefix}_pre_hit",
                            main_x=sticks[0],
                            main_y=sticks[1],
                            c_x=sticks[2],
                            c_y=sticks[3],
                            fighter_x_override=12.0,
                            fighter_facing_override=-1.0,
                            opponent_x_override=0.0,
                            opponent_facing_override=1.0,
                            **trigger_inputs,
                        )
                    )
                for hitlag_index, sticks in enumerate(hitlag, start=1):
                    trace.append(
                        command(
                            f"{prefix}_hitlag_{hitlag_index}",
                            main_x=sticks[0],
                            main_y=sticks[1],
                            c_x=sticks[2],
                            c_y=sticks[3],
                            **trigger_inputs,
                        )
                    )
                repeat(f"{prefix}_observe", 8)
                if record_input_window_only:
                    retained_labels = {
                        f"{prefix}_pre_hit_1",
                        f"{prefix}_pre_hit_2",
                        f"{prefix}_hitlag_1",
                        f"{prefix}_hitlag_2",
                    }
                    for sample in trace[case_trace_start:]:
                        sample["record"] = sample["label"] in retained_labels
            return trace

        # Establish a deterministic close-range neutral state directly. The
        # previous walk-together setup could stop at player-push distance,
        # leaving Falcon Jab 1 outside the victim's hurt volume.
        trace.append(
            command(
                "damage_hit_place",
                fighter_x_override=12.0,
                fighter_facing_override=-1.0,
                opponent_x_override=0.0,
                opponent_facing_override=1.0,
            )
        )
        repeat("damage_hit_neutral_settle", 8)
        trace.append(command("damage_hit_jab", opponent_attack=True))
        repeat("damage_hit_recovery", 40)
        return trace

    if defense_state_only:
        repeat("defense_state_settle", 60)
        repeat(
            "defense_state_forward_roll_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_forward_roll_entry",
                main_x=1.0,
                left_shoulder=1.0,
                digital_left=True,
            )
        )
        repeat("defense_state_forward_roll_observe", 40)

        repeat(
            "defense_state_spot_dodge_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_spot_dodge_entry",
                main_y=0.0,
                left_shoulder=1.0,
                digital_left=True,
            )
        )
        repeat("defense_state_spot_dodge_observe", 35)

        repeat(
            "defense_state_backward_roll_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_backward_roll_entry",
                main_x=1.0,
                left_shoulder=1.0,
                digital_left=True,
            )
        )
        repeat("defense_state_backward_roll_observe", 45)

        repeat(
            "defense_state_air_dodge_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_air_dodge_jump",
                left_shoulder=1.0,
                digital_left=True,
                jump=True,
            )
        )
        repeat(
            "defense_state_air_dodge_jump_squat",
            5,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_air_dodge_entry",
                main_x=1.0,
                main_y=1.0,
                left_shoulder=1.0,
                right_shoulder=1.0,
                digital_left=True,
                digital_right=True,
            )
        )
        repeat("defense_state_air_dodge_observe", 62)

        # The earlier upward air dodge reaches LandingFallSpecial with zero
        # horizontal velocity, so it cannot qualify the state's ground-
        # friction callback.  A fresh down-left air dodge from jump height
        # lands with above-walk-speed horizontal momentum and exposes all ten
        # special-landing ticks without relying on a memory override.
        repeat(
            "defense_state_horizontal_landing_shield",
            10,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_horizontal_landing_jump",
                left_shoulder=1.0,
                digital_left=True,
                jump=True,
            )
        )
        repeat(
            "defense_state_horizontal_landing_jump_squat",
            5,
            left_shoulder=1.0,
            digital_left=True,
        )
        trace.append(
            command(
                "defense_state_horizontal_landing_entry",
                main_x=0.0,
                main_y=0.0,
                left_shoulder=1.0,
                right_shoulder=1.0,
                digital_left=True,
                digital_right=True,
            )
        )
        repeat("defense_state_horizontal_landing_observe", 20)
        return trace

    if platform_drop_ecb_only:
        repeat("platform_drop_ecb_settle", 60)
        trace.append(command("platform_drop_ecb_entry", main_y=0.0))
        # Wait through the controller/post-frame pipeline and the first Pass
        # frames before relocating. Once Pass is active, keeping the fighter
        # above the stage exposes the complete animation-driven ECB without a
        # floor collision ending the 30-frame source action early.
        repeat("platform_drop_ecb_arm", 6, main_y=0.0)
        for _ in range(40):
            trace.append(
                command(
                    "platform_drop_ecb_observe",
                    main_y=0.0,
                    fighter_y_override=500.0,
                )
            )
        repeat("platform_drop_ecb_recovery", 10)
        return trace

    if airborne_landing_only:
        repeat("airborne_landing_settle", 60)

        trace.append(
            command("airborne_landing_jump_backward_entry", main_x=0.3, jump=True)
        )
        repeat("airborne_landing_jump_backward_arm", 6, main_x=0.3)
        repeat("airborne_landing_jump_backward_observe", 100)
        repeat("airborne_landing_jump_backward_settle", 30)

        trace.append(
            command("airborne_landing_jump_aerial_forward_ground", jump=True)
        )
        repeat("airborne_landing_jump_aerial_forward_ground_arm", 8)
        trace.append(
            command("airborne_landing_jump_aerial_forward_entry", jump=True)
        )
        repeat("airborne_landing_jump_aerial_forward_observe", 120)
        repeat("airborne_landing_jump_aerial_forward_settle", 30)

        trace.append(
            command("airborne_landing_jump_aerial_backward_ground", jump=True)
        )
        repeat("airborne_landing_jump_aerial_backward_ground_arm", 8)
        trace.append(
            command(
                "airborne_landing_jump_aerial_backward_entry",
                main_x=0.3,
                jump=True,
            )
        )
        repeat("airborne_landing_jump_aerial_backward_arm", 3, main_x=0.3)
        repeat("airborne_landing_jump_aerial_backward_observe", 120)
        repeat("airborne_landing_jump_aerial_backward_settle", 30)
        return trace

    if airborne_ecb_only:
        def observe_airborne_ecb_route(label: str, count: int) -> None:
            # Relocate only after native action entry. This preserves the
            # source action and exposes its complete animated ECB without a
            # platform collision truncating later frames.
            for _ in range(count):
                trace.append(
                    command(
                        f"{label}_observe",
                        fighter_y_override=40.0,
                    )
                )

        reset_reference_airborne_route("jump_forward_ecb")
        trace.append(command("jump_forward_ecb_entry", jump=True))
        repeat("jump_forward_ecb_arm", 6)
        observe_airborne_ecb_route("jump_forward_ecb", 45)

        reset_reference_airborne_route("jump_backward_ecb")
        trace.append(command("jump_backward_ecb_entry", main_x=0.0, jump=True))
        repeat("jump_backward_ecb_arm", 6, main_x=0.0)
        observe_airborne_ecb_route("jump_backward_ecb", 60)

        reset_reference_airborne_route("jump_aerial_forward_ecb")
        trace.append(command("jump_aerial_forward_ecb_ground_entry", jump=True))
        repeat("jump_aerial_forward_ecb_ground_arm", 8)
        trace.append(command("jump_aerial_forward_ecb_entry", jump=True))
        repeat("jump_aerial_forward_ecb_arm", 3)
        observe_airborne_ecb_route("jump_aerial_forward_ecb", 60)

        reset_reference_airborne_route("jump_aerial_backward_ecb")
        trace.append(command("jump_aerial_backward_ecb_ground_entry", jump=True))
        repeat("jump_aerial_backward_ecb_ground_arm", 8)
        trace.append(
            command(
                "jump_aerial_backward_ecb_entry",
                main_x=0.0,
                jump=True,
            )
        )
        repeat("jump_aerial_backward_ecb_arm", 3, main_x=0.0)
        observe_airborne_ecb_route("jump_aerial_backward_ecb", 45)
        return trace

    if platform_only:
        repeat("platform_settle", 60)
        trace.append(command("platform_jump", jump=True))
        repeat("platform_jump_squat", 5)
        repeat("platform_landing_setup", 100)
        repeat("platform_landing_settle", 30)
        trace.append(command("platform_tap_down_entry", main_y=0.0))
        repeat("platform_tap_down_release", 30)
        repeat("platform_before_held_down", 30)
        trace.append(command("platform_held_down_entry", main_y=0.0))
        repeat("platform_held_down", 30, main_y=0.0)
        repeat("platform_held_down_recovery", 60)
        return trace

    extend("settle", [0.5] * 10)
    extend("held_dash_right", [1.0] * 25)
    extend("run_turnaround_left", [0.0] * 35)
    extend("held_dash_neutral", [0.5] * 35)
    extend("direct_dash_right", [1.0] * 4)
    extend("direct_dash_dance_left", [0.0] * 5)
    extend("direct_dash_dance_right", [1.0] * 5)
    extend("direct_dash_dance_left_2", [0.0] * 5)
    extend("neutral_brake", [0.5] * 30)
    extend("moving_dash_right", [1.0] * 5)
    extend("moving_neutral", [0.5] * 3)
    extend("moving_dash_left", [0.0] * 5)
    extend("moving_dash_right_return", [1.0] * 5)
    extend("settle_again", [0.5] * 30)
    extend("two_sample_dash", [0.65, 1.0, 1.0, 1.0, 1.0])
    extend("reverse_after_two_sample", [0.0] * 5)
    extend("settle_after_two_sample", [0.5] * 30)
    extend("pivot_dash_right", [1.0] * 4)
    extend("pivot_reverse_left", [0.0])
    extend("pivot_neutral", [0.5] * 15)
    extend("slow_sweep_walk", [0.62, 0.70, 1.0, 1.0, 1.0])
    extend("settle_after_walk", [0.5] * 20)

    # Shield routes deliberately retain analog shoulders and digital clicks as
    # separate inputs. Melee turns an analog shoulder above the common 0.30
    # dead zone into HSD_PAD_LR, while EscapeAir checks only a fresh digital
    # HSD_PAD_L/HSD_PAD_R click.
    repeat("run_for_full_shield", 25, main_x=1.0)
    repeat(
        "run_to_full_shield",
        12,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("release_full_shield", 20)
    repeat("settle_before_light_shield", 20)
    repeat("light_shield_half_press", 20, left_shoulder=0.5)
    repeat("release_light_shield", 20)
    repeat("below_analog_shield_dead_zone", 4, left_shoulder=0.29)
    repeat("settle_before_escapes", 20)
    repeat(
        "shield_before_forward_roll",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "forward_roll_entry",
            main_x=1.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("forward_roll_recovery", 40)
    repeat(
        "shield_before_spot_dodge",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "spot_dodge_entry",
            main_y=0.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("spot_dodge_recovery", 35)

    repeat(
        "shield_before_jump",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "jump_from_held_left_shield",
            left_shoulder=1.0,
            digital_left=True,
            jump=True,
        )
    )
    repeat(
        "held_left_during_jump_squat",
        5,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "fresh_right_air_dodge_while_left_held",
            main_x=1.0,
            main_y=0.0,
            left_shoulder=1.0,
            right_shoulder=1.0,
            digital_left=True,
            digital_right=True,
        )
    )
    repeat("air_dodge_progress", 12)
    repeat("air_dodge_landing_recovery", 50)

    trace.append(command("jump_for_analog_air_control", jump=True))
    repeat("jump_squat_for_analog_air_control", 5)
    repeat(
        "analog_light_shield_does_not_air_dodge",
        8,
        left_shoulder=0.5,
    )
    repeat("analog_air_control_landing", 70)

    repeat(
        "shield_before_backward_roll",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "backward_roll_entry",
            main_x=1.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("backward_roll_recovery", 45)

    repeat(
        "shield_before_cstick_roll",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat(
        "cstick_roll_buffer",
        4,
        c_x=0.0,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("cstick_roll_recovery", 40)

    repeat(
        "shield_before_cstick_spot_dodge",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat(
        "cstick_spot_dodge_buffer",
        4,
        c_y=0.0,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("cstick_spot_dodge_recovery", 36)

    repeat(
        "shield_before_cstick_jump",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat(
        "cstick_jump_buffer",
        4,
        c_y=1.0,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("cstick_jump_recovery", 32)

    # Aerial locomotion routes retain exact button-hold and stick timing so
    # short/full-hop selection, jump-squat momentum reversal, double-jump
    # velocity replacement, and fast-fall entry are executable-oracle gates.
    repeat("cstick_jump_landing", 60)
    repeat("recenter_after_defense", 15, main_x=0.0)
    repeat("recenter_after_defense_brake", 20)
    repeat("run_for_jump_squat_reverse", 20, main_x=1.0)
    trace.append(command("running_jump_start", main_x=1.0, jump=True))
    repeat("jump_squat_reverse", 5, main_x=0.0)
    repeat("reverse_jump_landing", 80)

    repeat("recenter_before_double_jump", 5, main_x=0.0)
    repeat("recenter_before_double_jump_brake", 20)

    trace.append(command("neutral_jump_for_double_jump", jump=True))
    repeat("neutral_jump_squat_for_double_jump", 5)
    repeat("first_jump_drift_left", 10, main_x=0.0)
    trace.append(command("neutral_stick_double_jump", jump=True))
    repeat("neutral_stick_double_jump_landing", 90)

    trace.append(command("short_hop_press", jump=True))
    repeat("short_hop_release", 80)

    trace.append(command("full_hop_press", jump=True))
    repeat("full_hop_hold", 5, jump=True)
    repeat("full_hop_landing", 95)

    trace.append(command("full_hop_for_fast_fall", jump=True))
    repeat("full_hop_hold_for_fast_fall", 5, jump=True)
    repeat("rise_before_fast_fall", 35)
    repeat("fast_fall_down_press", 4, main_y=0.0)
    repeat("fast_fall_landing", 65)

    # Basic grounded vertical-stick transitions are part of ordinary movement,
    # and must retain Melee's authored squat-start/hold/release sequencing.
    # Keep the stick fully down long enough to observe the complete entry and
    # held states, then release to neutral through the complete exit state.
    repeat("settle_before_crouch", 20)
    repeat("crouch_hold", 30, main_y=0.0)
    repeat("crouch_release", 20)

    # Common-data x90/x94 form a deliberate hysteresis band. Exact x90 does
    # not enter squat; moving just beyond it does. Exact x94 keeps SquatWait;
    # moving just above it starts SquatRv.
    # Dolphin's pipe takes an unsigned controller byte while Slippi reports the
    # in-game signed stick after its 80-unit normalization. Bytes 73/72 observe
    # as 0.15625/0.15; bytes 78/79 observe as 0.1875/0.19375.
    repeat("crouch_entry_boundary", 10, main_y=73.0 / 255.0)
    repeat("crouch_entry_beyond", 20, main_y=72.0 / 255.0)
    repeat("crouch_release_boundary", 10, main_y=78.0 / 255.0)
    repeat("crouch_release_beyond", 20, main_y=79.0 / 255.0)

    # Crouch IASA routes are state-specific in ftCo_Squat*, even when they
    # return to the ordinary movement vocabulary. Pin the common jump route
    # in all three states, SquatWait's direct dash, and SquatRv's direct walk.
    repeat("settle_before_crouch_start_jump", 10)
    repeat("crouch_start_before_jump", 2, main_y=0.0)
    trace.append(command("crouch_start_jump", main_y=0.0, jump=True))
    repeat("crouch_start_jump_landing", 80)

    repeat("settle_before_crouch_wait_jump", 10)
    repeat("crouch_wait_before_jump", 20, main_y=0.0)
    trace.append(command("crouch_wait_jump", main_y=0.0, jump=True))
    repeat("crouch_wait_jump_landing", 80)

    repeat("settle_before_crouch_end_jump", 10)
    repeat("crouch_end_before_jump", 20, main_y=0.0)
    trace.append(command("crouch_end_release", main_y=0.5))
    trace.append(command("crouch_end_jump", jump=True))
    repeat("crouch_end_jump_landing", 80)

    repeat("recenter_before_crouch_wait_dash", 18, main_x=0.0)
    repeat("recenter_before_crouch_wait_dash_brake", 35)
    repeat("settle_before_crouch_wait_dash", 10)
    repeat("crouch_wait_before_dash", 20, main_y=0.0)
    repeat("crouch_wait_dash", 20, main_x=1.0)
    repeat("crouch_wait_dash_recovery", 35)

    repeat("settle_before_crouch_end_walk", 10)
    repeat("crouch_wait_before_end_walk", 20, main_y=0.0)
    trace.append(command("crouch_end_before_walk"))
    repeat("crouch_end_walk", 20, main_x=0.75)
    repeat("crouch_end_walk_recovery", 30)

    # Guard input appears in every crouch-state IASA list. Use a neutral stick
    # on the guard frame so the trace isolates guard precedence from spot dodge
    # and platform-pass input.
    repeat("settle_before_crouch_start_guard", 10)
    repeat("crouch_start_before_guard", 2, main_y=0.0)
    repeat(
        "crouch_start_guard",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("crouch_start_guard_release", 20)

    repeat("settle_before_crouch_wait_guard", 10)
    repeat("crouch_wait_before_guard", 20, main_y=0.0)
    repeat(
        "crouch_wait_guard",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("crouch_wait_guard_release", 20)

    repeat("settle_before_crouch_end_guard", 10)
    repeat("crouch_end_before_guard", 20, main_y=0.0)
    trace.append(command("crouch_end_guard_release"))
    repeat(
        "crouch_end_guard",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("crouch_end_guard_recovery", 20)

    # Taunt is dispatched by ftCo_800DE9D8 from Squat, SquatWait, and
    # SquatRv. D-pad up is held for one scheduled sample only so each route
    # proves fresh-input eligibility without depending on input repetition.
    repeat("settle_before_crouch_start_taunt", 10)
    repeat("crouch_start_before_taunt", 2, main_y=0.0)
    trace.append(command("crouch_start_taunt", taunt=True))
    repeat("crouch_start_taunt_recovery", 110)

    repeat("settle_before_crouch_wait_taunt", 10)
    repeat("crouch_wait_before_taunt", 20, main_y=0.0)
    trace.append(command("crouch_wait_taunt", taunt=True))
    repeat("crouch_wait_taunt_recovery", 110)

    repeat("settle_before_crouch_end_taunt", 10)
    repeat("crouch_end_before_taunt", 20, main_y=0.0)
    trace.append(command("crouch_end_taunt_release"))
    trace.append(command("crouch_end_taunt", taunt=True))
    repeat("crouch_end_taunt_recovery", 110)

    # Core crouch IASA beyond movement/guard/taunt. Neutral A is eligible in
    # Squat, SquatWait, and SquatRv. Physical Z enters Catch from Squat but
    # must reveal its A-component fallback from SquatWait and SquatRv. Neutral B is
    # eligible during Squat; SquatWait and SquatRv list only the down-special
    # dispatcher, so a neutral B sample must not start Falcon Punch there.
    repeat("settle_before_crouch_start_attack", 10)
    repeat("crouch_start_before_attack", 2, main_y=0.0)
    trace.append(command("crouch_start_attack", attack=True))
    repeat("crouch_start_attack_recovery", 60)

    repeat("settle_before_crouch_wait_attack", 10)
    repeat("crouch_wait_before_attack", 20, main_y=0.0)
    trace.append(command("crouch_wait_attack", attack=True))
    repeat("crouch_wait_attack_recovery", 60)

    repeat("settle_before_crouch_end_attack", 10)
    repeat("crouch_end_before_attack", 20, main_y=0.0)
    trace.append(command("crouch_end_attack_release"))
    trace.append(command("crouch_end_attack", attack=True))
    repeat("crouch_end_attack_recovery", 60)

    repeat("settle_before_crouch_wait_neutral_special", 10)
    repeat("crouch_wait_before_neutral_special", 20, main_y=0.0)
    trace.append(command("crouch_wait_neutral_special", special=True))
    repeat("crouch_wait_neutral_special_recovery", 40)

    repeat("settle_before_crouch_end_neutral_special", 10)
    repeat("crouch_end_before_neutral_special", 20, main_y=0.0)
    trace.append(command("crouch_end_neutral_special_release"))
    trace.append(command("crouch_end_neutral_special", special=True))
    repeat("crouch_end_neutral_special_recovery", 40)

    repeat("settle_before_crouch_start_neutral_special", 10)
    repeat("crouch_start_before_neutral_special", 2, main_y=0.0)
    trace.append(command("crouch_start_neutral_special", special=True))
    repeat("crouch_start_neutral_special_recovery", 130)

    repeat("settle_before_crouch_start_grab", 10)
    repeat("crouch_start_before_grab", 2, main_y=0.0)
    trace.append(command("crouch_start_grab", grab=True))
    repeat("crouch_start_grab_recovery", 90)

    repeat("settle_before_crouch_wait_grab", 10)
    repeat("crouch_wait_before_grab", 20, main_y=0.0)
    trace.append(command("crouch_wait_grab", grab=True))
    repeat("crouch_wait_grab_recovery", 90)

    repeat("settle_before_crouch_end_grab", 10)
    repeat("crouch_end_before_grab", 20, main_y=0.0)
    trace.append(command("crouch_end_grab_release"))
    trace.append(command("crouch_end_grab", grab=True))
    repeat("crouch_end_grab_recovery", 90)

    # Turn's common IASA list also dispatches AppealS. Enter an ordinary
    # standing turn for one frame, then press D-pad up before the turn ends.
    repeat("settle_before_standing_turn_taunt", 10)
    trace.append(command("standing_turn_before_taunt", main_x=0.0))
    trace.append(command("standing_turn_taunt", taunt=True))
    repeat("standing_turn_taunt_recovery", 110)

    # Falcon's normal-landing IASA becomes available once the displayed
    # animation reaches the four-frame common landing-lag value. A short hop
    # reaches Landing frame 1 after 35 scheduled samples, so 38 neutral
    # samples leave frame 4 visible immediately before this fresh taunt.
    repeat("settle_before_landing_taunt", 10)
    trace.append(command("landing_taunt_jump", jump=True))
    repeat("landing_taunt_setup", 38)
    trace.append(command("landing_taunt", taunt=True))
    repeat("landing_taunt_recovery", 110)

    # Systematically qualify more entries from ftCo_Landing_IASA on the same
    # first legal displayed-frame boundary. Jump, dash, guard (the decomp's
    # ftCo_80091A4C call), crouch, turn, and walk all appear in the common IASA
    # list; character attacks, specials, and grabs are outside this shared
    # movement trace.
    repeat("settle_before_landing_jump", 10)
    trace.append(command("landing_jump_jump", jump=True))
    repeat("landing_jump_setup", 38)
    trace.append(command("landing_jump", jump=True))
    repeat("landing_jump_recovery", 110)

    repeat("settle_before_landing_dash", 10)
    trace.append(command("landing_dash_jump", jump=True))
    repeat("landing_dash_setup", 38)
    trace.append(command("landing_dash", main_x=1.0))
    repeat("landing_dash_recovery", 110)

    repeat("settle_before_landing_guard", 10)
    trace.append(command("landing_guard_jump", jump=True))
    repeat("landing_guard_setup", 38)
    trace.append(
        command(
            "landing_guard",
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat(
        "landing_guard_held",
        12,
        left_shoulder=1.0,
        digital_left=True,
    )
    repeat("landing_guard_recovery", 110)

    repeat("settle_before_landing_walk", 10)
    trace.append(command("landing_walk_jump", jump=True))
    repeat("landing_walk_setup", 38)
    trace.append(command("landing_walk", main_x=0.75))
    repeat("landing_walk_recovery", 110)

    repeat("settle_before_landing_crouch", 10)
    trace.append(command("landing_crouch_jump", jump=True))
    repeat("landing_crouch_setup", 38)
    trace.append(command("landing_crouch", main_y=0.0))
    repeat("landing_crouch_recovery", 110)

    # SquatWait_CheckInput is gated to the one-frame window ending at
    # normal_landing_lag + frame_speed_mul. Down one displayed frame later
    # must leave Landing active rather than replaying the ordinary Squat entry.
    repeat("settle_before_landing_late_crouch", 10)
    trace.append(command("landing_late_crouch_jump", jump=True))
    repeat("landing_late_crouch_setup", 39)
    trace.append(command("landing_late_crouch", main_y=0.0))
    repeat("landing_late_crouch_recovery", 110)

    repeat("settle_before_landing_turn", 10)
    trace.append(command("landing_turn_jump", jump=True))
    repeat("landing_turn_setup", 38)
    trace.append(command("landing_turn", main_x=0.25))
    repeat("landing_turn_recovery", 110)

    # ftCo_Jump_GetInput checks a fresh main-stick up tilt before X/Y. Hold
    # through Falcon's four-frame KneeBend for the full-hop route, then repeat
    # with a one-sample tap to pin the stick-release short-hop path.
    repeat("settle_before_ground_tap_full_hop", 10)
    repeat("ground_tap_full_hop", 5, main_y=1.0)
    repeat("ground_tap_full_hop_recovery", 110)

    repeat("settle_before_ground_tap_short_hop", 10)
    trace.append(command("ground_tap_short_hop", main_y=1.0))
    repeat("ground_tap_short_hop_recovery", 110)

    repeat("settle_before_air_tap_jump", 10)
    trace.append(command("air_tap_jump_first_jump", jump=True))
    repeat("air_tap_jump_squat", 5)
    repeat("air_tap_jump_before_second", 10)
    trace.append(command("air_tap_jump", main_y=1.0))
    repeat("air_tap_jump_recovery", 90)

    repeat("settle_before_landing_tap_jump", 10)
    trace.append(command("landing_tap_jump_first_jump", jump=True))
    repeat("landing_tap_jump_setup", 38)
    trace.append(command("landing_tap_jump", main_y=1.0))
    repeat("landing_tap_jump_recovery", 110)

    repeat("settle_before_shield_tap_jump", 10)
    repeat(
        "shield_tap_jump_setup",
        10,
        left_shoulder=1.0,
        digital_left=True,
    )
    trace.append(
        command(
            "shield_tap_jump",
            main_y=1.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("shield_tap_jump_recovery", 110)

    # Common-data boundary and age controls. Controller-pipe values 0.83 and
    # 0.835 normalize just below and just above the 0.6625 tap-jump threshold.
    # The slow sweep ages four samples after first vertical tilt and must not
    # jump; the two-sample route reaches the same terminal value in-window.
    repeat("settle_before_tap_jump_below_threshold", 10)
    trace.append(command("tap_jump_below_threshold", main_y=0.83))
    repeat("tap_jump_below_threshold_recovery", 110)

    repeat("settle_before_tap_jump_above_threshold", 10)
    trace.append(command("tap_jump_above_threshold", main_y=0.835))
    repeat("tap_jump_above_threshold_recovery", 110)

    repeat("settle_before_tap_jump_slow_sweep", 10)
    for y in (0.63, 0.68, 0.74, 0.79, 0.835):
        trace.append(command("tap_jump_slow_sweep", main_y=y))
    repeat("tap_jump_slow_sweep_recovery", 110)

    repeat("settle_before_tap_jump_two_sample", 10)
    for y in (0.63, 0.835):
        trace.append(command("tap_jump_two_sample", main_y=y))
    repeat("tap_jump_two_sample_recovery", 110)

    # RunBrake's common IASA is intentionally narrow: jump and crouch are
    # immediate, while guard and taunt are absent. Each route enters terminal
    # run, releases to RunBrake frame 1, then applies one fresh candidate input
    # on the following sample.
    # Keep the three grounded routes away from P2, then put the airborne route
    # last and end before landing. This prevents the still-unqualified player
    # push interaction from contaminating the RunBrake IASA comparison.
    repeat("recenter_before_run_brake_crouch", 25, main_x=0.0)
    repeat("run_brake_crouch_settle", 30)
    repeat("run_brake_crouch_run", 25, main_x=1.0)
    trace.append(command("run_brake_crouch_entry"))
    trace.append(command("run_brake_crouch", main_y=0.0))
    repeat("run_brake_crouch_recovery", 90)

    repeat("recenter_before_run_brake_guard", 25, main_x=0.0)
    repeat("run_brake_guard_settle", 30)
    repeat("run_brake_guard_run", 25, main_x=1.0)
    trace.append(command("run_brake_guard_entry"))
    trace.append(
        command(
            "run_brake_guard",
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("run_brake_guard_recovery", 90)

    repeat("recenter_before_run_brake_spot_dodge", 25, main_x=0.0)
    repeat("run_brake_spot_dodge_settle", 30)
    repeat("run_brake_spot_dodge_run", 25, main_x=1.0)
    trace.append(command("run_brake_spot_dodge_entry"))
    trace.append(
        command(
            "run_brake_spot_dodge",
            main_y=0.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("run_brake_spot_dodge_recovery", 90)

    # The preceding shield-plus-down route crouches and therefore finishes its
    # recovery 13.5 units earlier than a rejected input. Nineteen leftward frames
    # restore the same safe setup reached by the ordinary 25-frame recenter.
    repeat("recenter_before_run_brake_cstick_roll", 19, main_x=0.0)
    repeat("run_brake_cstick_roll_settle", 30)
    repeat("run_brake_cstick_roll_run", 25, main_x=1.0)
    trace.append(command("run_brake_cstick_roll_entry"))
    trace.append(
        command(
            "run_brake_cstick_roll",
            c_x=1.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("run_brake_cstick_roll_recovery", 90)

    repeat("recenter_before_run_brake_cstick_spot", 25, main_x=0.0)
    repeat("run_brake_cstick_spot_settle", 30)
    repeat("run_brake_cstick_spot_run", 25, main_x=1.0)
    trace.append(command("run_brake_cstick_spot_entry"))
    trace.append(
        command(
            "run_brake_cstick_spot",
            c_y=0.0,
            left_shoulder=1.0,
            digital_left=True,
        )
    )
    repeat("run_brake_cstick_spot_recovery", 90)

    repeat("recenter_before_run_brake_taunt", 25, main_x=0.0)
    repeat("run_brake_taunt_settle", 30)
    repeat("run_brake_taunt_run", 25, main_x=1.0)
    trace.append(command("run_brake_taunt_entry"))
    trace.append(command("run_brake_taunt", taunt=True))
    repeat("run_brake_taunt_recovery", 90)

    repeat("recenter_before_run_brake_attack", 25, main_x=0.0)
    repeat("run_brake_attack_settle", 30)
    repeat("run_brake_attack_run", 25, main_x=1.0)
    trace.append(command("run_brake_attack_entry"))
    trace.append(command("run_brake_attack", attack=True))
    repeat("run_brake_attack_recovery", 90)

    repeat("recenter_before_run_brake_grab", 25, main_x=0.0)
    repeat("run_brake_grab_settle", 30)
    repeat("run_brake_grab_run", 25, main_x=1.0)
    trace.append(command("run_brake_grab_entry"))
    trace.append(command("run_brake_grab", grab=True))
    repeat("run_brake_grab_recovery", 90)

    repeat("recenter_before_run_brake_special", 25, main_x=0.0)
    repeat("run_brake_special_settle", 30)
    repeat("run_brake_special_run", 25, main_x=1.0)
    trace.append(command("run_brake_special_entry"))
    trace.append(command("run_brake_special", special=True))
    repeat("run_brake_special_recovery", 90)

    # RunBrake's command-variable gate eventually admits held opposite stick
    # into TurnRun. Hold through the full animation so the executable reveals
    # the first legal displayed frame and the resumed TurnRun animation frame.
    repeat("recenter_before_run_brake_reverse", 25, main_x=0.0)
    repeat("run_brake_reverse_settle", 30)
    repeat("run_brake_reverse_run", 25, main_x=1.0)
    trace.append(command("run_brake_reverse_entry"))
    repeat("run_brake_reverse_hold", 35, main_x=0.0)
    repeat("run_brake_reverse_recovery", 90)

    # TurnRun's neutral recovery already finishes at center-left. Settle there
    # instead of applying the ordinary leftward recenter, which would leave FD.
    repeat("recenter_before_run_brake_jump", 30)
    repeat("run_brake_jump_run", 25, main_x=1.0)
    trace.append(command("run_brake_jump_entry"))
    trace.append(command("run_brake_jump", jump=True))
    repeat("run_brake_jump_recovery", 12)

    # Keep character-specific Falcon Kick bodies at the end so their motion
    # cannot alter the preconditions of later shared-movement routes. Each
    # case creates space on the left, turns back toward stage center, and then
    # qualifies only the common down-special interrupt entry.
    repeat("settle_before_down_special_slice", 100)
    repeat("recenter_before_crouch_start_down_special", 25, main_x=0.0)
    repeat("settle_before_crouch_start_down_special", 30)
    trace.append(
        command(
            "face_right_before_crouch_start_down_special",
            main_x=0.65,
        )
    )
    repeat("face_right_settle_before_crouch_start_down_special", 15)
    repeat("crouch_start_before_down_special", 2, main_y=0.0)
    trace.append(command("crouch_start_down_special", main_y=0.0, special=True))
    repeat("crouch_start_down_special_recovery", 100)

    repeat("recenter_before_crouch_wait_down_special", 25, main_x=0.0)
    repeat("settle_before_crouch_wait_down_special", 30)
    trace.append(
        command(
            "face_right_before_crouch_wait_down_special",
            main_x=0.65,
        )
    )
    repeat("face_right_settle_before_crouch_wait_down_special", 15)
    repeat("crouch_wait_before_down_special", 20, main_y=0.0)
    trace.append(command("crouch_wait_down_special", main_y=0.0, special=True))
    repeat("crouch_wait_down_special_recovery", 100)

    repeat("recenter_before_crouch_end_down_special", 25, main_x=0.0)
    repeat("settle_before_crouch_end_down_special", 30)
    trace.append(
        command(
            "face_right_before_crouch_end_down_special",
            main_x=0.65,
        )
    )
    repeat("face_right_settle_before_crouch_end_down_special", 15)
    repeat("crouch_end_before_down_special", 20, main_y=0.0)
    trace.append(command("crouch_end_down_special_release"))
    trace.append(command("crouch_end_down_special", main_y=0.0, special=True))
    repeat("crouch_end_down_special_recovery", 100)
    return trace


def read_shield_memory_probe(memory_engine: object) -> dict[str, object]:
    """Read Falcon's live guard state and shield-joint world transform."""

    player_slot = 0x80453080
    transformed = memory_engine.read_byte(player_slot + 0x0C)
    fighter_gobj = memory_engine.read_word(player_slot + 0xB0 + 4 * transformed)
    fighter = memory_engine.read_word(fighter_gobj + 0x2C)
    shield_joint = memory_engine.read_word(fighter + 0x19C0)
    matrix = [
        memory_engine.read_float(shield_joint + 0x44 + 4 * index) for index in range(12)
    ]
    return {
        "fighter_address": fighter,
        "shield_joint_address": shield_joint,
        "guard_magnitude": memory_engine.read_float(fighter + 0x2344),
        "guard_angle_degrees": memory_engine.read_float(fighter + 0x2348),
        "shield_health": memory_engine.read_float(fighter + 0x1998),
        "lightshield_amount": memory_engine.read_float(fighter + 0x199C),
        "shield_radius": memory_engine.read_float(fighter + 0x19E0),
        "initial_shield_size": memory_engine.read_float(fighter + 0x1A0),
        "fighter_scale": [
            memory_engine.read_float(fighter + 0x34 + 4 * index) for index in range(3)
        ],
        "fighter_position": [
            memory_engine.read_float(fighter + 0xB0 + 4 * index) for index in range(3)
        ],
        "shield_position": [
            memory_engine.read_float(fighter + 0x19C8 + 4 * index) for index in range(3)
        ],
        "shield_joint_scale": [
            memory_engine.read_float(shield_joint + 0x2C + 4 * index)
            for index in range(3)
        ],
        "shield_joint_translate": [
            memory_engine.read_float(shield_joint + 0x38 + 4 * index)
            for index in range(3)
        ],
        "shield_joint_matrix": matrix,
    }


def read_damage_memory_probe(memory_engine: object) -> dict[str, object]:
    """Read Falcon's live damage state and the common damage constants."""

    player_slot = 0x80453080
    transformed = memory_engine.read_byte(player_slot + 0x0C)
    fighter_gobj = memory_engine.read_word(player_slot + 0xB0 + 4 * transformed)
    fighter = memory_engine.read_word(fighter_gobj + 0x2C)
    common = memory_engine.read_word(0x804D6554)
    source_gobj = memory_engine.read_word(fighter + 0x1868)
    source_fighter = memory_engine.read_word(source_gobj + 0x2C) if source_gobj else 0
    source_hitboxes = []
    if source_fighter:
        for index in range(4):
            hitbox = source_fighter + 0x914 + index * 0x138
            source_hitboxes.append(
                {
                    "state": memory_engine.read_word(hitbox),
                    "hit_id": memory_engine.read_word(hitbox + 0x04),
                    "damage_count": memory_engine.read_word(hitbox + 0x08),
                    "damage": memory_engine.read_float(hitbox + 0x0C),
                    "angle": memory_engine.read_word(hitbox + 0x20),
                    "knockback_growth": memory_engine.read_word(hitbox + 0x24),
                    "weight_set_knockback": memory_engine.read_word(hitbox + 0x28),
                    "base_knockback": memory_engine.read_word(hitbox + 0x2C),
                }
            )
    common_float_offsets = {
        "weight_scale": 0x0F4,
        "weight_base": 0x0F8,
        "launch_velocity_scale": 0x100,
        "minimum_knockback": 0x104,
        "maximum_knockback": 0x108,
        "damage_term_a": 0x110,
        "damage_term_b": 0x114,
        "weight_set_damage": 0x118,
        "weight_term_scale": 0x11C,
        "base_term": 0x120,
        "crouch_knockback_scale": 0x124,
        "collision_knockback_threshold": 0x12C,
        "sakurai_air_angle_radians": 0x144,
        "sakurai_max_ground_angle": 0x148,
        "sakurai_low_knockback": 0x14C,
        "sakurai_high_knockback": 0x150,
        "hitstun_scale": 0x154,
        "air_motion_knockback_scale": 0x190,
        "maximum_hitlag": 0x194,
        "hitlag_damage_scale": 0x198,
        "hitlag_base": 0x19C,
        "crouch_hitlag_scale": 0x1A0,
        "di_max_angle_degrees": 0x1A8,
        "v_cancel_scale": 0x1AC,
        "ground_knockback_friction_scale": 0x200,
        "air_knockback_decay": 0x204,
        "sdi_minimum_stick_magnitude": 0x4B0,
        "sdi_position_scale": 0x4B8,
        "asdi_position_scale": 0x4BC,
    }
    return {
        "fighter_address": fighter,
        "common_data_address": common,
        "source_gobj_address": source_gobj,
        "source_fighter_address": source_fighter,
        "source_hitboxes": source_hitboxes,
        "fighter_weight": memory_engine.read_float(fighter + 0x198),
        "knockback_velocity": [
            memory_engine.read_float(fighter + 0x8C + 4 * index) for index in range(3)
        ],
        "ground_knockback_velocity": memory_engine.read_float(fighter + 0xF0),
        "damage_percent": memory_engine.read_float(fighter + 0x1830),
        "damage_this_hit": memory_engine.read_float(fighter + 0x1838),
        "knockback_angle": memory_engine.read_word(fighter + 0x1848),
        "knockback_applied": memory_engine.read_float(fighter + 0x1850),
        "knockback_magnitude": memory_engine.read_float(fighter + 0x18A4),
        "knockback_applied_latched": memory_engine.read_float(fighter + 0x18A8),
        "hitlag_frames": memory_engine.read_float(fighter + 0x195C),
        "common": {
            name: memory_engine.read_float(common + offset)
            for name, offset in common_float_offsets.items()
        },
        "sdi_stick_window": memory_engine.read_word(common + 0x4B4),
    }


def read_input_memory_probe(
    memory_engine: object,
    *,
    schema: int = 1,
    ucf_pad_hook_target: int | None = None,
) -> dict[str, int | float]:
    """Read source-owned controller history and exact UCF input state."""

    if schema not in {1, 2}:
        raise ValueError(f"unsupported input-memory probe schema: {schema}")
    fighter = read_fighter_address(memory_engine, 0)
    fighter_input = BigEndianSnapshot.read(
        memory_engine,
        fighter + 0x618,
        0x675 - 0x618,
    )
    result: dict[str, int | float] = {
        "tilt_x_age": fighter_input.u8(fighter + 0x670),
        "tilt_y_age": fighter_input.u8(fighter + 0x671),
        "input_timer_counter": fighter_input.u8(fighter + 0x672),
    }
    if schema == 1:
        return result
    if ucf_pad_hook_target is None:
        raise RuntimeError("input-memory probe schema 2 requires the UCF pad hook")

    port = fighter_input.u8(fighter + 0x618)
    if not 0 <= port < 4:
        raise RuntimeError(f"invalid fighter controller port: {port}")
    game_status_address = 0x804C21CC + port * 0x44
    game_status = BigEndianSnapshot.read(
        memory_engine,
        game_status_address,
        0x44,
    )
    common = int(memory_engine.read_word(0x804D6554))
    if not 0x80000000 <= common < 0x81800000:
        raise RuntimeError(f"invalid Fighter common-data pointer: 0x{common:08x}")
    deadzone_x = float(memory_engine.read_float(common))
    deadzone_y = float(memory_engine.read_float(common + 4))
    pad_main_x = game_status.f32(game_status_address + 0x20)
    pad_main_y = game_status.f32(game_status_address + 0x24)
    pad_c_x = game_status.f32(game_status_address + 0x28)
    pad_c_y = game_status.f32(game_status_address + 0x2C)

    def apply_fighter_deadzone(value: float, threshold: float) -> float:
        return 0.0 if abs(value) <= threshold else value

    result.update(
        {
            "ucf_tilt_x_age": fighter_input.u8(fighter + 0x673),
            "ucf_tilt_y_age": fighter_input.u8(fighter + 0x674),
            "fighter_processed_main_x": fighter_input.f32(fighter + 0x620),
            "fighter_processed_main_y": fighter_input.f32(fighter + 0x624),
            "fighter_previous_main_x": fighter_input.f32(fighter + 0x628),
            "fighter_previous_main_y": fighter_input.f32(fighter + 0x62C),
            "fighter_processed_c_x": fighter_input.f32(fighter + 0x638),
            "fighter_processed_c_y": fighter_input.f32(fighter + 0x63C),
            "pad_processed_main_x": pad_main_x,
            "pad_processed_main_y": pad_main_y,
            "pad_processed_c_x": pad_c_x,
            "pad_processed_c_y": pad_c_y,
            "fighter_pre_ucf_main_x": apply_fighter_deadzone(
                pad_main_x, deadzone_x
            ),
            "fighter_pre_ucf_main_y": apply_fighter_deadzone(
                pad_main_y, deadzone_y
            ),
            "fighter_pre_ucf_c_x": apply_fighter_deadzone(pad_c_x, deadzone_x),
            "fighter_pre_ucf_c_y": apply_fighter_deadzone(pad_c_y, deadzone_y),
            "fighter_axis_deadzone_x": deadzone_x,
            "fighter_axis_deadzone_y": deadzone_y,
            "pad_port": port,
            "ucf_pad_buffer_count": int(
                memory_engine.read_byte(
                    ucf_pad_hook_target + 4 + port * 12 + 9
                )
            ),
        }
    )
    return result


class BigEndianSnapshot:
    """One contiguous PowerPC memory observation with typed zero-I/O reads."""

    __slots__ = ("base", "data")

    def __init__(self, base: int, data: bytes) -> None:
        self.base = base
        self.data = data

    @classmethod
    def read(
        cls, memory_engine: object, base: int, size: int
    ) -> BigEndianSnapshot:
        return cls(base, bytes(memory_engine.read_bytes(base, size)))

    def offset(self, address: int, size: int) -> int:
        offset = address - self.base
        if offset < 0 or offset + size > len(self.data):
            raise ValueError(
                "snapshot access outside observed span: "
                f"base=0x{self.base:08x} size=0x{len(self.data):x} "
                f"address=0x{address:08x} access_size=0x{size:x}"
            )
        return offset

    def u8(self, address: int) -> int:
        return self.data[self.offset(address, 1)]

    def u16(self, address: int) -> int:
        return struct.unpack_from(">H", self.data, self.offset(address, 2))[0]

    def i16(self, address: int) -> int:
        return struct.unpack_from(">h", self.data, self.offset(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack_from(">I", self.data, self.offset(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack_from(">f", self.data, self.offset(address, 4))[0]

    def f32_vector(self, address: int, count: int) -> list[float]:
        return list(
            struct.unpack_from(
                f">{count}f",
                self.data,
                self.offset(address, 4 * count),
            )
        )

    def bytes_at(self, address: int, size: int) -> bytes:
        offset = self.offset(address, size)
        return self.data[offset : offset + size]


class LinuxDolphinSharedMemory:
    """Zero-syscall MEM1 reads with writes delegated to the hooked DME."""

    MEM1_BASE = 0x80000000
    MEM1_SIZE = 0x02000000

    def __init__(self, delegate: object, dolphin_pid: int) -> None:
        maps = Path(f"/proc/{dolphin_pid}/maps").read_text(encoding="ascii")
        shared_path = None
        for line in maps.splitlines():
            fields = line.split()
            if len(fields) < 6 or int(fields[2], 16) != 0:
                continue
            start, end = (int(value, 16) for value in fields[0].split("-"))
            mapped_name = next(
                (
                    field
                    for field in fields[5:]
                    if field.startswith("/dev/shm/dolphin")
                ),
                None,
            )
            if (
                end - start == self.MEM1_SIZE
                and mapped_name is not None
            ):
                mapped_path = Path(mapped_name)
                if "(deleted)" not in fields:
                    shared_path = mapped_path
                    break
                for descriptor in Path(f"/proc/{dolphin_pid}/fd").iterdir():
                    try:
                        if os.readlink(descriptor).startswith(str(mapped_path)):
                            shared_path = descriptor
                            break
                    except OSError:
                        continue
                break
        if shared_path is None:
            candidates = [
                line for line in maps.splitlines() if "/dev/shm/dolphin" in line
            ]
            raise RuntimeError(
                "Dolphin MEM1 shared-memory mapping was not found: "
                + " | ".join(candidates)
            )
        self._delegate = delegate
        self._source = shared_path.open("rb")
        self._memory = mmap.mmap(
            self._source.fileno(),
            self.MEM1_SIZE,
            access=mmap.ACCESS_READ,
        )

    def read_bytes(self, address: int, size: int) -> bytes:
        offset = address - self.MEM1_BASE
        if offset < 0 or offset + size > self.MEM1_SIZE:
            return bytes(self._delegate.read_bytes(address, size))
        return self._memory[offset : offset + size]

    def read_byte(self, address: int) -> int:
        return self.read_bytes(address, 1)[0]

    def read_word(self, address: int) -> int:
        return struct.unpack(">I", self.read_bytes(address, 4))[0]

    def read_float(self, address: int) -> float:
        return struct.unpack(">f", self.read_bytes(address, 4))[0]

    def read_double(self, address: int) -> float:
        return struct.unpack(">d", self.read_bytes(address, 8))[0]

    def un_hook(self) -> None:
        self._memory.close()
        self._source.close()
        self._delegate.un_hook()

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


def read_fighter_address(memory_engine: object, player_index: int) -> int:
    """Resolve one of Melee's six StaticPlayer slots to its live Fighter."""

    def require_mem1_pointer(value: int, label: str) -> int:
        if not 0x80000000 <= value < 0x81800000:
            raise RuntimeError(
                f"invalid {label} MEM1 pointer for player {player_index + 1}: "
                f"0x{value:08x}"
            )
        return value

    static_player_stride = 0xE90
    player_slot = 0x80453080 + player_index * static_player_stride
    player = BigEndianSnapshot.read(memory_engine, player_slot, 0xC0)
    transformed = player.u8(player_slot + 0x0C)
    fighter_gobj = require_mem1_pointer(
        player.u32(player_slot + 0xB0 + 4 * transformed),
        "fighter GObj",
    )
    gobj = BigEndianSnapshot.read(memory_engine, fighter_gobj, 0x30)
    return require_mem1_pointer(
        gobj.u32(fighter_gobj + 0x2C),
        "fighter data",
    )


def read_fighter_hurt_capsules(
    memory_engine: object,
    fighter: int,
    fighter_snapshot: BigEndianSnapshot,
) -> list[dict[str, object]]:
    """Read live pose-transformed FighterHurtCapsule values."""

    def transform(matrix: list[float], value: list[float]) -> list[float]:
        return [
            matrix[row * 4] * value[0]
            + matrix[row * 4 + 1] * value[1]
            + matrix[row * 4 + 2] * value[2]
            + matrix[row * 4 + 3]
            for row in range(3)
        ]

    hurtboxes = []
    bone_matrices: dict[int, list[float]] = {}
    hurtbox_count = fighter_snapshot.u8(fighter + 0x119E)
    if hurtbox_count > 15:
        raise RuntimeError(f"invalid Fighter hurt-capsule count: {hurtbox_count}")
    for index in range(hurtbox_count):
        hurtbox = fighter + 0x11A0 + index * 0x4C
        bone = fighter_snapshot.u32(hurtbox + 0x20)
        offset_a = fighter_snapshot.f32_vector(hurtbox + 0x04, 3)
        offset_b = fighter_snapshot.f32_vector(hurtbox + 0x10, 3)
        bone_matrix = bone_matrices.get(bone)
        if bone_matrix is None:
            matrix_address = bone + 0x44
            bone_matrix = BigEndianSnapshot.read(
                memory_engine, matrix_address, 12 * 4
            ).f32_vector(matrix_address, 12)
            bone_matrices[bone] = bone_matrix
        hurtboxes.append(
            {
                "state": fighter_snapshot.u32(hurtbox),
                "state_bytes": fighter_snapshot.bytes_at(hurtbox, 4).hex(),
                "radius": fighter_snapshot.f32(hurtbox + 0x1C),
                "offset_a": offset_a,
                "offset_b": offset_b,
                "position_a": transform(bone_matrix, offset_a),
                "position_b": transform(bone_matrix, offset_b),
                "collision_position_a": fighter_snapshot.f32_vector(
                    hurtbox + 0x28, 3
                ),
                "collision_position_b": fighter_snapshot.f32_vector(
                    hurtbox + 0x34, 3
                ),
                "bone_index": fighter_snapshot.u32(hurtbox + 0x40),
                "height": fighter_snapshot.u32(hurtbox + 0x44),
                "grabbable": fighter_snapshot.u32(hurtbox + 0x48),
            }
        )
    return hurtboxes


def read_jobj_world_translation(
    memory_engine: object, jobj: int
) -> list[float]:
    """Read the translation column of one live HSD_JObj world matrix."""

    if not 0x80000000 <= jobj < 0x81800000:
        raise RuntimeError(f"invalid HSD_JObj MEM1 pointer: 0x{jobj:08x}")
    snapshot = BigEndianSnapshot.read(memory_engine, jobj, 0x74)
    return [
        snapshot.f32(jobj + 0x50),
        snapshot.f32(jobj + 0x60),
        snapshot.f32(jobj + 0x70),
    ]


def read_jobj_pose(memory_engine: object, jobj: int) -> dict[str, object]:
    """Read one live HSD_JObj's local SRT and evaluated world matrix."""

    if not 0x80000000 <= jobj < 0x81800000:
        raise RuntimeError(f"invalid HSD_JObj MEM1 pointer: 0x{jobj:08x}")
    snapshot = BigEndianSnapshot.read(memory_engine, jobj, 0x74)
    return {
        "flags": snapshot.u32(jobj + 0x14),
        "rotation": snapshot.f32_vector(jobj + 0x1C, 4),
        "scale": snapshot.f32_vector(jobj + 0x2C, 3),
        "translation": snapshot.f32_vector(jobj + 0x38, 3),
        "world_matrix": snapshot.f32_vector(jobj + 0x44, 12),
    }


def read_guard_target_joint_tree(memory_engine: object) -> dict[str, object]:
    """Read the static local-pose tree used by common GuardOn blending.

    ftCo_80091E78 blends the fighter's current joints toward
    ``((HSD_Joint **) fp->ft_data->x20->x0)[2]``.  Reading that descriptor
    tree directly keeps predecessor-dependent GuardOn imports independent of
    whatever live pose happened to enter shield in a particular capture.
    """

    fighter = read_fighter_address(memory_engine, 0)
    fighter_data = memory_engine.read_word(fighter + 0x10C)
    guard_pose_table = memory_engine.read_word(fighter_data + 0x20)
    joint_roots = memory_engine.read_word(guard_pose_table)
    root = memory_engine.read_word(joint_roots + 2 * 4)
    for name, address in (
        ("fighter_data", fighter_data),
        ("guard_pose_table", guard_pose_table),
        ("joint_roots", joint_roots),
        ("root", root),
    ):
        if not 0x80000000 <= address < 0x81800000:
            raise RuntimeError(
                f"invalid GuardOn {name} MEM1 pointer: 0x{address:08x}"
            )

    rows: list[dict[str, object]] = []
    visited: set[int] = set()

    dynamic_parts_table = memory_engine.read_word(0x804D6540)
    fighter_dynamic_parts = memory_engine.read_word(dynamic_parts_table + 2 * 4)
    dynamic_parts = memory_engine.read_word(fighter_dynamic_parts)
    dynamic_part_count = memory_engine.read_word(fighter_dynamic_parts + 0x04)
    skipped_parts = {
        memory_engine.read_byte(dynamic_parts + index * 4)
        for index in range(dynamic_part_count)
    }
    parts_table = memory_engine.read_word(0x804D6544)
    fighter_parts_table = memory_engine.read_word(parts_table + 2 * 4)
    parts_count = memory_engine.read_word(fighter_parts_table + 0x08)
    target_part = 1

    def walk(address: int, parent_index: int) -> None:
        nonlocal target_part
        while address != 0:
            if not 0x80000000 <= address < 0x81800000:
                raise RuntimeError(
                    "invalid GuardOn HSD_Joint MEM1 pointer: "
                    f"0x{address:08x}"
                )
            if address in visited or len(rows) >= 256:
                raise RuntimeError("invalid GuardOn HSD_Joint tree")
            visited.add(address)
            snapshot = BigEndianSnapshot.read(memory_engine, address, 0x40)
            source_index = len(rows)
            while target_part in skipped_parts:
                target_part += 1
            if target_part >= parts_count:
                raise RuntimeError("GuardOn target exceeds Falcon part table")
            child = snapshot.u32(address + 0x08)
            next_sibling = snapshot.u32(address + 0x0C)
            rows.append(
                {
                    "source_index": source_index,
                    "target_part_index": target_part,
                    "parent_index": parent_index,
                    "address": address,
                    "flags": snapshot.u32(address + 0x04),
                    "rotation": snapshot.f32_vector(address + 0x14, 3),
                    "scale": snapshot.f32_vector(address + 0x20, 3),
                    "translation": snapshot.f32_vector(address + 0x2C, 3),
                }
            )
            target_part += 1
            if child != 0:
                walk(child, source_index)
            address = next_sibling

    walk(root, -1)
    if len(rows) != 62:
        raise RuntimeError(
            f"unexpected GuardOn HSD_Joint count: {len(rows)} (expected 62)"
        )
    return {
        "schema": 1,
        "fighter_address": fighter,
        "fighter_data_address": fighter_data,
        "guard_pose_table_address": guard_pose_table,
        "joint_roots_address": joint_roots,
        "guard_target_root_address": root,
        "parts_count": parts_count,
        "skipped_part_indices": sorted(skipped_parts),
        "joints": rows,
    }


def read_hurtbox_memory_probe(memory_engine: object) -> dict[str, object]:
    """Read one fighter's collision-authoritative hurt-capsule pose."""

    fighter = read_fighter_address(memory_engine, 0)
    snapshot = BigEndianSnapshot.read(memory_engine, fighter, 0x2350)
    hurtbox_count = snapshot.u8(fighter + 0x119E)
    if hurtbox_count > 15:
        raise RuntimeError(f"invalid Fighter hurt-capsule count: {hurtbox_count}")
    hurtboxes = []
    for index in range(hurtbox_count):
        hurtbox = fighter + 0x11A0 + index * 0x4C
        hurtboxes.append(
            {
                "state": snapshot.u32(hurtbox),
                "state_bytes": snapshot.bytes_at(hurtbox, 4).hex(),
                "radius": snapshot.f32(hurtbox + 0x1C),
                "position_a": snapshot.f32_vector(hurtbox + 0x28, 3),
                "position_b": snapshot.f32_vector(hurtbox + 0x34, 3),
                "bone_index": snapshot.u32(hurtbox + 0x40),
                "height": snapshot.u32(hurtbox + 0x44),
                "grabbable": snapshot.u32(hurtbox + 0x48),
            }
        )
    return {
        "fighter_address": fighter,
        "fighter_position": snapshot.f32_vector(fighter + 0xB0, 3),
        "fighter_hurtboxes": hurtboxes,
    }


def read_hitbox_memory_probe(memory_engine: object) -> dict[str, object]:
    """Read both Falcons' live attack and hurt-capsule geometry."""

    common = memory_engine.read_word(0x804D6554)

    def read_ecb(
        fighter_address: int,
        snapshot: BigEndianSnapshot,
        offset: int,
    ) -> dict[str, list[float]]:
        ecb = fighter_address + offset
        return {
            name: snapshot.f32_vector(ecb + offset, 2)
            for name, offset in (
                ("top", 0x00),
                ("bottom", 0x08),
                ("right", 0x10),
                ("left", 0x18),
            )
        }

    def read_hitboxes(
        fighter_address: int, snapshot: BigEndianSnapshot
    ) -> list[dict[str, object]]:
        hitboxes = []
        for index in range(4):
            hitbox = fighter_address + 0x914 + index * 0x138
            hitboxes.append(
                {
                    "state": snapshot.u32(hitbox),
                    "hit_id": snapshot.u32(hitbox + 0x04),
                    "damage_count": snapshot.u32(hitbox + 0x08),
                    "damage": snapshot.f32(hitbox + 0x0C),
                    "bone_offset": snapshot.f32_vector(hitbox + 0x10, 3),
                    "radius": snapshot.f32(hitbox + 0x1C),
                    "angle": snapshot.u32(hitbox + 0x20),
                    "knockback_growth": snapshot.u32(hitbox + 0x24),
                    "weight_set_knockback": snapshot.u32(hitbox + 0x28),
                    "base_knockback": snapshot.u32(hitbox + 0x2C),
                    "element": snapshot.u32(hitbox + 0x30),
                    "position": snapshot.f32_vector(hitbox + 0x4C, 3),
                    "previous_position": snapshot.f32_vector(
                        hitbox + 0x58, 3
                    ),
                }
            )
        return hitboxes

    fighter = read_fighter_address(memory_engine, 0)
    opponent = read_fighter_address(memory_engine, 1)
    fighter_snapshot = BigEndianSnapshot.read(memory_engine, fighter, 0x2350)
    opponent_snapshot = BigEndianSnapshot.read(memory_engine, opponent, 0x2350)
    return {
        "fighter_address": fighter,
        "fighter_animation_frame": fighter_snapshot.f32(fighter + 0x894),
        "fighter_animation_rate": fighter_snapshot.f32(fighter + 0x89C),
        "fighter_motion_id": fighter_snapshot.u32(fighter + 0x10),
        "fighter_animation_id": fighter_snapshot.u32(fighter + 0x14),
        "fighter_animation_blend_frames": fighter_snapshot.f32(fighter + 0x8A4),
        "fighter_animation_blend_progress": fighter_snapshot.f32(fighter + 0x8A8),
        "hurtbox_state_flag_byte": fighter_snapshot.u8(fighter + 0x221A),
        "fighter_position": fighter_snapshot.f32_vector(fighter + 0xB0, 3),
        "fighter_scale": fighter_snapshot.f32_vector(fighter + 0x34, 3),
        "hitboxes": read_hitboxes(fighter, fighter_snapshot),
        "fighter_hurtboxes": read_fighter_hurt_capsules(
            memory_engine, fighter, fighter_snapshot
        ),
        "fighter_desired_ecb": read_ecb(fighter, fighter_snapshot, 0x774),
        "fighter_ecb": read_ecb(fighter, fighter_snapshot, 0x794),
        "fighter_previous_ecb": read_ecb(fighter, fighter_snapshot, 0x7B4),
        "fighter_ecb_lock_ticks": fighter_snapshot.u32(fighter + 0x88C),
        "fighter_collision_flags": fighter_snapshot.u32(fighter + 0x820),
        "fighter_ledge_snap": fighter_snapshot.f32_vector(fighter + 0x744, 3),
        "fighter_collision_contact": fighter_snapshot.f32_vector(
            fighter + 0x830, 3
        ),
        "fighter_collision_positions": {
            name: fighter_snapshot.f32_vector(fighter + offset, 3)
            for name, offset in (
                ("current", 0x6F4),
                ("previous", 0x700),
                ("last", 0x70C),
            )
        },
        "fighter_ledge_ids": [
            fighter_snapshot.u32(fighter + 0x730),
            fighter_snapshot.u32(fighter + 0x734),
        ],
        "fighter_environment_flags": fighter_snapshot.u32(fighter + 0x824),
        "fighter_previous_environment_flags": fighter_snapshot.u32(fighter + 0x828),
        "fighter_command_variables": [
            fighter_snapshot.u32(fighter + 0x2200 + 4 * index)
            for index in range(4)
        ],
        "fighter_captain_specialhi_flags": fighter_snapshot.u8(fighter + 0x2342),
        "fighter_captain_specialhi_velocity": [
            fighter_snapshot.f32(fighter + 0x2344),
            fighter_snapshot.f32(fighter + 0x2348),
        ],
        "opponent_fighter_address": opponent,
        "opponent_fighter_position": opponent_snapshot.f32_vector(
            opponent + 0xB0, 3
        ),
        "opponent_hitboxes": read_hitboxes(opponent, opponent_snapshot),
        "opponent_damage_percent_internal": opponent_snapshot.f32(
            opponent + 0x1830
        ),
        "opponent_damage_percent_temp": opponent_snapshot.f32(opponent + 0x1838),
        "opponent_knockback_applied": opponent_snapshot.f32(opponent + 0x1850),
        "opponent_knockback_magnitude": opponent_snapshot.f32(opponent + 0x18A4),
        "opponent_knockback_applied_latched": opponent_snapshot.f32(
            opponent + 0x18A8
        ),
        "opponent_damage_state_ticks": opponent_snapshot.u32(opponent + 0x2340),
        "throw_weight": memory_engine.read_float(common + 0x10C),
        "opponent_hurtboxes": read_fighter_hurt_capsules(
            memory_engine, opponent, opponent_snapshot
        ),
        "opponent_ecb": read_ecb(opponent, opponent_snapshot, 0x794),
    }


def read_surface_collision_memory_probe(
    memory_engine: object,
    *,
    player_index: int = 0,
    include_capture_constraint_state: bool = False,
) -> dict[str, object]:
    """Read the source ECB/environment contact selected by fighter collision."""

    fighter = read_fighter_address(memory_engine, player_index)
    snapshot = BigEndianSnapshot.read(memory_engine, fighter, 0x8AC)
    common = memory_engine.read_word(0x804D6554)

    def read_surface(offset: int) -> dict[str, object]:
        surface = fighter + offset
        return {
            "index": snapshot.u32(surface),
            "flags": snapshot.u32(surface + 0x04),
            "normal": snapshot.f32_vector(surface + 0x08, 3),
        }

    ecb = fighter + 0x794
    ecb_source_kind = snapshot.u32(fighter + 0x7F4)
    ecb_source_joints = [
        snapshot.u32(fighter + 0x7FC + 4 * index) for index in range(6)
    ]
    ecb_source_closure_indices = (
        0, 1, 2, 3, 4, 6, 7, 8, 12, 13, 14, 18, 19,
        21, 22, 23, 24, 25, 38, 39, 42, 44, 45, 46, 47, 61,
    )
    parts = snapshot.u32(fighter + 0x5E8)
    parts_snapshot = BigEndianSnapshot.read(memory_engine, parts, 0x3F0)
    result: dict[str, object] = {
        "fighter_address": fighter,
        "fighter_costume_id": snapshot.u8(fighter + 0x619),
        "fighter_costume_joint": snapshot.u32(fighter + 0x108),
        "fighter_animation_frame": snapshot.f32(fighter + 0x894),
        "fighter_animation_rate": snapshot.f32(fighter + 0x89C),
        "fighter_motion_id": snapshot.u32(fighter + 0x10),
        "fighter_animation_id": snapshot.u32(fighter + 0x14),
        "fighter_animation_blend_frames": snapshot.f32(fighter + 0x8A4),
        "fighter_animation_blend_progress": snapshot.f32(fighter + 0x8A8),
        "environment_flags": snapshot.u32(fighter + 0x824),
        "previous_environment_flags": snapshot.u32(fighter + 0x828),
        "contact": snapshot.f32_vector(fighter + 0x830, 3),
        "ecb": {
            name: snapshot.f32_vector(ecb + offset, 2)
            for name, offset in (
                ("top", 0x00),
                ("bottom", 0x08),
                ("right", 0x10),
                ("left", 0x18),
            )
        },
        "ecb_source": {
            "kind": ecb_source_kind,
            "joints": [
                {
                    "address": jobj,
                    "world_translation": read_jobj_world_translation(
                        memory_engine, jobj
                    ),
                }
                for jobj in ecb_source_joints
            ]
            if ecb_source_kind == 1
            else [],
            "joint_closure": [
                {
                    "source_index": index,
                    "address": (
                        jobj := parts_snapshot.u32(parts + 0x10 * index)
                    ),
                    "animation_address": (
                        animation_jobj := parts_snapshot.u32(
                            parts + 0x10 * index + 0x04
                        )
                    ),
                    "fighter_bone_flags": parts_snapshot.u16(
                        parts + 0x10 * index + 0x08
                    ),
                    "pose": read_jobj_pose(memory_engine, jobj),
                    "animation_pose": read_jobj_pose(
                        memory_engine, animation_jobj
                    ),
                }
                for index in ecb_source_closure_indices
            ]
            if ecb_source_kind == 1
            else [],
            "side_y_offset": snapshot.f32(fighter + 0x814),
            "minimum_height": snapshot.f32(fighter + 0x818),
            "minimum_width": snapshot.f32(fighter + 0x81C),
        },
        "input": {
            "held": snapshot.u32(fighter + 0x65C),
            "previous_held": snapshot.u32(fighter + 0x660),
            "pressed": snapshot.u32(fighter + 0x668),
            "released": snapshot.u32(fighter + 0x66C),
            "timers_670_685": list(
                snapshot.bytes_at(fighter + 0x670, 0x16)
            ),
            "tech_input_age": snapshot.u8(fighter + 0x680),
            "tech_lockout": snapshot.u8(fighter + 0x684),
            "tech_window": memory_engine.read_float(common + 0x250),
            "tech_lockout_minimum": memory_engine.read_word(common + 0x1C),
        },
        "surfaces": {
            "floor": read_surface(0x83C),
            "left_facing_wall": read_surface(0x850),
            "right_facing_wall": read_surface(0x864),
            "ceiling": read_surface(0x878),
        },
    }
    if include_capture_constraint_state:
        constraint_snapshot = BigEndianSnapshot.read(
            memory_engine, fighter + 0x2174, 0xB3
        )

        def read_ecb_at(offset: int) -> dict[str, object]:
            base = fighter + offset
            return {
                name: snapshot.f32_vector(base + component_offset, 2)
                for name, component_offset in (
                    ("top", 0x00),
                    ("bottom", 0x08),
                    ("right", 0x10),
                    ("left", 0x18),
                )
            }

        result["capture_constraint"] = {
            "fighter_position": snapshot.f32_vector(fighter + 0xB0, 3),
            "collision_positions": {
                "current": snapshot.f32_vector(fighter + 0x6F4, 3),
                "previous_step": snapshot.f32_vector(fighter + 0x700, 3),
                "routine_start": snapshot.f32_vector(fighter + 0x70C, 3),
                "pre_collision": snapshot.f32_vector(fighter + 0x718, 3),
            },
            "desired_ecb": read_ecb_at(0x774),
            "current_ecb": read_ecb_at(0x794),
            "previous_step_ecb": read_ecb_at(0x7B4),
            "routine_start_ecb": read_ecb_at(0x7D4),
            "saved_xrotn_translation": constraint_snapshot.f32_vector(
                fighter + 0x2174, 3
            ),
            "flags_2226_raw": constraint_snapshot.u8(fighter + 0x2226),
        }
    return result


def read_stage_collision_memory_probe(
    memory_engine: object,
) -> dict[str, object]:
    """Read source topology and the runtime world-space collision catalog.

    MapCollData vertices are joint-local.  Melee collision queries use the
    transformed ``groundCollVtx[*].pos`` array instead, so committing only the
    source vertices silently misplaces collision lines owned by translated or
    animated stage joints.
    """

    stage_info_address = 0x8049E6C8
    stage_info = BigEndianSnapshot.read(
        memory_engine, stage_info_address, 0x290
    )
    camera_bounds = stage_info.f32_vector(stage_info_address, 4)
    camera_offset = stage_info.f32_vector(stage_info_address + 0x10, 2)
    blast_zone = stage_info.f32_vector(stage_info_address + 0x74, 4)

    def read_stage_point(index: int) -> dict[str, object] | None:
        jobj = stage_info.u32(stage_info_address + 0x280 + index * 4)
        if jobj == 0:
            return None
        if not 0x80000000 <= jobj < 0x81800000:
            raise RuntimeError(
                f"stage point {index} has invalid HSD_JObj pointer 0x{jobj:08x}"
            )
        jobj_snapshot = BigEndianSnapshot.read(memory_engine, jobj, 0x74)
        parent = jobj_snapshot.u32(jobj + 0x0C)
        position_offset = 0x38 if parent == 0 else 0x50
        position = (
            jobj_snapshot.f32_vector(jobj + position_offset, 3)
            if parent == 0
            else [
                jobj_snapshot.f32(jobj + 0x50),
                jobj_snapshot.f32(jobj + 0x60),
                jobj_snapshot.f32(jobj + 0x70),
            ]
        )
        return {
            "index": index,
            "jobj_address": jobj,
            "parent_address": parent,
            "position": position,
        }

    map_coll_data = memory_engine.read_word(0x804D64B4)
    header = BigEndianSnapshot.read(memory_engine, map_coll_data, 0x30)
    vertices_address = header.u32(map_coll_data)
    vertex_count = header.u32(map_coll_data + 0x04)
    lines_address = header.u32(map_coll_data + 0x08)
    line_count = header.u32(map_coll_data + 0x0C)
    if not 0 < vertex_count <= 4096 or not 0 < line_count <= 4096:
        raise RuntimeError(
            "loaded stage collision catalog has invalid dimensions: "
            f"vertices={vertex_count} lines={line_count}"
        )
    vertices_snapshot = BigEndianSnapshot.read(
        memory_engine, vertices_address, vertex_count * 8
    )
    source_vertices = [
        vertices_snapshot.f32_vector(vertices_address + index * 8, 2)
        for index in range(vertex_count)
    ]
    runtime_vertices_address = memory_engine.read_word(0x804D64B8)
    runtime_lines_address = memory_engine.read_word(0x804D64BC)
    if runtime_vertices_address == 0 or runtime_lines_address == 0:
        raise RuntimeError("runtime stage collision catalog is not loaded")
    runtime_vertices_snapshot = BigEndianSnapshot.read(
        memory_engine, runtime_vertices_address, vertex_count * 0x18
    )
    runtime_vertices = [
        runtime_vertices_snapshot.f32_vector(
            runtime_vertices_address + index * 0x18 + 0x08,
            2,
        )
        for index in range(vertex_count)
    ]
    runtime_lines_snapshot = BigEndianSnapshot.read(
        memory_engine, runtime_lines_address, line_count * 8
    )
    lines_snapshot = BigEndianSnapshot.read(
        memory_engine, lines_address, line_count * 0x10
    )
    ranges = {
        name: {
            "start": header.i16(map_coll_data + offset),
            "count": header.i16(map_coll_data + offset + 2),
        }
        for name, offset in (
            ("floor", 0x10),
            ("ceiling", 0x14),
            ("right_wall", 0x18),
            ("left_wall", 0x1C),
            ("dynamic", 0x20),
        )
    }

    def line_kind(index: int) -> str:
        for name, bounds in ranges.items():
            start = int(bounds["start"])
            count = int(bounds["count"])
            if start <= index < start + count:
                return name
        return "unclassified"

    lines = []
    for index in range(line_count):
        address = lines_address + index * 0x10
        v0 = lines_snapshot.u16(address)
        v1 = lines_snapshot.u16(address + 0x02)
        if v0 >= vertex_count or v1 >= vertex_count:
            raise RuntimeError(
                f"stage collision line {index} has an invalid vertex index"
            )
        runtime_line_address = runtime_lines_address + index * 8
        runtime_source_line = runtime_lines_snapshot.u32(runtime_line_address)
        expected_source_line = lines_address + index * 0x10
        if runtime_source_line != expected_source_line:
            raise RuntimeError(
                f"runtime stage collision line {index} has an invalid source pointer"
            )
        lines.append(
            {
                "index": index,
                "kind": line_kind(index),
                "vertices": [v0, v1],
                "start": source_vertices[v0],
                "end": source_vertices[v1],
                "world_start": runtime_vertices[v0],
                "world_end": runtime_vertices[v1],
                "neighbors": [
                    lines_snapshot.i16(address + offset)
                    for offset in (0x04, 0x06, 0x08, 0x0A)
                ],
                "hi_flags": lines_snapshot.u16(address + 0x0C),
                "lo_flags": lines_snapshot.u16(address + 0x0E),
                "runtime_flags": runtime_lines_snapshot.u32(
                    runtime_line_address + 0x04
                ),
            }
        )
    return {
        "stage_info_address": stage_info_address,
        "grkind": stage_info.u32(stage_info_address + 0x88),
        "camera": {
            "bounds": {
                "left": camera_bounds[0],
                "right": camera_bounds[1],
                "top": camera_bounds[2],
                "bottom": camera_bounds[3],
            },
            "offset": {"x": camera_offset[0], "y": camera_offset[1]},
            "effective_bounds": {
                "left": camera_bounds[0] + camera_offset[0],
                "right": camera_bounds[1] + camera_offset[0],
                "top": camera_bounds[2] + camera_offset[1],
                "bottom": camera_bounds[3] + camera_offset[1],
            },
        },
        "blast_zone": {
            "raw": {
                "left": blast_zone[0],
                "right": blast_zone[1],
                "top": blast_zone[2],
                "bottom": blast_zone[3],
            },
            "effective": {
                "left": blast_zone[0] + camera_offset[0],
                "right": blast_zone[1] + camera_offset[0],
                "top": blast_zone[2] + camera_offset[1],
                "bottom": blast_zone[3] + camera_offset[1],
            },
        },
        "player_spawn_points": [read_stage_point(index) for index in range(4)],
        "map_coll_data_address": map_coll_data,
        "vertices_address": vertices_address,
        "runtime_vertices_address": runtime_vertices_address,
        "vertex_count": vertex_count,
        "lines_address": lines_address,
        "runtime_lines_address": runtime_lines_address,
        "line_count": line_count,
        "ranges": ranges,
        "lines": lines,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def file_revision_fingerprint(path: Path) -> dict[str, int]:
    """Return the stable identity shared by immutable hardlinks."""

    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def cached_sha256(path: Path) -> str:
    """Hash immutable oracle inputs once per exact filesystem revision."""

    resolved = path.resolve()
    fingerprint = file_revision_fingerprint(resolved)
    cache_path = (
        Path(__file__).resolve().parent.parent
        / "build"
        / "oracle-toolchain"
        / "sha256-cache.json"
    )
    cache: dict[str, dict[str, object]] = {}
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    key = str(resolved)
    cached = cache.get(key, {})
    matching_entry = cached
    if matching_entry.get("fingerprint") != fingerprint:
        matching_entry = next(
            (
                entry
                for entry in cache.values()
                if isinstance(entry, dict)
                and entry.get("fingerprint") == fingerprint
            ),
            {},
        )
    if matching_entry.get("fingerprint") == fingerprint:
        digest = matching_entry.get("sha256")
        if isinstance(digest, str) and len(digest) == 64:
            return digest

    digest = sha256(resolved)
    cache[key] = {"fingerprint": fingerprint, "sha256": digest}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_name(
        f"{cache_path.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(
        json.dumps(cache, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    return digest


_LIBMELEE_GET_DOLPHIN_VERSION = melee_console.get_dolphin_version


def preload_hardlinked_dolphin_version(path: Path) -> None:
    """Probe one immutable Dolphin inode once before capture workers fork."""

    executable = Path(melee_console.get_exe_path(str(path.resolve()))).resolve()
    fingerprint = file_revision_fingerprint(executable)
    version = _LIBMELEE_GET_DOLPHIN_VERSION(str(executable))

    def get_dolphin_version(candidate: str) -> object:
        candidate_executable = Path(melee_console.get_exe_path(candidate)).resolve()
        if file_revision_fingerprint(candidate_executable) == fingerprint:
            return version
        return _LIBMELEE_GET_DOLPHIN_VERSION(candidate)

    melee_console.get_dolphin_version = get_dolphin_version


def wait_for_udp_listener(port: int, timeout: float) -> None:
    """Wait until Dolphin owns the local Slippi spectator port.

    Calling ENet's connect before Dolphin binds the port leaves the libmelee
    host with a stale peer. Detecting ownership first makes the single connect
    attempt deterministic on slower AppImage/WSL starts.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if os.name == "nt":
                # Windows permits a loopback UDP bind alongside an existing
                # wildcard bind unless the probe itself is exclusive. Slippi
                # listens on 0.0.0.0, so probe the same address and request
                # exclusive ownership to avoid a false "port is free" result.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("0.0.0.0", port))
        except OSError:
            return
        finally:
            probe.close()
        time.sleep(0.05)
    raise RuntimeError(f"Dolphin did not bind Slippi UDP port {port}")


_CHECKPOINT_TARGET_PIDS: dict[int, int] = {}


def begin_headless_checkpoint(
    process: subprocess.Popen[bytes],
    action: str,
    slot: int = 0,
) -> dict[str, object]:
    """Queue a checkpoint operation for the next blocking EXI input boundary."""

    if action not in {"saved", "loaded"}:
        raise ValueError(f"unsupported checkpoint action: {action}")
    if not 0 <= slot < CHECKPOINT_SLOT_COUNT:
        raise ValueError(f"unsupported checkpoint slot: {slot}")
    target_pid = _CHECKPOINT_TARGET_PIDS.get(process.pid, process.pid)
    status_path = Path(f"/tmp/pf-exiai-checkpoint-{target_pid}.status")
    if not status_path.is_file():
        ready_statuses = sorted(
            (
                path
                for path in Path("/tmp").glob("pf-exiai-checkpoint-*.status")
                if path.read_text(encoding="ascii").startswith("ready ")
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not ready_statuses:
            raise RuntimeError("Dolphin checkpoint control endpoint is not ready")
        status_path = ready_statuses[0]
        target_pid = int(status_path.stem.rsplit("-", 1)[1])
        _CHECKPOINT_TARGET_PIDS[process.pid] = target_pid
    previous = status_path.read_text(encoding="ascii")
    requested_at = time.monotonic()
    request_path = Path(f"/tmp/pf-exiai-checkpoint-{target_pid}.request")
    temporary_request = request_path.with_suffix(".request.tmp")
    temporary_request.write_text(
        f"{'save' if action == 'saved' else 'load'} {slot}\n",
        encoding="ascii",
    )
    temporary_request.replace(request_path)
    return {
        "action": action,
        "slot": slot,
        "status_path": status_path,
        "previous": previous,
        "requested_at": requested_at,
    }


def finish_headless_checkpoint(
    process: subprocess.Popen[bytes],
    request: dict[str, object],
    timeout: float = 10.0,
) -> float:
    """Wait for an EXI-boundary checkpoint request after advancing input."""

    action = str(request["action"])
    slot = int(request["slot"])
    status_path = Path(request["status_path"])
    previous = str(request["previous"])
    requested_at = float(request["requested_at"])
    deadline = requested_at + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Dolphin exited during checkpoint {action}: {process.returncode}"
            )
        current = status_path.read_text(encoding="ascii")
        if previous != current:
            words = current.split()
            response_slot = int(words[1]) if len(words) >= 2 else 0
            if words and words[0] == "empty" and response_slot == slot:
                raise RuntimeError(f"checkpoint slot {slot} is empty")
            if words and words[0] == action and response_slot == slot:
                return time.monotonic() - requested_at
        time.sleep(0.005)
    raise TimeoutError(f"Dolphin checkpoint {action} timed out")


def stop_console(console: melee.Console) -> None:
    """Stop Dolphin and remove libmelee's temporary home without a Windows race."""

    process = console._process
    temp_dir = console.temp_dir
    console.temp_dir = None
    console.stop()

    if process is not None:
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)

        target_pid = _CHECKPOINT_TARGET_PIDS.pop(process.pid, process.pid)
        for suffix in ("request", "request.tmp", "status", "status.tmp"):
            Path(f"/tmp/pf-exiai-checkpoint-{target_pid}.{suffix}").unlink(
                missing_ok=True
            )

    if temp_dir is None:
        return
    for attempt in range(50):
        try:
            shutil.rmtree(temp_dir)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 49:
                raise
            time.sleep(0.1)


def choose_match(
    gamestate: melee.GameState,
    player_one: melee.Controller,
    player_two: melee.Controller,
    stage: melee.Stage,
    menu_helper: melee.MenuHelper,
    modern_menu_helper: bool,
    opponent: melee.Character = melee.Character.FOX,
    stage_cursor: tuple[float, float] | None = None,
) -> None:
    if gamestate.menu_state in (
        melee.Menu.CHARACTER_SELECT,
        melee.Menu.SLIPPI_ONLINE_CSS,
    ):
        menu_helper.choose_character(
            opponent,
            gamestate,
            player_two,
            costume=0,
            swag=False,
            start=False,
        )
        menu_helper.choose_character(
            melee.Character.CPTFALCON,
            gamestate,
            player_one,
            costume=0,
            swag=False,
            start=True,
        )
    elif gamestate.menu_state == melee.Menu.STAGE_SELECT:
        player_two.release_all()
        if stage_cursor is None:
            if modern_menu_helper:
                menu_helper.choose_stage(
                    stage,
                    gamestate,
                    player_one,
                    melee.Character.CPTFALCON,
                    autostart=True,
                )
            else:
                menu_helper.choose_stage(stage, gamestate, player_one)
        else:
            choose_stage_at(gamestate, player_one, *stage_cursor)
    elif gamestate.menu_state in (melee.Menu.PRESS_START, melee.Menu.MAIN_MENU):
        player_two.release_all()
        menu_helper.choose_versus_mode(gamestate, player_one)
    else:
        player_one.release_all()
        player_two.release_all()


def install_slippi_raw_pad_extension(console: melee.Console) -> None:
    """Retain raw C-stick bytes that libmelee 0.47.2 otherwise discards."""

    original = console._Console__pre_frame
    raw_c_stick_by_port: dict[int, tuple[int, int]] = {}
    console._pf_raw_c_stick_by_port = raw_c_stick_by_port

    def pre_frame_with_raw_pad(
        self: melee.Console,
        gamestate: melee.GameState,
        event_bytes: bytes,
    ) -> None:
        original(gamestate, event_bytes)
        if len(event_bytes) <= 0x42:
            raise RuntimeError(
                "exact UCF input capture requires Slippi raw main/C payloads"
            )
        controller_port = int(event_bytes[0x05]) + 1
        if int(event_bytes[0x06]) == 1:
            return

        def signed_axis(offset: int) -> int:
            value = int(event_bytes[offset])
            return value if value < 0x80 else value - 0x100

        raw_c_stick_by_port[controller_port] = (
            signed_axis(0x41),
            signed_axis(0x42),
        )

    console._Console__pre_frame = types.MethodType(
        pre_frame_with_raw_pad,
        console,
    )


def choose_stage_at(
    gamestate: melee.GameState,
    controller: melee.Controller,
    target_x: float,
    target_y: float,
) -> None:
    """Choose a vanilla stage at a source-derived stage-select coordinate."""

    if gamestate.frame < 20:
        controller.release_all()
        return
    cursor = gamestate.players[controller.port].cursor
    wiggleroom = 1.5
    controller.release_button(melee.Button.BUTTON_A)
    if cursor.y < target_y - wiggleroom:
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 0.5, 1.0)
    elif cursor.y > target_y + wiggleroom:
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 0.5, 0.0)
    elif cursor.x < target_x - wiggleroom:
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 1.0, 0.5)
    elif cursor.x > target_x + wiggleroom:
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 0.0, 0.5)
    else:
        controller.press_button(melee.Button.BUTTON_A)


def wait_for_grounded_capsule(
    console: melee.Console,
    player_one: melee.Controller,
    player_two: melee.Controller,
    gamestate: melee.GameState,
) -> melee.GameState:
    """Advance neutral frames until the native Capsule has stopped bouncing."""

    for _ in range(600):
        if len(gamestate.projectiles) == 1:
            item = gamestate.projectiles[0]
            if (
                int(item.type.value) == 255
                and int(item.subtype) == 0
                and float(item.speed.x) == 0.0
                and float(item.speed.y) == 0.0
            ):
                return gamestate
        player_one.release_all()
        player_two.release_all()
        next_state = console.step()
        if next_state is None:
            raise RuntimeError("missing state while waiting for grounded Capsule")
        gamestate = next_state
    raise RuntimeError("native Capsule did not settle within 600 frames")


def hook_memory_engine(dolphin: Path) -> object:
    """Hook DME, including extracted-AppImage process-name discovery."""

    if "DME_DOLPHIN_PROCESS_NAME" not in os.environ:
        if os.name == "nt" and dolphin.suffix.lower() == ".exe":
            # DME otherwise searches only Dolphin.exe/DolphinQt2.exe/
            # DolphinWx.exe. Slippi's executable has a distinct process name.
            os.environ["DME_DOLPHIN_PROCESS_NAME"] = dolphin.name
        elif dolphin.suffix.lower() == ".appimage" or dolphin.name.lower() in {
            "apprun",
            "apprun.wrapped",
        }:
            os.environ["DME_DOLPHIN_PROCESS_NAME"] = "AppRun.wrapped"
        else:
            os.environ["DME_DOLPHIN_PROCESS_NAME"] = dolphin.name
    try:
        import dolphin_memory_engine as memory_engine_module
    except ImportError as error:
        raise RuntimeError("memory probes require dolphin-memory-engine") from error
    memory_engine_module.hook()
    return memory_engine_module


def wait_for_memory_engine_hook(dolphin: Path) -> object:
    memory_engine = hook_memory_engine(dolphin)
    hook_deadline = time.monotonic() + 10.0
    while not memory_engine.is_hooked() and time.monotonic() < hook_deadline:
        time.sleep(0.05)
        memory_engine.hook()
    if not memory_engine.is_hooked():
        raise RuntimeError(
            "dolphin-memory-engine could not hook the oracle process: "
            f"{memory_engine.get_status()}"
        )
    return memory_engine


def set_native_capsule_preferences(memory_engine: object) -> None:
    """Set the source item-switch preference to Capsule at Very High."""

    # gm_80167BC8 maps the item-switch UI mask through lbl_803B7844 when it
    # constructs StartMeleeRules.x20. Capsule (It_Kind_Capsule == 0) is UI
    # bit 29, not bit 0.
    capsule_item_switch_mask = (1 << 29).to_bytes(8, "big")
    main_data = int(memory_engine.read_word(0x804D3EE0))
    if not 0x80000000 <= main_data < 0x81800000:
        raise RuntimeError(f"invalid gmMainLib_804D3EE0 pointer: 0x{main_data:08x}")
    item_preferences = main_data + 0x1898 + 0x448
    memory_engine.write_byte(item_preferences, 4)
    memory_engine.write_bytes(
        item_preferences + 8,
        capsule_item_switch_mask,
    )
    if (
        int(memory_engine.read_byte(item_preferences)) != 4
        or bytes(memory_engine.read_bytes(item_preferences + 8, 8))
        != capsule_item_switch_mask
    ):
        raise RuntimeError("native item preferences did not retain write")


def read_native_item_rules(memory_engine: object) -> dict[str, object]:
    """Read the source preferences and isolated item-rule accessor code."""

    main_data = int(memory_engine.read_word(0x804D3EE0))
    if not 0x80000000 <= main_data < 0x81800000:
        raise RuntimeError(f"invalid gmMainLib_804D3EE0 pointer: 0x{main_data:08x}")
    item_preferences = main_data + 0x1898 + 0x448
    return {
        "spawns_enabled": int(memory_engine.read_word(0x8049FAA0 + 8)),
        "rule_accessor_code": {
            "frequency": bytes(memory_engine.read_bytes(0x8016AE80, 8)).hex(),
            "runtime_mask": bytes(memory_engine.read_bytes(0x8016AEA4, 12)).hex(),
        },
        "preferences": {
            "frequency": int(memory_engine.read_byte(item_preferences)),
            "item_switch_mask": bytes(
                memory_engine.read_bytes(item_preferences + 8, 8)
            ).hex(),
        },
    }


def enable_native_capsule_gecko(console: object) -> None:
    """Configure the native spawner despite Slippi's items-off rule override."""

    game_settings = (
        Path(console._get_dolphin_home_path()) / "GameSettings" / "GALE01r2.ini"
    )
    if not game_settings.is_file():
        raise FileNotFoundError(f"missing libmelee Gecko config: {game_settings}")
    # Slippi's recording rules replace StartMeleeRules.xB with -1 during the
    # match handoff, after vanilla preferences are copied. Override only the
    # two source accessors consumed by it_8026D018 and the ambient spawner:
    # frequency 4 (Very High), and runtime item-kind bit 0 (Capsule).
    enabled_header = "[Gecko_Enabled]\n"
    gecko_header = "[Gecko]\n"
    code_name = "$Oracle: Native Capsule Spawning"
    text = game_settings.read_text(encoding="ascii")
    if enabled_header not in text or gecko_header not in text:
        raise RuntimeError("unexpected libmelee Gecko config structure")
    text = text.replace(
        enabled_header,
        f"{enabled_header}{code_name}\n",
        1,
    )
    text = text.replace(
        gecko_header,
        (
            f"{gecko_header}{code_name}\n"
            "0416AE80 38600004 # Oracle/Items/NativeFrequencyVeryHigh.asm\n"
            "0416AE84 4E800020\n"
            "0416AEA4 38600000 # Oracle/Items/NativeMaskCapsuleHi.asm\n"
            "0416AEA8 38800001\n"
            "0416AEAC 4E800020\n"
        ),
        1,
    )
    game_settings.write_text(text, encoding="ascii", newline="\n")


def capture(args: argparse.Namespace) -> dict[str, object]:
    dolphin = Path(args.dolphin).resolve()
    iso = Path(args.iso).resolve()
    if dolphin.is_dir():
        executable_candidates = (
            dolphin / "Slippi Dolphin.exe",
            dolphin / "dolphin-emu",
        )
        executable = next(
            (candidate for candidate in executable_candidates if candidate.is_file()),
            None,
        )
        if executable is None:
            raise FileNotFoundError(f"missing Slippi Dolphin under {dolphin}")
    elif not dolphin.is_file():
        raise FileNotFoundError(f"missing Dolphin executable or AppImage: {dolphin}")
    else:
        executable = dolphin
    if not iso.is_file():
        raise FileNotFoundError(f"missing GALE01 image: {iso}")
    checkpoint_coverage_manifest = None
    if args.oracle_coverage_manifest is not None:
        coverage_bytes = args.oracle_coverage_manifest.read_bytes()
        checkpoint_coverage_manifest = json.loads(coverage_bytes)
        if args.oracle_case:
            checkpoint_coverage_manifest = projected_manifest(
                checkpoint_coverage_manifest,
                [str(case_id) for case_id in args.oracle_case],
                hashlib.sha256(coverage_bytes).hexdigest(),
                None,
                None,
                None,
            )
    checkpoint_capture_plan = (
        dict(checkpoint_coverage_manifest["checkpoint_pack"]["capture_plan"])
        if checkpoint_coverage_manifest is not None
        else None
    )
    checkpoint_input_memory_probe_schema = (
        checkpoint_capture_plan.get("input_memory_probe_schema", 1)
        if checkpoint_capture_plan is not None
        else 1
    )
    if (
        not isinstance(checkpoint_input_memory_probe_schema, int)
        or isinstance(checkpoint_input_memory_probe_schema, bool)
        or checkpoint_input_memory_probe_schema not in {1, 2}
    ):
        raise ValueError(
            "checkpoint_pack.capture_plan.input_memory_probe_schema "
            "must be 1 or 2"
        )
    if checkpoint_input_memory_probe_schema != 1 and not args.memory_probe_input:
        raise ValueError(
            "input_memory_probe_schema 2 requires --memory-probe-input"
        )
    checkpoint_stage = (
        checkpoint_capture_plan.get("stage")
        if checkpoint_capture_plan is not None
        else None
    )
    if checkpoint_stage not in {
        None,
        "FINAL_DESTINATION",
        "BATTLEFIELD",
        "HYRULE_TEMPLE",
    }:
        raise ValueError(
            "checkpoint_pack.capture_plan.stage must be FINAL_DESTINATION, "
            "BATTLEFIELD, or HYRULE_TEMPLE"
        )
    selected_checkpoint_start_labels: tuple[str, ...] = ()
    if args.oracle_case:
        if checkpoint_capture_plan is None:
            raise ValueError("--oracle-case requires a checkpoint capture plan")
        case_fields = [
            key
            for key, value in checkpoint_capture_plan.items()
            if key.endswith("_cases") and isinstance(value, list)
        ]
        if len(case_fields) > 1:
            raise ValueError("checkpoint capture plan contains multiple case lists")
        if not case_fields:
            projected_cases = checkpoint_coverage_manifest.get("checkpoint_cases")
            if not isinstance(projected_cases, list) or not projected_cases:
                raise ValueError("projected checkpoint cases are missing")
            selected_labels = [
                case.get("start_label")
                for case in projected_cases
                if isinstance(case, dict)
            ]
            if (
                len(selected_labels) != len(projected_cases)
                or any(not isinstance(label, str) or not label for label in selected_labels)
            ):
                raise ValueError(
                    "label-based checkpoint cases require nonempty start_label"
                )
            selected_checkpoint_start_labels = tuple(selected_labels)
    checkpoint_random_seed = (
        checkpoint_capture_plan.get("source_random_seed")
        if checkpoint_capture_plan is not None
        else None
    )
    checkpoint_batch_inputs = (
        checkpoint_capture_plan.get("batch_exi_inputs", False)
        if checkpoint_capture_plan is not None
        else False
    )
    checkpoint_slot_count = (
        checkpoint_capture_plan.get("checkpoint_slot_count", 1)
        if checkpoint_capture_plan is not None
        else 1
    )
    if (
        not isinstance(checkpoint_slot_count, int)
        or isinstance(checkpoint_slot_count, bool)
        or not 1 <= checkpoint_slot_count <= CHECKPOINT_SLOT_COUNT
    ):
        raise ValueError(
            "checkpoint_pack.capture_plan.checkpoint_slot_count must be "
            f"between 1 and {CHECKPOINT_SLOT_COUNT}"
        )
    if not isinstance(checkpoint_batch_inputs, bool):
        raise ValueError("checkpoint_pack.capture_plan.batch_exi_inputs must be boolean")
    if checkpoint_input_memory_probe_schema == 2 and checkpoint_batch_inputs:
        raise ValueError(
            "input_memory_probe_schema 2 requires batch_exi_inputs=false"
        )
    if args.oracle_checkpoint_no_batch_inputs:
        checkpoint_batch_inputs = False
    checkpoint_record_surface_rows = (
        checkpoint_capture_plan.get("record_surface_collision_memory_rows", True)
        if checkpoint_capture_plan is not None
        else True
    )
    if not isinstance(checkpoint_record_surface_rows, bool):
        raise ValueError(
            "checkpoint_pack.capture_plan.record_surface_collision_memory_rows "
            "must be boolean"
        )
    if (
        checkpoint_random_seed is not None
        and (
            not isinstance(checkpoint_random_seed, int)
            or isinstance(checkpoint_random_seed, bool)
            or not 0 <= checkpoint_random_seed <= 0xFFFFFFFF
        )
    ):
        raise ValueError(
            "checkpoint_pack.capture_plan.source_random_seed must be a u32"
        )
    if args.oracle_exiai:
        exiai_artifact = args.oracle_release_artifact.resolve()
        if not exiai_artifact.is_file():
            raise FileNotFoundError(
                "--oracle-exiai requires --oracle-release-artifact pointing "
                "to the pinned ExiAI 0.2.0 AppImage"
            )
        artifact_sha256 = cached_sha256(exiai_artifact)
        if artifact_sha256 != EXIAI_020_APPIMAGE_SHA256:
            raise ValueError(
                "unexpected ExiAI release artifact SHA-256: "
                f"{artifact_sha256}"
            )
        if importlib.metadata.version("melee") != "0.47.2":
            raise RuntimeError("--oracle-exiai requires pinned melee 0.47.2")
    wall_geometry_route = bool(
        args.special_geometry_only
        and args.special_geometry_move
        and "down_ground_wall" in args.special_geometry_move
    )
    surface_response_route = bool(
        args.damage_hit_only
        and checkpoint_capture_plan is not None
        and "surface_response_cases" in checkpoint_capture_plan
    )
    surface_response_stage = checkpoint_stage or (
        "HYRULE_TEMPLE" if surface_response_route else None
    )
    hyrule_stage_route = wall_geometry_route or (
        surface_response_route and surface_response_stage == "HYRULE_TEMPLE"
    )
    battlefield_checkpoint_route = checkpoint_stage == "BATTLEFIELD"
    raw_special_acquisition_cases = (
        checkpoint_capture_plan.get("special_acquisition_cases", [])
        if checkpoint_capture_plan is not None
        else []
    )
    powershield_special_route = bool(
        isinstance(raw_special_acquisition_cases, list)
        and any(
            isinstance(case, dict)
            and case.get("source_state") == "powershield_release"
            for case in raw_special_acquisition_cases
        )
    )
    if wall_geometry_route and set(args.special_geometry_move) != {"down_ground_wall"}:
        raise ValueError(
            "down_ground_wall uses Hyrule Temple and must be captured alone"
        )

    console_path = (
        dolphin.parent
        if os.name == "nt" and dolphin.is_file()
        else dolphin
    )
    console_parameters = inspect.signature(melee.Console).parameters
    console_kwargs: dict[str, object] = dict(
        path=str(console_path),
        slippi_port=args.slippi_port,
        blocking_input=True,
        polling_mode=False,
        tmp_home_directory=True,
        copy_home_directory=False,
        fullscreen=False,
        gfx_backend="",
        disable_audio=True,
        save_replays=False,
    )
    if args.oracle_exiai:
        required_parameters = {"use_exi_inputs", "enable_ffw"}
        if not required_parameters.issubset(console_parameters):
            raise RuntimeError(
                "--oracle-exiai requires libmelee with ExiAI/FFW support "
                "(tested with melee 0.47.2)"
            )
        console_kwargs.update(
            gfx_backend="Null",
            use_exi_inputs=True,
            enable_ffw=not args.oracle_exiai_no_fast_forward,
            emulation_speed=0.0,
            online_delay=0,
        )
    console = melee.Console(**console_kwargs)
    if checkpoint_input_memory_probe_schema == 2:
        install_slippi_raw_pad_extension(console)
    if args.enable_items:
        enable_native_capsule_gecko(console)
    ucf_oracle_policy = (
        configure_ucf084_oracle(
            console,
            executable,
            iso,
            allow_native_capsule_spawning=args.enable_items,
        )
        if args.oracle_exiai
        else None
    )
    player_one = melee.Controller(console, 1, melee.ControllerType.STANDARD)
    player_two = melee.Controller(console, 2, melee.ControllerType.STANDARD)
    started_at = time.monotonic()
    connected_at: float | None = None
    menu_ready_at: float | None = None
    hook_ready_at: float | None = None
    memory_engine = None
    ucf_pad_hook_target: int | None = None

    try:
        environment = None
        if dolphin.is_file() and dolphin.name.lower().endswith(".appimage"):
            # WSL commonly lacks FUSE. AppImage's supported extraction fallback
            # keeps the oracle runnable without installing a kernel component.
            environment = {"APPIMAGE_EXTRACT_AND_RUN": "1"}
        if args.batch:
            dolphin_environment = os.environ.copy()
            if environment is not None:
                dolphin_environment.update(environment)
            # libmelee 0.44.0 does not expose Dolphin's --batch or null-video
            # switches. Preserve its process/home ownership while extending
            # only the launch command used by this reproducible oracle route.
            console._process = subprocess.Popen(
                [
                    str(executable),
                    "--batch",
                    "--video_backend=Null",
                    "--exec",
                    str(iso),
                    "--user",
                    console._get_dolphin_home_path(),
                ],
                env=dolphin_environment,
            )
        else:
            run_kwargs: dict[str, object] = {
                "iso_path": str(iso),
                "environment_vars": environment,
            }
            if "exe_name" in inspect.signature(console.run).parameters:
                run_kwargs["exe_name"] = executable.name
            console.run(**run_kwargs)
        wait_for_udp_listener(console.slippi_port, 30.0)
        if not console.connect():
            raise RuntimeError("Dolphin Slippi stream did not connect")
        if not player_one.connect() or not player_two.connect():
            raise RuntimeError("Dolphin controller pipes did not connect")
        connected_at = time.monotonic()

        gamestate = None
        items_configured = False
        menu_helper = melee.MenuHelper()
        modern_menu_helper = (
            "character" in inspect.signature(menu_helper.choose_stage).parameters
        )
        while time.monotonic() - started_at < args.menu_timeout:
            gamestate = console.step()
            if gamestate is None:
                continue
            if (
                args.enable_items
                and not items_configured
                and gamestate.menu_state == melee.Menu.MAIN_MENU
            ):
                memory_engine = wait_for_memory_engine_hook(executable)
                set_native_capsule_preferences(memory_engine)
                items_configured = True
            if (
                gamestate.menu_state in (melee.Menu.IN_GAME, melee.Menu.SUDDEN_DEATH)
                and gamestate.frame >= args.start_frame
                and 1 in gamestate.players
                and gamestate.players[1].character == melee.Character.CPTFALCON
            ):
                break
            choose_match(
                gamestate,
                player_one,
                player_two,
                (
                    melee.Stage.BATTLEFIELD
                    if (
                        args.platform_only
                        or args.platform_drop_ecb_only
                        or args.airborne_ecb_only
                        or args.aerial_attack_ecb_only
                        or args.aerial_attack_landing_only
                        or args.airborne_landing_only
                        or battlefield_checkpoint_route
                    )
                    else melee.Stage.FINAL_DESTINATION
                ),
                menu_helper,
                modern_menu_helper,
                (
                    melee.Character.CPTFALCON
                    if (
                        args.push_only
                        or args.shield_hit_only
                        or args.shield_collision_only
                        or args.moving_hit_sweep_only
                        or args.common_hurt_geometry_only
                        or args.damage_hit_only
                        or args.hitbox_geometry_only
                        or args.throw_geometry_only
                        or args.special_geometry_only
                        or powershield_special_route
                    )
                    else melee.Character.FOX
                ),
                stage_cursor=(
                    HYRULE_TEMPLE_STAGE_CURSOR if hyrule_stage_route else None
                ),
            )
        else:
            state = None if gamestate is None else str(gamestate.menu_state)
            raise TimeoutError(f"Dolphin match setup timed out in {state}")
        menu_ready_at = time.monotonic()

        if (
            args.memory_probe_shield
            or args.memory_probe_damage
            or args.memory_probe_input
            or args.memory_probe_hitbox
            or args.memory_probe_hurtbox
            or args.memory_probe_collision
            or args.memory_probe_surface
            or args.oracle_checkpoint_pack
            or ucf_oracle_policy is not None
        ):
            if memory_engine is None:
                memory_engine = wait_for_memory_engine_hook(executable)
            if (
                args.oracle_exiai
                and sys.platform.startswith("linux")
                and console._process is not None
            ):
                memory_engine = LinuxDolphinSharedMemory(
                    memory_engine,
                    console._process.pid,
                )
        if ucf_oracle_policy is not None:
            if memory_engine is None:
                raise RuntimeError("UCF oracle policy requires runtime memory proof")
            verify_ucf084_oracle(memory_engine, ucf_oracle_policy)
            if checkpoint_input_memory_probe_schema == 2:
                ucf_pad_hook_target = ucf084_runtime_hook_target(
                    memory_engine,
                    0x8006B460,
                )
        hook_ready_at = time.monotonic()
        stage_collision_memory = (
            read_stage_collision_memory_probe(memory_engine)
            if args.memory_probe_surface
            else None
        )

        if (
            args.special_geometry_move
            and "side_ground_item_hit" in args.special_geometry_move
        ):
            gamestate = wait_for_grounded_capsule(
                console,
                player_one,
                player_two,
                gamestate,
            )

        player_one.release_all()
        player_two.release_all()
        if args.special_acquisition_only:
            # Menu navigation can leave Falcon in a carried-over crouch when
            # the match first reaches the capture frame.  This domain needs a
            # neutral Wait checkpoint so every case can acquire its declared
            # source state independently.
            for _ in range(180):
                player_one.release_all()
                player_two.release_all()
                gamestate = console.step()
                if gamestate is None:
                    raise RuntimeError(
                        "missing game state while settling special acquisition"
                    )
                player = gamestate.players.get(1)
                if player is not None and player.action == melee.Action.STANDING:
                    break
            else:
                raise RuntimeError(
                    "special acquisition checkpoint did not settle to Wait"
                )
        checkpoint_probe = None
        checkpoint_pack_started_at = None
        checkpoint_pack_save_seconds = 0.0
        if args.oracle_checkpoint_probe:
            if console._process is None:
                raise RuntimeError("checkpoint probe requires a local Dolphin process")
            saved_game_frame = int(gamestate.frame)
            saved_position_x = float(gamestate.players[1].position.x)
            pending_checkpoint = begin_headless_checkpoint(
                console._process, "saved"
            )
            player_one.release_all()
            player_two.release_all()
            gamestate = console.step()
            if gamestate is None:
                raise RuntimeError("missing game state while saving checkpoint")
            save_seconds = finish_headless_checkpoint(
                console._process, pending_checkpoint
            )
            for _ in range(5):
                player_one.release_all()
                player_two.release_all()
                player_one.tilt_analog(melee.Button.BUTTON_MAIN, 1.0, 0.5)
                gamestate = console.step()
                if gamestate is None:
                    raise RuntimeError("missing game state during checkpoint probe")
            advanced_game_frame = int(gamestate.frame)
            advanced_position_x = float(gamestate.players[1].position.x)
            player_one.release_all()
            player_two.release_all()
            pending_checkpoint = begin_headless_checkpoint(
                console._process, "loaded"
            )
            gamestate = console.step()
            if gamestate is None:
                raise RuntimeError("missing game state after checkpoint restore")
            load_seconds = finish_headless_checkpoint(
                console._process, pending_checkpoint
            )
            restored_game_frame = int(gamestate.frame)
            restored_position_x = float(gamestate.players[1].position.x)
            for _ in range(5):
                player_one.release_all()
                player_two.release_all()
                player_one.tilt_analog(melee.Button.BUTTON_MAIN, 1.0, 0.5)
                gamestate = console.step()
                if gamestate is None:
                    raise RuntimeError(
                        "missing game state during repeated checkpoint probe"
                    )
            repeated_advanced_position_x = float(
                gamestate.players[1].position.x
            )
            player_one.release_all()
            player_two.release_all()
            pending_checkpoint = begin_headless_checkpoint(
                console._process, "loaded"
            )
            gamestate = console.step()
            if gamestate is None:
                raise RuntimeError(
                    "missing game state after repeated checkpoint restore"
                )
            repeated_load_seconds = finish_headless_checkpoint(
                console._process, pending_checkpoint
            )
            repeated_restored_position_x = float(
                gamestate.players[1].position.x
            )
            if (
                advanced_position_x <= saved_position_x + 0.01
                or abs(restored_position_x - saved_position_x) > 0.000001
                or repeated_advanced_position_x <= saved_position_x + 0.01
                or abs(repeated_restored_position_x - saved_position_x)
                > 0.000001
            ):
                raise RuntimeError(
                    "checkpoint did not restore the captured state: "
                    f"saved={saved_game_frame} advanced={advanced_game_frame} "
                    f"restored={restored_game_frame} "
                    f"saved_x={saved_position_x} advanced_x={advanced_position_x} "
                    f"restored_x={restored_position_x} "
                    f"repeated_advanced_x={repeated_advanced_position_x} "
                    f"repeated_restored_x={repeated_restored_position_x}"
                )
            checkpoint_probe = {
                "saved_game_frame": saved_game_frame,
                "advanced_game_frame": advanced_game_frame,
                "restored_game_frame": restored_game_frame,
                "saved_position_x": saved_position_x,
                "advanced_position_x": advanced_position_x,
                "restored_position_x": restored_position_x,
                "repeated_advanced_position_x": repeated_advanced_position_x,
                "repeated_restored_position_x": repeated_restored_position_x,
                "save_seconds": save_seconds,
                "load_seconds": load_seconds,
                "repeated_load_seconds": repeated_load_seconds,
            }
        elif args.oracle_checkpoint_pack:
            if console._process is None:
                raise RuntimeError("checkpoint pack requires a local Dolphin process")
            if memory_engine is None:
                raise RuntimeError("checkpoint pack requires memory placement")
            for checkpoint_slot in range(checkpoint_slot_count):
                pending_checkpoint = begin_headless_checkpoint(
                    console._process, "saved", slot=checkpoint_slot
                )
                player_one.release_all()
                player_two.release_all()
                gamestate = console.step()
                if gamestate is None:
                    raise RuntimeError(
                        "missing game state while saving checkpoint pack"
                    )
                checkpoint_pack_save_seconds += finish_headless_checkpoint(
                    console._process, pending_checkpoint
                )
            checkpoint_pack_started_at = time.monotonic()
        rows: list[dict[str, object]] = []
        origin_x: float | None = None
        origin_two_x: float | None = None
        falcon_frame_data = (
            json.loads(args.falcon_frame_data.read_text(encoding="utf-8"))
            if args.falcon_frame_data is not None
            else None
        )
        trace = input_trace(
            platform_only=args.platform_only,
            platform_drop_ecb_only=args.platform_drop_ecb_only,
            airborne_ecb_only=args.airborne_ecb_only,
            airborne_landing_only=args.airborne_landing_only,
            push_only=args.push_only,
            shield_only=args.shield_only,
            shield_break_orientation_only=args.shield_break_orientation_only,
            shield_geometry_only=args.shield_geometry_only,
            shield_geometry_sweep_only=args.shield_geometry_sweep_only,
            shield_guardon_landing_only=args.shield_guardon_landing_only,
            shield_hit_only=args.shield_hit_only,
            shield_collision_only=args.shield_collision_only,
            moving_hit_sweep_only=args.moving_hit_sweep_only,
            common_hurt_geometry_only=args.common_hurt_geometry_only,
            checkpoint_isolated=args.oracle_checkpoint_pack,
            damage_hit_only=args.damage_hit_only,
            defense_state_only=args.defense_state_only,
            special_acquisition_only=args.special_acquisition_only,
            attack_iasa_only=args.attack_iasa_only,
            aerial_iasa_only=args.aerial_iasa_only,
            aerial_attack_ecb_only=args.aerial_attack_ecb_only,
            aerial_attack_landing_only=args.aerial_attack_landing_only,
            ground_attack_iasa_only=args.ground_attack_iasa_only,
            hitbox_geometry_only=args.hitbox_geometry_only,
            throw_geometry_only=args.throw_geometry_only,
            special_geometry_only=args.special_geometry_only,
            ground_attack_moves=(
                tuple(args.ground_attack_move) if args.ground_attack_move else None
            ),
            special_geometry_moves=(
                tuple(args.special_geometry_move)
                if args.special_geometry_move
                else None
            ),
            falcon_frame_data=falcon_frame_data,
            checkpoint_capture_plan=checkpoint_capture_plan,
            selected_checkpoint_start_labels=selected_checkpoint_start_labels,
            shield_hit_pressure=args.shield_hit_pressure,
        )
        # libmelee's modern blocking-input scheduler applies each command to
        # the immediately returned post-frame. The legacy scheduler used by
        # our 0.40.1 captures reports it two frames later.
        pipeline_delay = (
            0
            if "use_exi_inputs" in console_parameters
            else 2
        )
        commands = trace + [
            {
                **trace[0],
                "label": "pipeline_drain",
                "fighter_x_from_item_offset": None,
                "opponent_x_from_item_offset": None,
                "fighter_x_override": None,
                "fighter_y_override": None,
                "fighter_facing_override": None,
                "fighter_damage_override": None,
                "fighter_self_velocity_x_override": None,
                "fighter_self_velocity_y_override": None,
                "fighter_knockback_velocity_x_override": None,
                "fighter_knockback_velocity_y_override": None,
                "fighter_position_state_reset": False,
                "opponent_x_override": None,
                "opponent_y_override": None,
                "opponent_facing_override": None,
                "opponent_position_state_reset": False,
                "source_random_seed_override": None,
            }
            for _ in range(pipeline_delay)
        ]

        def command_conditional_edges(
            trace_command: dict[str, object],
        ) -> tuple[dict[str, object], ...]:
            edge = trace_command.get("conditional_edge")
            if edge is None:
                return ()
            if isinstance(edge, dict):
                return (edge,)
            if isinstance(edge, (list, tuple)) and all(
                isinstance(item, dict) for item in edge
            ):
                return tuple(edge)
            raise RuntimeError("invalid generated conditional response edge")

        expected_conditional_edges = {
            str(edge["id"])
            for trace_command in trace
            for edge in command_conditional_edges(trace_command)
        }
        fired_conditional_edges: set[str] = set()
        conditional_edge_observations: dict[str, list[str]] = {
            edge_id: [] for edge_id in expected_conditional_edges
        }
        checkpoint_restore_seconds = 0.0
        checkpoint_case_labels: list[str] = []
        batch_exi_inputs = checkpoint_batch_inputs
        if batch_exi_inputs:
            # Switch only after menus and checkpoint setup are complete. Before
            # BATCH ON, Dolphin retains its established last-command-wins pipe
            # behavior, which collapses any menu-helper backlog. Afterwards,
            # every FLUSH-delimited sample is consumed on exactly one frame.
            player_one._write("BATCH ON\n")
            player_two._write("BATCH ON\n")
        buffered_input_frames = 0
        cliff_wait_fighter_address: int | None = None
        cliff_wait_recording_armed = False
        cliff_wait_recorded_timers: set[int] = set()
        cliff_wait_exit_recorded = False
        cliff_wait_timer_by_command_index: dict[int, int] = {}
        cliff_wait_exit_command_index: int | None = None
        cliff_wait_timer_jump_applied = False
        ledge_cooldown_fighter_address: int | None = None
        ledge_cooldown_recording_armed = False
        ledge_cooldown_by_command_index: dict[int, int] = {}

        def write_controller_sample(
            controller_sample: dict[str, object], *, flush: bool
        ) -> None:
            player_one.release_all()
            player_two.release_all()
            player_one.tilt_analog(
                melee.Button.BUTTON_MAIN,
                float(controller_sample["main_x"]),
                float(controller_sample["main_y"]),
            )
            player_one.tilt_analog(
                melee.Button.BUTTON_C,
                float(controller_sample["c_x"]),
                float(controller_sample["c_y"]),
            )
            player_one.press_shoulder(
                melee.Button.BUTTON_L,
                float(controller_sample["left_shoulder"]),
            )
            player_one.press_shoulder(
                melee.Button.BUTTON_R,
                float(controller_sample["right_shoulder"]),
            )
            for field, button in (
                ("digital_left", melee.Button.BUTTON_L),
                ("digital_right", melee.Button.BUTTON_R),
                ("jump", melee.Button.BUTTON_X),
                ("attack", melee.Button.BUTTON_A),
                ("special", melee.Button.BUTTON_B),
                ("grab", melee.Button.BUTTON_Z),
                ("taunt", melee.Button.BUTTON_D_UP),
            ):
                if bool(controller_sample[field]):
                    player_one.press_button(button)
            player_two.tilt_analog(
                melee.Button.BUTTON_MAIN,
                float(controller_sample["opponent_main_x"]),
                float(controller_sample["opponent_main_y"]),
            )
            if bool(controller_sample["opponent_attack"]):
                player_two.press_button(melee.Button.BUTTON_A)
            if bool(controller_sample["opponent_grab"]):
                player_two.press_button(melee.Button.BUTTON_Z)
            if bool(controller_sample["opponent_jump"]):
                player_two.press_button(melee.Button.BUTTON_X)
            if flush:
                player_one.flush()
                player_two.flush()

        def batch_safe(
            controller_sample: dict[str, object], command_index: int
        ) -> bool:
            edge_pending = any(
                str(edge["id"]) not in fired_conditional_edges
                for edge in command_conditional_edges(controller_sample)
            )
            return not (
                edge_pending
                or (
                    controller_sample.get("cliff_wait_timer_jump") is not None
                    and not cliff_wait_timer_jump_applied
                )
                or command_index in cliff_wait_timer_by_command_index
                or command_index == cliff_wait_exit_command_index
                or command_index in ledge_cooldown_by_command_index
                or bool(controller_sample.get("restore_before", False))
                or controller_sample.get("fighter_x_from_item_offset") is not None
                or controller_sample.get("opponent_x_from_item_offset") is not None
                or controller_sample.get("fighter_x_override") is not None
                or controller_sample.get("fighter_y_override") is not None
                or controller_sample.get("fighter_facing_override") is not None
                or controller_sample.get("fighter_damage_override") is not None
                or controller_sample.get("fighter_self_velocity_x_override")
                is not None
                or controller_sample.get("fighter_self_velocity_y_override")
                is not None
                or controller_sample.get(
                    "fighter_knockback_velocity_x_override"
                )
                is not None
                or controller_sample.get(
                    "fighter_knockback_velocity_y_override"
                )
                is not None
                or bool(controller_sample.get("fighter_position_state_reset", False))
                or controller_sample.get("opponent_x_override") is not None
                or controller_sample.get("opponent_y_override") is not None
                or controller_sample.get("opponent_facing_override") is not None
                or bool(
                    controller_sample.get("opponent_position_state_reset", False)
                )
                or controller_sample.get("source_random_seed_override") is not None
            )

        def apply_memory_overrides(
            fighter_overrides: tuple[tuple[int, int, object], ...],
            source_random_seed_override: object,
        ) -> None:
            if any(value is not None for _, _, value in fighter_overrides):
                if memory_engine is None:
                    raise RuntimeError(
                        "fighter state override requires a memory probe"
                    )
                fighter_addresses = (
                    read_fighter_address(memory_engine, 0),
                    read_fighter_address(memory_engine, 1),
                )
                for fighter_index, fighter_address in enumerate(
                    fighter_addresses
                ):
                    writes = sorted(
                        (offset, float(value))
                        for owner, offset, value in fighter_overrides
                        if owner == fighter_index and value is not None
                    )
                    while writes:
                        first_offset, first_value = writes.pop(0)
                        values = [first_value]
                        next_offset = first_offset + 4
                        while writes and writes[0][0] == next_offset:
                            _, value = writes.pop(0)
                            values.append(value)
                            next_offset += 4
                        memory_engine.write_bytes(
                            fighter_address + first_offset,
                            b"".join(struct.pack(">f", value) for value in values),
                        )
            if source_random_seed_override is not None:
                if memory_engine is None:
                    raise RuntimeError(
                        "source RNG initialization requires a memory probe"
                    )
                seed_pointer = memory_engine.read_word(
                    HSD_RANDOM_SEED_POINTER_ADDRESS
                )
                if seed_pointer != HSD_RANDOM_SEED_ADDRESS:
                    raise RuntimeError(
                        "unexpected HSD random seed pointer: "
                        f"0x{seed_pointer:08x}"
                    )
                memory_engine.write_word(
                    HSD_RANDOM_SEED_ADDRESS,
                    source_random_seed_override,
                )
                restored_seed = memory_engine.read_word(
                    HSD_RANDOM_SEED_ADDRESS
                )
                if restored_seed != source_random_seed_override:
                    raise RuntimeError(
                        "failed to initialize HSD random seed: "
                        f"0x{restored_seed:08x}"
                    )

        for command_index, sample in enumerate(commands):
            if bool(sample.get("restore_before", False)):
                if console._process is None:
                    raise RuntimeError(
                        "checkpoint-isolated trace requires local Dolphin"
                    )
                case_number = len(checkpoint_case_labels) + 1
                case_started_at = time.monotonic()
                checkpoint_slot = int(sample.get("checkpoint_slot", 0))
                if args.oracle_checkpoint_pack:
                    print(
                        "ssbm-checkpoint-case="
                        f"{case_number}/"
                        f"{sum(bool(row.get('restore_before')) for row in trace)} "
                        f"label={sample['label']} slot={checkpoint_slot}",
                        file=sys.stderr,
                        flush=True,
                    )

                if buffered_input_frames != 0:
                    raise RuntimeError(
                        "checkpoint boundary reached with buffered EXI inputs"
                    )
                checkpoint_request = begin_headless_checkpoint(
                    console._process,
                    "loaded",
                    slot=checkpoint_slot,
                )
                player_one.release_all()
                player_two.release_all()
                gamestate = console.step()
                if (
                    gamestate is None
                    or 1 not in gamestate.players
                    or 2 not in gamestate.players
                ):
                    raise RuntimeError(
                        "missing player state at checkpoint restore boundary"
                    )
                try:
                    checkpoint_restore_seconds += finish_headless_checkpoint(
                        console._process,
                        checkpoint_request,
                    )
                except Exception as error:
                    raise RuntimeError(
                        "checkpoint restore failed before case "
                        f"{case_number} ({sample['label']})"
                    ) from error
                origin_x = None
                origin_two_x = None
                cliff_wait_fighter_address = None
                cliff_wait_recording_armed = False
                cliff_wait_recorded_timers.clear()
                cliff_wait_exit_recorded = False
                cliff_wait_timer_by_command_index.clear()
                cliff_wait_exit_command_index = None
                cliff_wait_timer_jump_applied = False
                ledge_cooldown_fighter_address = None
                ledge_cooldown_recording_armed = False
                ledge_cooldown_by_command_index.clear()
                checkpoint_case_labels.append(str(sample["label"]))
                if args.oracle_checkpoint_pack:
                    print(
                        "ssbm-checkpoint-restore=pass "
                        f"case={len(checkpoint_case_labels)} seconds="
                        f"{time.monotonic() - case_started_at:.6f}",
                        file=sys.stderr,
                        flush=True,
                    )
            conditional_edge_fired_now = False
            conditional_edges = command_conditional_edges(sample)
            if conditional_edges:
                if pipeline_delay != 0:
                    raise RuntimeError(
                        "conditional response edges require the zero-delay "
                        "EXI input pipeline"
                    )
                player_before_step = gamestate.players.get(1)
                opponent_before_step = gamestate.players.get(2)
                for conditional_edge in conditional_edges:
                    edge_id = str(conditional_edge["id"])
                    edge_owner = conditional_edge.get("owner", "fighter")
                    edge_player = (
                        opponent_before_step
                        if edge_owner == "opponent"
                        else player_before_step
                    )
                    if (
                        edge_id not in fired_conditional_edges
                        and edge_player is not None
                        and len(conditional_edge_observations[edge_id]) < 16
                    ):
                        conditional_edge_observations[edge_id].append(
                            f"{edge_owner}:{edge_player.action.name}:"
                            f"{int(edge_player.action_frame)}"
                        )
                    if (
                        edge_id not in fired_conditional_edges
                        and edge_player is not None
                        and edge_player.action.name
                        == conditional_edge["action"]
                        and int(edge_player.action_frame)
                        == conditional_edge["frame"]
                    ):
                        sample.update(conditional_edge["inputs"])
                        sample["label"] = f"{sample['label']}_edge"
                        fired_conditional_edges.add(edge_id)
                        conditional_edge_fired_now = True
            if buffered_input_frames == 0:
                if (
                    batch_exi_inputs
                    and not conditional_edge_fired_now
                    and batch_safe(sample, command_index)
                ):
                    batch: list[dict[str, object]] = []
                    for candidate_index, candidate in enumerate(
                        commands[command_index : command_index + 64],
                        command_index,
                    ):
                        if not batch_safe(candidate, candidate_index):
                            break
                        batch.append(candidate)
                    for candidate in batch:
                        write_controller_sample(candidate, flush=True)
                    buffered_input_frames = len(batch)
                else:
                    write_controller_sample(sample, flush=False)
            fighter_x_override = sample["fighter_x_override"]
            opponent_x_override = sample["opponent_x_override"]
            if sample["fighter_x_from_item_offset"] is not None:
                if not gamestate.projectiles:
                    raise RuntimeError(
                        "item-relative fighter position requires a live item"
                    )
                fighter_x_override = float(gamestate.projectiles[0].position.x) + float(
                    sample["fighter_x_from_item_offset"]
                )
            if sample["opponent_x_from_item_offset"] is not None:
                if not gamestate.projectiles:
                    raise RuntimeError(
                        "item-relative opponent position requires a live item"
                    )
                opponent_x_override = float(
                    gamestate.projectiles[0].position.x
                ) + float(sample["opponent_x_from_item_offset"])
            fighter_overrides = (
                (0, 0xB0, fighter_x_override),
                (0, 0xB4, sample["fighter_y_override"]),
                (0, 0x2C, sample["fighter_facing_override"]),
                (0, 0x1830, sample["fighter_damage_override"]),
                (0, 0x80, sample["fighter_self_velocity_x_override"]),
                (0, 0x84, sample["fighter_self_velocity_y_override"]),
                (0, 0x8C, sample["fighter_knockback_velocity_x_override"]),
                (0, 0x90, sample["fighter_knockback_velocity_y_override"]),
                (1, 0xB0, opponent_x_override),
                (1, 0xB4, sample["opponent_y_override"]),
                (1, 0x2C, sample["opponent_facing_override"]),
            )
            if bool(sample["fighter_position_state_reset"]):
                if fighter_x_override is None or sample["fighter_y_override"] is None:
                    raise RuntimeError(
                        "fighter position-state reset requires x and y overrides"
                    )
                reset_x = float(fighter_x_override)
                reset_y = float(sample["fighter_y_override"])
                fighter_overrides += (
                    (0, 0xBC, reset_x),
                    (0, 0xC0, reset_y),
                    (0, 0xC8, 0.0),
                    (0, 0xCC, 0.0),
                    (0, 0x6F4, reset_x),
                    (0, 0x6F8, reset_y),
                    (0, 0x700, reset_x),
                    (0, 0x704, reset_y),
                    (0, 0x70C, reset_x),
                    (0, 0x710, reset_y),
                    (0, 0x718, reset_x),
                    (0, 0x71C, reset_y),
                )
            if bool(sample["opponent_position_state_reset"]):
                if (
                    opponent_x_override is None
                    or sample["opponent_y_override"] is None
                ):
                    raise RuntimeError(
                        "opponent position-state reset requires x and y overrides"
                    )
                reset_x = float(opponent_x_override)
                reset_y = float(sample["opponent_y_override"])
                fighter_overrides += (
                    (1, 0xBC, reset_x),
                    (1, 0xC0, reset_y),
                    (1, 0xC8, 0.0),
                    (1, 0xCC, 0.0),
                    (1, 0x6F4, reset_x),
                    (1, 0x6F8, reset_y),
                    (1, 0x700, reset_x),
                    (1, 0x704, reset_y),
                    (1, 0x70C, reset_x),
                    (1, 0x710, reset_y),
                    (1, 0x718, reset_x),
                    (1, 0x71C, reset_y),
                )
            source_random_seed_override = sample[
                "source_random_seed_override"
            ]
            apply_memory_overrides(
                fighter_overrides, source_random_seed_override
            )
            input_was_buffered = buffered_input_frames != 0
            if input_was_buffered:
                attached_controllers = console.controllers
                console.controllers = []
                try:
                    gamestate = console.step()
                finally:
                    console.controllers = attached_controllers
                buffered_input_frames -= 1
            else:
                gamestate = console.step()
            if (
                gamestate is None
                or 1 not in gamestate.players
                or 2 not in gamestate.players
            ):
                raise RuntimeError(
                    f"missing player state at command frame {command_index}"
                )
            if command_index < pipeline_delay:
                continue
            index = command_index - pipeline_delay
            scheduled = trace[index]
            player = gamestate.players[1]
            player_two_state = gamestate.players[2]
            observed_x = float(player.controller_state.main_stick[0])
            observed_y = float(player.controller_state.main_stick[1])
            observed_raw_main_x = int(
                player.controller_state.raw_main_stick[0]
            )
            observed_raw_main_y = int(
                player.controller_state.raw_main_stick[1]
            )
            raw_c_by_port = getattr(console, "_pf_raw_c_stick_by_port", {})
            raw_c_stick = raw_c_by_port.get(1)
            if checkpoint_input_memory_probe_schema == 2 and (
                not isinstance(raw_c_stick, tuple)
                or len(raw_c_stick) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or not -128 <= value <= 127
                    for value in raw_c_stick
                )
            ):
                raise RuntimeError("Slippi raw C-stick observation is missing")
            observed_raw_c_x = int(raw_c_stick[0]) if raw_c_stick else 0
            observed_raw_c_y = int(raw_c_stick[1]) if raw_c_stick else 0
            observed_c_x = float(player.controller_state.c_stick[0])
            observed_c_y = float(player.controller_state.c_stick[1])
            observed_left_shoulder = float(player.controller_state.l_shoulder)
            observed_right_shoulder = float(player.controller_state.r_shoulder)
            observed_digital_left = bool(
                player.controller_state.button[melee.Button.BUTTON_L]
            )
            observed_digital_right = bool(
                player.controller_state.button[melee.Button.BUTTON_R]
            )
            observed_jump = bool(
                player.controller_state.button[melee.Button.BUTTON_X]
                or player.controller_state.button[melee.Button.BUTTON_Y]
            )
            observed_attack = bool(
                player.controller_state.button[melee.Button.BUTTON_A]
            )
            observed_special = bool(
                player.controller_state.button[melee.Button.BUTTON_B]
            )
            observed_grab = bool(player.controller_state.button[melee.Button.BUTTON_Z])
            observed_taunt = bool(
                player.controller_state.button[melee.Button.BUTTON_D_UP]
            )
            observed_opponent_x = float(player_two_state.controller_state.main_stick[0])
            observed_opponent_y = float(player_two_state.controller_state.main_stick[1])
            observed_opponent_attack = bool(
                player_two_state.controller_state.button[melee.Button.BUTTON_A]
            )
            observed_opponent_grab = bool(
                player_two_state.controller_state.button[melee.Button.BUTTON_Z]
            )
            requested_x = float(scheduled["main_x"])
            requested_y = float(scheduled["main_y"])
            requested_c_x = float(scheduled["c_x"])
            requested_c_y = float(scheduled["c_y"])
            input_memory_sample: dict[str, int | float] | None = None
            alignment_x = observed_x
            alignment_y = observed_y
            alignment_c_x = observed_c_x
            alignment_c_y = observed_c_y
            if args.memory_probe_input and checkpoint_input_memory_probe_schema == 2:
                input_memory_sample = read_input_memory_probe(
                    memory_engine,
                    schema=checkpoint_input_memory_probe_schema,
                    ucf_pad_hook_target=ucf_pad_hook_target,
                )
                alignment_x = (
                    float(input_memory_sample["pad_processed_main_x"]) + 1.0
                ) * 0.5
                alignment_y = (
                    float(input_memory_sample["pad_processed_main_y"]) + 1.0
                ) * 0.5
                alignment_c_x = (
                    float(input_memory_sample["pad_processed_c_x"]) + 1.0
                ) * 0.5
                alignment_c_y = (
                    float(input_memory_sample["pad_processed_c_y"]) + 1.0
                ) * 0.5
            axis_aligned = (
                (requested_x == 0.5 and abs(alignment_x - 0.5) <= 0.02)
                or (abs(requested_x - 0.5) <= 0.02 and abs(alignment_x - 0.5) <= 0.02)
                or (requested_x < 0.5 and alignment_x < 0.5)
                or (requested_x > 0.5 and alignment_x > 0.5)
            ) and (
                (requested_y == 0.5 and abs(alignment_y - 0.5) <= 0.02)
                or (abs(requested_y - 0.5) <= 0.02 and abs(alignment_y - 0.5) <= 0.02)
                or (requested_y < 0.5 and alignment_y < 0.5)
                or (requested_y > 0.5 and alignment_y > 0.5)
            )
            if args.shield_geometry_sweep_only:
                # The game's per-axis dead zone intentionally collapses small
                # sweep components to neutral. The recorded post-frame sample
                # remains the authoritative input for this extraction route.
                axis_aligned = True
            # Melee reports sub-0.2 C-stick components as neutral. Preserve
            # that expected collapse so threshold-negative routes can still
            # prove the requested raw input and observed source response.
            c_axis_aligned = (
                (requested_c_x == 0.5 and abs(alignment_c_x - 0.5) <= 0.02)
                or (
                    abs(requested_c_x - 0.5) < 0.10
                    and abs(alignment_c_x - 0.5) <= 0.02
                )
                or (requested_c_x < 0.5 and alignment_c_x < 0.5)
                or (requested_c_x > 0.5 and alignment_c_x > 0.5)
            ) and (
                (requested_c_y == 0.5 and abs(alignment_c_y - 0.5) <= 0.02)
                or (
                    abs(requested_c_y - 0.5) < 0.10
                    and abs(alignment_c_y - 0.5) <= 0.02
                )
                or (requested_c_y < 0.5 and alignment_c_y < 0.5)
                or (requested_c_y > 0.5 and alignment_c_y > 0.5)
            )
            # The Slippi post-frame payload exposes the aggregate analog
            # shoulder pressure on both ControllerState shoulder fields. The
            # digital L/R bits remain independent, so validate the aggregate
            # analog amount and both digital clicks separately.
            requested_analog_shoulder = max(
                float(scheduled["left_shoulder"]),
                float(scheduled["right_shoulder"]),
            )
            expected_observed_shoulder = (
                1.0
                if bool(scheduled["digital_left"])
                or bool(scheduled["digital_right"])
                else (
                    0.35
                    if bool(scheduled["grab"])
                    else (
                        0.0
                        if requested_analog_shoulder <= 0.30
                        else requested_analog_shoulder
                    )
                )
            )
            shoulder_aligned = (
                abs(
                    max(observed_left_shoulder, observed_right_shoulder)
                    - expected_observed_shoulder
                )
                <= 0.10
                and observed_digital_left == bool(scheduled["digital_left"])
                and observed_digital_right == bool(scheduled["digital_right"])
                and observed_jump == bool(scheduled["jump"])
                and observed_attack == bool(scheduled["attack"])
                and observed_special == bool(scheduled["special"])
                and observed_grab == bool(scheduled["grab"])
                and observed_taunt == bool(scheduled["taunt"])
            )
            requested_opponent_x = float(scheduled["opponent_main_x"])
            requested_opponent_y = float(scheduled["opponent_main_y"])
            opponent_axis_aligned = (
                (requested_opponent_x == 0.5 and abs(observed_opponent_x - 0.5) <= 0.02)
                or (requested_opponent_x < 0.5 and observed_opponent_x < 0.5)
                or (requested_opponent_x > 0.5 and observed_opponent_x > 0.5)
            ) and (
                (requested_opponent_y == 0.5 and abs(observed_opponent_y - 0.5) <= 0.02)
                or (requested_opponent_y < 0.5 and observed_opponent_y < 0.5)
                or (requested_opponent_y > 0.5 and observed_opponent_y > 0.5)
            )
            aligned = (
                axis_aligned
                and c_axis_aligned
                and shoulder_aligned
                and opponent_axis_aligned
                and observed_opponent_attack == bool(scheduled["opponent_attack"])
                and observed_opponent_grab == bool(scheduled["opponent_grab"])
            )
            if not aligned:
                raise RuntimeError(
                    "controller/post-frame alignment failed at trace frame "
                    f"{index}: requested={scheduled} "
                    "observed="
                    f"x={observed_x} y={observed_y} "
                    f"cx={observed_c_x} cy={observed_c_y} "
                    f"l={observed_left_shoulder}/{observed_digital_left} "
                    f"r={observed_right_shoulder}/{observed_digital_right} "
                    f"jump={observed_jump} attack={observed_attack} "
                    f"special={observed_special} grab={observed_grab} "
                    f"taunt={observed_taunt} "
                    f"opponent_x={observed_opponent_x} "
                    f"opponent_y={observed_opponent_y} "
                    f"opponent_attack={observed_opponent_attack}"
                    f" opponent_grab={observed_opponent_grab}"
                )
            if not bool(scheduled.get("record", True)):
                continue
            record_actions = scheduled.get("record_actions")
            if (
                record_actions is not None
                and player.action.name not in record_actions
            ):
                continue
            cliff_wait_timer: int | None = None
            record_cliff_wait_timers = scheduled.get(
                "record_cliff_wait_timers"
            )
            if record_cliff_wait_timers is not None:
                if memory_engine is None:
                    raise RuntimeError(
                        "CliffWait timer sampling requires a memory probe"
                    )
                if player.action.name == "EDGE_HANGING":
                    cliff_wait_timer_jump = scheduled.get(
                        "cliff_wait_timer_jump"
                    )
                    expected_timer = cliff_wait_timer_by_command_index.get(
                        command_index
                    )
                    if cliff_wait_recording_armed and expected_timer is None:
                        if (
                            cliff_wait_timer_jump is not None
                            and not cliff_wait_timer_jump_applied
                            and not bool(player.invulnerable)
                            and int(player.action_frame)
                            == int(
                                cliff_wait_timer_jump[
                                    "write_on_action_frame"
                                ]
                            )
                        ):
                            if cliff_wait_fighter_address is None:
                                cliff_wait_fighter_address = (
                                    read_fighter_address(memory_engine, 0)
                                )
                            jump_value = int(cliff_wait_timer_jump["value"])
                            pre_jump_timer = memory_engine.read_float(
                                cliff_wait_fighter_address + 0x2344
                            )
                            if pre_jump_timer <= float(jump_value):
                                raise RuntimeError(
                                    "CliffWait timer jump did not skip a "
                                    f"positive interval: {pre_jump_timer}"
                                )
                            memory_engine.write_float(
                                cliff_wait_fighter_address + 0x2344,
                                float(jump_value),
                            )
                            restored_jump_timer = memory_engine.read_float(
                                cliff_wait_fighter_address + 0x2344
                            )
                            if abs(restored_jump_timer - jump_value) > 0.001:
                                raise RuntimeError(
                                    "failed to apply CliffWait timer jump: "
                                    f"{restored_jump_timer}"
                                )
                            for requested_timer in record_cliff_wait_timers:
                                if requested_timer < jump_value:
                                    cliff_wait_timer_by_command_index[
                                        command_index
                                        + jump_value
                                        - requested_timer
                                    ] = requested_timer
                            cliff_wait_exit_command_index = (
                                command_index + jump_value
                            )
                            cliff_wait_timer_jump_applied = True
                        continue
                    if cliff_wait_fighter_address is None:
                        cliff_wait_fighter_address = read_fighter_address(
                            memory_engine, 0
                        )
                    raw_cliff_wait_timer = memory_engine.read_float(
                        cliff_wait_fighter_address + 0x2344
                    )
                    cliff_wait_timer = round(raw_cliff_wait_timer)
                    if abs(raw_cliff_wait_timer - cliff_wait_timer) > 0.001:
                        raise RuntimeError(
                            "non-integral CliffWait timer observed: "
                            f"{raw_cliff_wait_timer}"
                        )
                    if expected_timer is not None and cliff_wait_timer != expected_timer:
                        raise RuntimeError(
                            "CliffWait timer sampling lost frame alignment: "
                            f"expected {expected_timer}, observed {cliff_wait_timer}"
                        )
                    if not cliff_wait_recording_armed:
                        if cliff_wait_timer not in record_cliff_wait_timers:
                            raise RuntimeError(
                                "initial CliffWait timer was not declared: "
                                f"{cliff_wait_timer}"
                            )
                        if cliff_wait_timer_jump is None:
                            for requested_timer in record_cliff_wait_timers:
                                if requested_timer < cliff_wait_timer:
                                    cliff_wait_timer_by_command_index[
                                        command_index
                                        + cliff_wait_timer
                                        - requested_timer
                                    ] = requested_timer
                            cliff_wait_exit_command_index = (
                                command_index + cliff_wait_timer
                            )
                    cliff_wait_recording_armed = True
                    cliff_wait_recorded_timers.add(cliff_wait_timer)
                elif player.action.name in {"FALLING", "TUMBLING"}:
                    if (
                        not cliff_wait_recording_armed
                        or cliff_wait_exit_recorded
                        or command_index != cliff_wait_exit_command_index
                    ):
                        continue
                    cliff_wait_timer = 0
                    cliff_wait_exit_recorded = True
                else:
                    continue
            ledge_regrab_cooldown: int | None = None
            record_ledge_regrab_cooldowns = scheduled.get(
                "record_ledge_regrab_cooldowns"
            )
            if record_ledge_regrab_cooldowns is not None:
                if memory_engine is None:
                    raise RuntimeError(
                        "ledge regrab cooldown sampling requires a memory probe"
                    )
                expected_cooldown = ledge_cooldown_by_command_index.get(
                    command_index
                )
                if (
                    not ledge_cooldown_recording_armed
                    and not conditional_edge_fired_now
                ):
                    continue
                if ledge_cooldown_recording_armed and expected_cooldown is None:
                    continue
                if ledge_cooldown_fighter_address is None:
                    ledge_cooldown_fighter_address = read_fighter_address(
                        memory_engine, 0
                    )
                ledge_regrab_cooldown = memory_engine.read_word(
                    ledge_cooldown_fighter_address + 0x2064
                )
                if (
                    expected_cooldown is not None
                    and ledge_regrab_cooldown != expected_cooldown
                ):
                    raise RuntimeError(
                        "ledge regrab cooldown sampling lost frame alignment: "
                        f"expected {expected_cooldown}, observed "
                        f"{ledge_regrab_cooldown}"
                    )
                if not ledge_cooldown_recording_armed:
                    if ledge_regrab_cooldown not in (
                        record_ledge_regrab_cooldowns
                    ):
                        raise RuntimeError(
                            "initial ledge regrab cooldown was not declared: "
                            f"{ledge_regrab_cooldown}"
                        )
                    for requested_cooldown in record_ledge_regrab_cooldowns:
                        if requested_cooldown < ledge_regrab_cooldown:
                            ledge_cooldown_by_command_index[
                                command_index
                                + ledge_regrab_cooldown
                                - requested_cooldown
                            ] = requested_cooldown
                    ledge_cooldown_recording_armed = True
            if origin_x is None:
                origin_x = player.position.x
            if origin_two_x is None:
                origin_two_x = player_two_state.position.x
            row = {
                "trace_frame": index,
                "game_frame": int(gamestate.frame),
                "label": scheduled["label"],
                "requested_main_x": requested_x,
                "requested_main_y": requested_y,
                "requested_c_x": requested_c_x,
                "requested_c_y": requested_c_y,
                "requested_left_shoulder": float(scheduled["left_shoulder"]),
                "requested_right_shoulder": float(scheduled["right_shoulder"]),
                "requested_digital_left": bool(scheduled["digital_left"]),
                "requested_digital_right": bool(scheduled["digital_right"]),
                "requested_jump": bool(scheduled["jump"]),
                "requested_attack": bool(scheduled["attack"]),
                "requested_special": bool(scheduled["special"]),
                "requested_grab": bool(scheduled["grab"]),
                "requested_taunt": bool(scheduled["taunt"]),
                "requested_opponent_main_x": requested_opponent_x,
                "requested_opponent_main_y": requested_opponent_y,
                "requested_opponent_attack": bool(scheduled["opponent_attack"]),
                "requested_opponent_grab": bool(scheduled["opponent_grab"]),
                "requested_opponent_jump": bool(scheduled["opponent_jump"]),
                "requested_fighter_y_override": scheduled["fighter_y_override"],
                "requested_fighter_facing_override": scheduled[
                    "fighter_facing_override"
                ],
                "requested_fighter_damage_override": scheduled[
                    "fighter_damage_override"
                ],
                "requested_fighter_x_override": scheduled["fighter_x_override"],
                "requested_fighter_self_velocity_x_override": scheduled[
                    "fighter_self_velocity_x_override"
                ],
                "requested_fighter_self_velocity_y_override": scheduled[
                    "fighter_self_velocity_y_override"
                ],
                "requested_fighter_knockback_velocity_x_override": scheduled[
                    "fighter_knockback_velocity_x_override"
                ],
                "requested_fighter_knockback_velocity_y_override": scheduled[
                    "fighter_knockback_velocity_y_override"
                ],
                "requested_fighter_position_state_reset": scheduled[
                    "fighter_position_state_reset"
                ],
                "requested_opponent_x_override": scheduled["opponent_x_override"],
                "requested_opponent_y_override": scheduled["opponent_y_override"],
                "requested_opponent_facing_override": scheduled[
                    "opponent_facing_override"
                ],
                "observed_main_x": observed_x,
                "observed_main_y": observed_y,
                "observed_raw_main_x": observed_raw_main_x,
                "observed_raw_main_y": observed_raw_main_y,
                **(
                    {
                        "observed_raw_c_x": observed_raw_c_x,
                        "observed_raw_c_y": observed_raw_c_y,
                    }
                    if checkpoint_input_memory_probe_schema == 2
                    else {}
                ),
                "observed_c_x": observed_c_x,
                "observed_c_y": observed_c_y,
                "observed_left_shoulder": observed_left_shoulder,
                "observed_right_shoulder": observed_right_shoulder,
                "observed_analog_shoulder": max(
                    observed_left_shoulder,
                    observed_right_shoulder,
                ),
                "observed_digital_left": observed_digital_left,
                "observed_digital_right": observed_digital_right,
                "observed_jump": observed_jump,
                "observed_attack": observed_attack,
                "observed_special": observed_special,
                "observed_grab": observed_grab,
                "observed_taunt": observed_taunt,
                "observed_opponent_main_x": observed_opponent_x,
                "observed_opponent_main_y": observed_opponent_y,
                "observed_opponent_attack": observed_opponent_attack,
                "observed_opponent_grab": observed_opponent_grab,
                "action": player.action.name,
                "action_value": int(player.action.value),
                "action_frame": float(player.action_frame),
                "facing": 1 if player.facing else -1,
                "grounded": bool(player.on_ground),
                "position_x": float(player.position.x),
                "position_x_from_origin": float(player.position.x - origin_x),
                "position_y": float(player.position.y),
                "ground_velocity_x": float(player.speed_ground_x_self),
                "air_velocity_x": float(player.speed_air_x_self),
                "velocity_y": float(player.speed_y_self),
                "attack_velocity_x": float(player.speed_x_attack),
                "attack_velocity_y": float(player.speed_y_attack),
                "hitlag_left": float(player.hitlag_left),
                "hitstun_left": float(player.hitstun_frames_left),
                "invulnerable": bool(player.invulnerable),
                "invulnerability_left": int(player.invulnerability_left),
                "iasa": bool(player.iasa),
                "damage_percent": float(player.percent),
                "shield_health": float(player.shield_strength),
                "opponent_action": player_two_state.action.name,
                "opponent_action_value": int(player_two_state.action.value),
                "opponent_action_frame": float(player_two_state.action_frame),
                "opponent_facing": (1 if player_two_state.facing else -1),
                "opponent_grounded": bool(player_two_state.on_ground),
                "opponent_position_x": float(player_two_state.position.x),
                "opponent_position_x_from_origin": float(
                    player_two_state.position.x - origin_two_x
                ),
                "opponent_position_y": float(player_two_state.position.y),
                "opponent_ground_velocity_x": float(
                    player_two_state.speed_ground_x_self
                ),
                "opponent_air_velocity_x": float(player_two_state.speed_air_x_self),
                "opponent_velocity_y": float(player_two_state.speed_y_self),
                "opponent_attack_velocity_x": float(player_two_state.speed_x_attack),
                "opponent_attack_velocity_y": float(player_two_state.speed_y_attack),
                "opponent_hitlag_left": float(player_two_state.hitlag_left),
                "opponent_hitstun_left": float(player_two_state.hitstun_frames_left),
                "opponent_damage_percent": float(player_two_state.percent),
                "projectiles": [
                    {
                        "type": int(projectile.type.value),
                        "subtype": int(projectile.subtype),
                        "x": float(projectile.position.x),
                        "y": float(projectile.position.y),
                        "velocity_x": float(projectile.speed.x),
                        "velocity_y": float(projectile.speed.y),
                        "owner": int(projectile.owner),
                        "frame": int(projectile.frame),
                    }
                    for projectile in gamestate.projectiles
                ],
            }
            if cliff_wait_timer is not None:
                row["cliff_wait_timer"] = cliff_wait_timer
            if ledge_regrab_cooldown is not None:
                row["ledge_regrab_cooldown"] = ledge_regrab_cooldown
            if memory_engine is not None:
                if args.memory_probe_shield:
                    row["shield_memory"] = read_shield_memory_probe(memory_engine)
                if args.memory_probe_damage:
                    row["damage_memory"] = read_damage_memory_probe(memory_engine)
                if args.memory_probe_input:
                    row["input_memory"] = (
                        input_memory_sample
                        if input_memory_sample is not None
                        else read_input_memory_probe(memory_engine)
                    )
                if args.memory_probe_hitbox:
                    row["hitbox_memory"] = read_hitbox_memory_probe(memory_engine)
                if args.memory_probe_hurtbox:
                    row["hurtbox_memory"] = read_hurtbox_memory_probe(memory_engine)
                if args.memory_probe_collision:
                    row["shield_memory"] = read_shield_memory_probe(memory_engine)
                    row["hitbox_memory"] = read_hitbox_memory_probe(memory_engine)
                if (
                    args.memory_probe_surface
                    and checkpoint_record_surface_rows
                    and not input_was_buffered
                ):
                    row["surface_collision_memory"] = (
                        read_surface_collision_memory_probe(
                            memory_engine,
                            include_capture_constraint_state=(
                                args.throw_geometry_only
                            ),
                        )
                    )
                    if args.throw_geometry_only:
                        row["opponent_surface_collision_memory"] = (
                            read_surface_collision_memory_probe(
                                memory_engine,
                                player_index=1,
                                include_capture_constraint_state=True,
                            )
                        )
            rows.append(row)

        missing_conditional_edges = (
            expected_conditional_edges - fired_conditional_edges
        )
        if missing_conditional_edges:
            raise RuntimeError(
                "conditional response edges did not fire: "
                + ",".join(
                    f"{edge_id}[{','.join(conditional_edge_observations[edge_id])}]"
                    for edge_id in sorted(missing_conditional_edges)
                )
            )
        item_rules = (
            read_native_item_rules(memory_engine)
            if args.enable_items and memory_engine is not None
            else None
        )
        checkpoint_pack_warm_seconds = (
            time.monotonic() - checkpoint_pack_started_at
            if checkpoint_pack_started_at is not None
            else None
        )
        if checkpoint_pack_warm_seconds is not None:
            print(
                "ssbm-checkpoint-pack-time "
                f"warm_seconds={checkpoint_pack_warm_seconds:.6f} "
                f"save_seconds={checkpoint_pack_save_seconds:.6f} "
                f"restore_seconds={checkpoint_restore_seconds:.6f}",
                file=sys.stderr,
                flush=True,
            )
        checkpoint_pack = (
            {
                "protocol": (
                    checkpoint_coverage_manifest.get("checkpoint_pack", {}).get(
                        "protocol", "rebased-slippi-state-file-control-v1"
                    )
                    if isinstance(checkpoint_coverage_manifest, dict)
                    else "rebased-slippi-state-file-control-v1"
                ),
                "slot_count": checkpoint_slot_count,
                "case_count": len(checkpoint_case_labels),
                "case_start_labels": checkpoint_case_labels,
                "coverage_manifest": checkpoint_coverage_manifest,
            }
            if checkpoint_pack_started_at is not None
            else None
        )
        return {
            "schema": (
                14
                if args.memory_probe_input
                and checkpoint_input_memory_probe_schema == 2
                else 13
                if args.memory_probe_input
                else 12
                if args.memory_probe_hurtbox
                else 11
                if args.memory_probe_surface
                else 10
                if args.memory_probe_collision
                else 9
                if args.memory_probe_hitbox
                else 8 if args.memory_probe_shield or args.memory_probe_damage else 7
            ),
            "oracle": (
                "SSBM GALE01 NTSC-U revision 2 with UCF 0.84 "
                "via Dolphin/Slippi"
                if ucf_oracle_policy is not None
                else "SSBM GALE01 NTSC-U revision 2 via Dolphin/Slippi"
            ),
            "oracle_gameplay_policy": ucf_oracle_policy,
            "dolphin_version": console.version,
            "oracle_execution": (
                {
                    "mode": (
                        "exiai-headless-null-unlimited"
                        if args.oracle_exiai_no_fast_forward
                        else "exiai-headless-null-fast-forward"
                    ),
                    "release": "exi-ai-0.2.0",
                    "release_artifact_sha256": EXIAI_020_APPIMAGE_SHA256,
                    "launcher_sha256": cached_sha256(executable),
                }
                if args.oracle_exiai
                else {"mode": "stock"}
            ),
            **(
                {"checkpoint_probe": checkpoint_probe}
                if checkpoint_probe is not None
                else {}
            ),
            **(
                {"checkpoint_pack": checkpoint_pack}
                if checkpoint_pack is not None
                else {}
            ),
            "libmelee_version": importlib.metadata.version("melee"),
            "disc": {
                "game_id": "GALE01",
                "revision": 2,
                "sha256": cached_sha256(iso),
            },
            "fighter": "CPTFALCON",
            "opponent": (
                "CPTFALCON"
                if (
                    args.push_only
                    or args.shield_hit_only
                    or args.shield_collision_only
                    or args.moving_hit_sweep_only
                    or args.common_hurt_geometry_only
                    or args.damage_hit_only
                    or args.hitbox_geometry_only
                    or args.throw_geometry_only
                    or args.special_geometry_only
                    or powershield_special_route
                )
                else "FOX"
            ),
            "stage": (
                "HYRULE_TEMPLE"
                if hyrule_stage_route
                else "BATTLEFIELD"
                if (
                    args.platform_only
                    or args.platform_drop_ecb_only
                    or args.airborne_ecb_only
                    or args.aerial_attack_ecb_only
                        or args.aerial_attack_landing_only
                        or args.shield_guardon_landing_only
                        or args.airborne_landing_only
                    or battlefield_checkpoint_route
                )
                else "FINAL_DESTINATION"
            ),
            "shield_hit_requested_pressure": (
                args.shield_hit_pressure if args.shield_hit_only else None
            ),
            "shield_hit_route": bool(args.shield_hit_only),
            "damage_hit_route": bool(args.damage_hit_only),
            "defense_state_route": bool(args.defense_state_only),
            "special_acquisition_route": bool(
                args.special_acquisition_only
            ),
            "shield_break_orientation_route": bool(
                args.shield_break_orientation_only
            ),
            "aerial_iasa_route": bool(args.aerial_iasa_only),
            "aerial_attack_ecb_route": bool(args.aerial_attack_ecb_only),
            "aerial_attack_landing_route": bool(
                args.aerial_attack_landing_only
            ),
            "common_hurt_geometry_route": bool(
                args.common_hurt_geometry_only
            ),
            "controller_postframe_pipeline_delay": pipeline_delay,
            "shield_memory_probe": (
                {
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "guard_state_pipeline_delay_frames": 1,
                    "fields": {
                        "guard_magnitude": "fighter+0x2344",
                        "guard_angle_degrees": "fighter+0x2348",
                        "shield_health": "fighter+0x1998",
                        "lightshield_amount": "fighter+0x199c",
                        "shield_joint": "fighter+0x19c0",
                    },
                }
                if args.memory_probe_shield or args.memory_probe_collision
                else None
            ),
            "damage_memory_probe": (
                {
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "common_data_pointer_address": "0x804d6554",
                    "decomp_revision": ("9509dc04406fb2028bfab01243841ba4787c0fb7"),
                }
                if args.memory_probe_damage
                else None
            ),
            "input_memory_probe": (
                {
                    **(
                        {"schema": 2}
                        if checkpoint_input_memory_probe_schema == 2
                        else {}
                    ),
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "fields": {
                        "tilt_x_age": "fighter+0x670",
                        "tilt_y_age": "fighter+0x671",
                        "input_timer_counter": "fighter+0x672",
                        **(
                            {
                                "ucf_tilt_x_age": "fighter+0x673",
                                "ucf_tilt_y_age": "fighter+0x674",
                                "fighter_processed_main": "fighter+0x620..0x627",
                                "fighter_previous_main": "fighter+0x628..0x62f",
                                "fighter_processed_c": "fighter+0x638..0x63f",
                                "slippi_raw_main": "pre-frame+0x3b,+0x40",
                                "slippi_raw_c": "pre-frame+0x41..0x42",
                                "pad_processed_axes": (
                                    "HSD_PadGameStatus[port]+0x20..0x2f"
                                ),
                                "fighter_pre_ucf_axes": (
                                    "HSD processed axes after common-data x0/x4"
                                    " deadzones"
                                ),
                                "fighter_axis_deadzones": "p_ftCommonData+0x00..0x07",
                                "ucf_pad_buffer_count": (
                                    "UCF@0x8006b460 target+0x04+port*0x0c+0x09"
                                ),
                            }
                            if checkpoint_input_memory_probe_schema == 2
                            else {}
                        ),
                    },
                    "decomp_revision": (
                        "9509dc04406fb2028bfab01243841ba4787c0fb7"
                    ),
                }
                if args.memory_probe_input
                else None
            ),
            "surface_collision_memory_probe": (
                {
                    "schema": 2,
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "fields": {
                        "fighter_animation_frame": "fighter+0x894",
                        "fighter_animation_rate": "fighter+0x89c",
                        "fighter_motion_id": "fighter+0x10",
                        "fighter_animation_id": "fighter+0x14",
                        "fighter_animation_blend_frames": "fighter+0x8a4",
                        "fighter_animation_blend_progress": "fighter+0x8a8",
                        "fighter_costume_id": "fighter+0x619",
                        "fighter_costume_joint": "fighter+0x108",
                        "fighter_parts": "fighter+0x5e8",
                        "guard_target_joint_tree": (
                            "((HSD_Joint**)fighter->ft_data->x20->x0)[2]"
                        ),
                        "ecb_source": "fighter+0x7f4",
                        "ecb_source_joints": "fighter+0x7fc..0x810",
                        "ecb_source_joint_srt_and_matrix": (
                            "HSD_JObj+0x14..0x73"
                        ),
                        "environment_flags": "fighter+0x824",
                        "contact": "fighter+0x830",
                        "floor": "fighter+0x83c",
                        "left_facing_wall": "fighter+0x850",
                        "right_facing_wall": "fighter+0x864",
                        "ceiling": "fighter+0x878",
                    },
                }
                if args.memory_probe_surface
                else None
            ),
            "guard_target_joint_tree": (
                read_guard_target_joint_tree(memory_engine)
                if args.memory_probe_surface and memory_engine is not None
                else None
            ),
            "capture_constraint_memory_probe": (
                {
                    "schema": 1,
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "players": [0, 1],
                    "fields": {
                        "fighter_position": "fighter+0xb0..0xbb",
                        "collision_positions": "fighter+0x6f4..0x723",
                        "desired_ecb": "fighter+0x774..0x793",
                        "current_ecb": "fighter+0x794..0x7b3",
                        "previous_step_ecb": "fighter+0x7b4..0x7d3",
                        "routine_start_ecb": "fighter+0x7d4..0x7f3",
                        "saved_xrotn_translation": "fighter+0x2174..0x217f",
                        "constraint_flags_raw": "fighter+0x2226",
                    },
                    "decomp_revision": (
                        "9509dc04406fb2028bfab01243841ba4787c0fb7"
                    ),
                }
                if args.memory_probe_surface and args.throw_geometry_only
                else None
            ),
            "stage_collision_memory": stage_collision_memory,
            "item_rules": item_rules,
            "hitbox_memory_probe": (
                {
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "fighter_hitbox_array": "fighter+0x914",
                    "hitbox_stride": "0x138",
                    "position": "hitbox+0x4c",
                    "previous_position": "hitbox+0x58",
                    "static_player_stride": "0xe90",
                    "fighter_hurtbox_count": "fighter+0x119e",
                    "fighter_hurtbox_array": "fighter+0x11a0",
                    "hurtbox_stride": "0x4c",
                    "hurtbox_position_a": "hurtbox+0x28",
                    "hurtbox_position_b": "hurtbox+0x34",
                    "fighter_desired_ecb": "fighter+0x774",
                    "fighter_ecb": "fighter+0x794",
                    "fighter_previous_ecb": "fighter+0x7b4",
                    "fighter_ecb_lock_ticks": "fighter+0x88c",
                    "fighter_collision_flags": "fighter+0x820",
                    "ecb_layout": "top,bottom,right,left Vec2",
                    "fighter_ledge_snap": "fighter+0x744,+0x748,+0x74c",
                    "fighter_collision_contact": "fighter+0x830 Vec3",
                    "fighter_collision_positions": ("fighter+0x6f4,+0x700,+0x70c Vec3"),
                    "fighter_ledge_ids": "fighter+0x730,+0x734",
                    "decomp_revision": ("9509dc04406fb2028bfab01243841ba4787c0fb7"),
                }
                if args.memory_probe_hitbox or args.memory_probe_collision
                else None
            ),
            "hurtbox_memory_probe": (
                {
                    "engine_version": importlib.metadata.version(
                        "dolphin-memory-engine"
                    ),
                    "player_slot_address": "0x80453080",
                    "fighter_hurtbox_count": "fighter+0x119e",
                    "fighter_hurtbox_array": "fighter+0x11a0",
                    "hurtbox_stride": "0x4c",
                    "position_a": "hurtbox+0x28 collision-authoritative Vec3",
                    "position_b": "hurtbox+0x34 collision-authoritative Vec3",
                    "decomp_revision": (
                        "9509dc04406fb2028bfab01243841ba4787c0fb7"
                    ),
                }
                if args.memory_probe_hurtbox
                else None
            ),
            "rows": rows,
        }
    finally:
        cleanup_started_at = time.monotonic()
        if memory_engine is not None:
            memory_engine.un_hook()
        player_one.disconnect()
        player_two.disconnect()
        stop_console(console)
        if args.oracle_checkpoint_pack:
            finished_at = time.monotonic()
            menu_start = connected_at or started_at
            hook_start = menu_ready_at or menu_start
            capture_start = hook_ready_at or hook_start
            print(
                "ssbm-checkpoint-lifecycle-time "
                f"launch_connect_seconds="
                f"{(connected_at or finished_at) - started_at:.6f} "
                f"menu_seconds="
                f"{(menu_ready_at or finished_at) - menu_start:.6f} "
                f"hook_seconds="
                f"{(hook_ready_at or finished_at) - hook_start:.6f} "
                f"capture_seconds="
                f"{cleanup_started_at - capture_start:.6f} "
                f"cleanup_seconds={finished_at - cleanup_started_at:.6f} "
                f"total_seconds={finished_at - started_at:.6f}",
                file=sys.stderr,
                flush=True,
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dolphin", required=True)
    parser.add_argument("--iso", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--menu-timeout", type=float, default=120.0)
    parser.add_argument("--start-frame", type=int, default=120)
    parser.add_argument("--slippi-port", type=int, default=51441)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument(
        "--oracle-exiai",
        action="store_true",
        help="use the pinned ExiAI 0.2.0 headless Null-video fast-forward path",
    )
    parser.add_argument(
        "--oracle-exiai-no-fast-forward",
        action="store_true",
        help="retain ExiAI/checkpoints but disable display-bone-skipping FFW",
    )
    parser.add_argument(
        "--oracle-release-artifact",
        type=Path,
        help="pinned ExiAI release AppImage used to produce an extracted launcher",
    )
    parser.add_argument(
        "--oracle-checkpoint-probe",
        action="store_true",
        help="qualify the checkpoint-enabled NoGUI control protocol",
    )
    parser.add_argument(
        "--oracle-checkpoint-pack",
        action="store_true",
        help="replace cross-case settling with checkpoint-isolated cases",
    )
    parser.add_argument(
        "--oracle-checkpoint-no-batch-inputs",
        action="store_true",
        help=(
            "sample every checkpoint response frame instead of batching EXI "
            "inputs; intended for collision-memory geometry captures"
        ),
    )
    parser.add_argument(
        "--oracle-coverage-manifest",
        type=Path,
        help="domain manifest owning checkpoint capture selection and budgets",
    )
    parser.add_argument(
        "--oracle-case",
        action="append",
        help="capture only the named checkpoint case; repeatable",
    )
    parser.add_argument("--enable-items", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--platform-only", action="store_true")
    mode.add_argument("--platform-drop-ecb-only", action="store_true")
    mode.add_argument(
        "--airborne-ecb-only",
        "--jump-forward-ecb-only",
        dest="airborne_ecb_only",
        action="store_true",
        help=(
            "capture complete JumpF/JumpB/JumpAerialF/JumpAerialB ECB tracks; "
            "--jump-forward-ecb-only is a compatibility alias"
        ),
    )
    mode.add_argument("--airborne-landing-only", action="store_true")
    mode.add_argument("--push-only", action="store_true")
    mode.add_argument("--shield-only", action="store_true")
    mode.add_argument("--shield-break-orientation-only", action="store_true")
    mode.add_argument("--shield-geometry-only", action="store_true")
    mode.add_argument("--shield-geometry-sweep-only", action="store_true")
    mode.add_argument("--shield-guardon-landing-only", action="store_true")
    mode.add_argument("--shield-hit-only", action="store_true")
    mode.add_argument("--shield-collision-only", action="store_true")
    mode.add_argument("--moving-hit-sweep-only", action="store_true")
    mode.add_argument("--common-hurt-geometry-only", action="store_true")
    mode.add_argument("--damage-hit-only", action="store_true")
    mode.add_argument("--defense-state-only", action="store_true")
    mode.add_argument("--special-acquisition-only", action="store_true")
    mode.add_argument("--attack-iasa-only", action="store_true")
    mode.add_argument("--aerial-iasa-only", action="store_true")
    mode.add_argument("--aerial-attack-ecb-only", action="store_true")
    mode.add_argument("--aerial-attack-landing-only", action="store_true")
    mode.add_argument("--ground-attack-iasa-only", action="store_true")
    mode.add_argument("--hitbox-geometry-only", action="store_true")
    mode.add_argument("--throw-geometry-only", action="store_true")
    mode.add_argument("--special-geometry-only", action="store_true")
    parser.add_argument(
        "--ground-attack-move",
        action="append",
        choices=(
            "dashattack",
            "ftilt_m",
            "utilt",
            "dtilt",
            "fsmash_m",
            "usmash",
            "dsmash",
        ),
    )
    parser.add_argument(
        "--special-geometry-move",
        action="append",
        choices=tuple(SPECIAL_GEOMETRY_SOURCE_KEYS),
    )
    parser.add_argument("--falcon-frame-data", type=Path)
    parser.add_argument("--memory-probe-shield", action="store_true")
    parser.add_argument("--memory-probe-damage", action="store_true")
    parser.add_argument("--memory-probe-input", action="store_true")
    parser.add_argument("--memory-probe-hitbox", action="store_true")
    parser.add_argument("--memory-probe-hurtbox", action="store_true")
    parser.add_argument("--memory-probe-collision", action="store_true")
    parser.add_argument("--memory-probe-surface", action="store_true")
    parser.add_argument("--shield-hit-pressure", type=float, default=0.35)
    args = parser.parse_args(argv)
    if args.oracle_exiai and args.batch:
        parser.error("--oracle-exiai launches its own headless process")
    if args.oracle_exiai_no_fast_forward and not args.oracle_exiai:
        parser.error("--oracle-exiai-no-fast-forward requires --oracle-exiai")
    if args.oracle_exiai and args.oracle_release_artifact is None:
        parser.error("--oracle-exiai requires --oracle-release-artifact")
    if args.oracle_release_artifact is not None and not args.oracle_exiai:
        parser.error("--oracle-release-artifact requires --oracle-exiai")
    if args.oracle_checkpoint_probe and not args.oracle_exiai:
        parser.error("--oracle-checkpoint-probe requires --oracle-exiai")
    if args.oracle_checkpoint_pack and not (
        args.oracle_exiai
        and (
            args.common_hurt_geometry_only
            or args.damage_hit_only
            or args.push_only
            or args.special_acquisition_only
        )
    ):
        parser.error(
            "--oracle-checkpoint-pack requires --oracle-exiai and "
            "a checkpoint-capable capture mode"
        )
    if args.oracle_checkpoint_probe and args.oracle_checkpoint_pack:
        parser.error("select only one checkpoint mode")
    if args.oracle_checkpoint_pack and args.oracle_coverage_manifest is None:
        parser.error("--oracle-checkpoint-pack requires --oracle-coverage-manifest")
    if args.oracle_coverage_manifest is not None and not args.oracle_checkpoint_pack:
        parser.error("--oracle-coverage-manifest requires --oracle-checkpoint-pack")
    if args.oracle_case and not args.oracle_checkpoint_pack:
        parser.error("--oracle-case requires --oracle-checkpoint-pack")
    if args.oracle_checkpoint_no_batch_inputs and not args.oracle_checkpoint_pack:
        parser.error(
            "--oracle-checkpoint-no-batch-inputs requires --oracle-checkpoint-pack"
        )
    if not 1024 <= args.slippi_port <= 65535:
        parser.error("--slippi-port must be in [1024, 65535]")
    if not 0.30 <= args.shield_hit_pressure <= 1.0:
        parser.error("--shield-hit-pressure must be in [0.30, 1.0]")
    if (
        args.special_geometry_move
        and "side_ground_item_hit" in args.special_geometry_move
        and not args.enable_items
    ):
        parser.error("side_ground_item_hit requires --enable-items")
    if args.memory_probe_damage and not args.damage_hit_only:
        parser.error("--memory-probe-damage requires --damage-hit-only")
    if args.memory_probe_surface and not (
        args.platform_only
        or args.platform_drop_ecb_only
        or args.airborne_ecb_only
        or args.aerial_attack_ecb_only
        or args.aerial_attack_landing_only
        or args.airborne_landing_only
        or args.shield_break_orientation_only
        or args.throw_geometry_only
        or args.special_geometry_only
        or (
            args.oracle_checkpoint_pack
            and (
                args.damage_hit_only
                or args.common_hurt_geometry_only
                or args.special_acquisition_only
            )
        )
    ):
        parser.error(
            "--memory-probe-surface requires --platform-only, "
            "--platform-drop-ecb-only, --airborne-ecb-only, "
            "--aerial-attack-ecb-only, --aerial-attack-landing-only, "
            "--airborne-landing-only, --shield-break-orientation-only, "
            "--throw-geometry-only, --special-geometry-only, or a "
            "damage-hit/common-hurt-geometry/"
            "special-acquisition checkpoint pack"
        )
    if args.memory_probe_hitbox and not (
        args.defense_state_only
        or args.common_hurt_geometry_only
        or args.shield_hit_only
        or args.hitbox_geometry_only
        or args.throw_geometry_only
        or args.special_geometry_only
        or args.shield_break_orientation_only
        or (args.damage_hit_only and args.oracle_checkpoint_pack)
    ):
        parser.error(
            "--memory-probe-hitbox requires a geometry-only mode or a "
            "damage-hit checkpoint pack"
        )
    if args.memory_probe_hurtbox and not (
        args.common_hurt_geometry_only
        or args.airborne_ecb_only
        or args.hitbox_geometry_only
        or args.throw_geometry_only
        or args.special_geometry_only
        or (args.damage_hit_only and args.oracle_checkpoint_pack)
    ):
        parser.error(
            "--memory-probe-hurtbox requires a geometry/ECB-only mode or a "
            "damage-hit checkpoint pack"
        )
    if args.memory_probe_collision and not (
        args.shield_collision_only
        or args.moving_hit_sweep_only
        or args.shield_break_orientation_only
    ):
        parser.error(
            "--memory-probe-collision requires --shield-collision-only or "
            "--moving-hit-sweep-only or --shield-break-orientation-only"
        )
    selected_memory_probes = (
        args.memory_probe_shield,
        args.memory_probe_damage,
        args.memory_probe_input,
        args.memory_probe_hitbox,
        args.memory_probe_hurtbox,
        args.memory_probe_collision,
        args.memory_probe_surface,
    )
    input_surface_checkpoint_probe = (
        args.memory_probe_input
        and args.memory_probe_surface
        and args.oracle_checkpoint_pack
        and args.special_acquisition_only
        and sum(selected_memory_probes) == 2
    )
    if sum(selected_memory_probes) > 1 and not input_surface_checkpoint_probe:
        parser.error("select only one memory probe")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = capture(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print("ssbm-movement-capture=pass " f"frames={len(result['rows'])} output={output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
