#!/usr/bin/env python3
"""Replay a Dolphin movement capture through the native M4 simulator."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import sys

from ssbm_collision import binary32


SSBM_TO_M4_ACTION = {
    "STANDING": 0,
    "WALK_SLOW": 1,
    "WALK_MIDDLE": 1,
    "WALK_FAST": 1,
    "DASHING": 2,
    "RUNNING": 3,
    "RUN_BRAKE": 11,
    "TURNING_RUN": 10,
    "FALLING": 6,
    "TURNING": 103,
    "SHIELD_START": 18,
    "SHIELD_REFLECT": 18,
    "SHIELD": 18,
    "SHIELD_RELEASE": 20,
    "SHIELD_STUN": 19,
    "SHIELD_BREAK_FLY": 21,
    "SHIELD_BREAK_DOWN_U": 46,
    "SHIELD_BREAK_DOWN_D": 46,
    "SHIELD_BREAK_STAND_U": 47,
    "SHIELD_BREAK_STAND_D": 47,
    "SHIELD_BREAK_TEETER": 48,
    "NEUTRAL_ATTACK_1": 12,
    "NEUTRAL_ATTACK_2": 58,
    "DASH_ATTACK": 57,
    "FTILT_HIGH": 87,
    "FTILT_HIGH_MID": 87,
    "FTILT_MID": 87,
    "FTILT_LOW_MID": 87,
    "FTILT_LOW": 87,
    "UPTILT": 79,
    "DOWNTILT": 80,
    "FSMASH_HIGH": 88,
    "FSMASH_MID_HIGH": 88,
    "FSMASH_MID": 88,
    "FSMASH_MID_LOW": 88,
    "FSMASH_LOW": 88,
    "UPSMASH": 89,
    "DOWNSMASH": 90,
    "ROLL_FORWARD": 38,
    "ROLL_BACKWARD": 39,
    "SPOTDODGE": 40,
    "CROUCH_START": 104,
    "CROUCHING": 4,
    "CROUCH_END": 105,
    "KNEE_BEND": 5,
    "JUMPING_FORWARD": 6,
    "JUMPING_BACKWARD": 6,
    "JUMPING_ARIAL_FORWARD": 6,
    "JUMPING_ARIAL_BACKWARD": 6,
    "FALLING_FORWARD": 6,
    "FALLING_BACKWARD": 6,
    "FALLING_AERIAL": 6,
    "FALLING_AERIAL_FORWARD": 6,
    "FALLING_AERIAL_BACKWARD": 6,
    "AIRDODGE": 32,
    "NAIR": 35,
    "FAIR": 81,
    "BAIR": 82,
    "UAIR": 83,
    "DAIR": 84,
    "NAIR_LANDING": 36,
    "FAIR_LANDING": 95,
    "BAIR_LANDING": 96,
    "UAIR_LANDING": 97,
    "DAIR_LANDING": 98,
    "LANDING_SPECIAL": 34,
    "LANDING": 7,
    "TAUNT_RIGHT": 75,
    "TAUNT_LEFT": 75,
    "PLATFORM_DROP": 6,
    "NEUTRAL_B_FULL_CHARGE_AIR": 108,
    "NEUTRAL_B_ATTACKING_AIR": 107,
    "SWORD_DANCE_1": 109,
    "SWORD_DANCE_2_HIGH": 110,
    "SWORD_DANCE_2_MID": 111,
    "SWORD_DANCE_3_HIGH": 112,
}

CHARACTER_AERIAL_LANDING_ACTIONS = {
    "NAIR_LANDING",
    "FAIR_LANDING",
    "BAIR_LANDING",
    "UAIR_LANDING",
    "DAIR_LANDING",
}

POSITION_ANCHOR_LABELS = {
    "recenter_after_defense",
    "run_for_jump_squat_reverse",
    "recenter_before_double_jump",
    "neutral_jump_for_double_jump",
    "short_hop_press",
    "full_hop_press",
    "full_hop_for_fast_fall",
    "settle_before_crouch_start_jump",
    "settle_before_crouch_wait_jump",
    "settle_before_crouch_end_jump",
    "settle_before_crouch_wait_dash",
    "settle_before_crouch_end_walk",
    "settle_before_crouch_start_guard",
    "settle_before_crouch_wait_guard",
    "settle_before_crouch_end_guard",
    "settle_before_crouch_start_taunt",
    "settle_before_crouch_wait_taunt",
    "settle_before_crouch_end_taunt",
    "settle_before_crouch_start_attack",
    "settle_before_crouch_wait_attack",
    "settle_before_crouch_end_attack",
    "settle_before_crouch_wait_neutral_special",
    "settle_before_crouch_end_neutral_special",
    "settle_before_crouch_start_neutral_special",
    "settle_before_crouch_start_down_special",
    "settle_before_down_special_slice",
    "settle_before_crouch_wait_down_special",
    "settle_before_crouch_end_down_special",
    "settle_before_crouch_start_grab",
    "settle_before_crouch_wait_grab",
    "settle_before_crouch_end_grab",
    "settle_before_standing_turn_taunt",
    "settle_before_landing_taunt",
    "settle_before_landing_jump",
    "settle_before_landing_dash",
    "settle_before_landing_guard",
    "settle_before_landing_walk",
    "settle_before_landing_crouch",
    "settle_before_landing_late_crouch",
    "settle_before_landing_turn",
    "settle_before_ground_tap_full_hop",
    "settle_before_ground_tap_short_hop",
    "settle_before_air_tap_jump",
    "settle_before_landing_tap_jump",
    "settle_before_shield_tap_jump",
    "settle_before_tap_jump_below_threshold",
    "settle_before_tap_jump_above_threshold",
    "settle_before_tap_jump_slow_sweep",
    "settle_before_tap_jump_two_sample",
    "recenter_before_run_brake_jump",
    "recenter_before_run_brake_crouch",
    "recenter_before_run_brake_guard",
    "recenter_before_run_brake_spot_dodge",
    "recenter_before_run_brake_cstick_roll",
    "recenter_before_run_brake_cstick_spot",
    "recenter_before_run_brake_taunt",
    "recenter_before_run_brake_attack",
    "recenter_before_run_brake_grab",
    "recenter_before_run_brake_special",
    "recenter_before_run_brake_reverse",
}

# These samples qualify common-state IASA eligibility, not the execution of
# character-specific moves. Compare the transition sample against the
# project's semantic counterpart, then resume exact shared-state comparison at
# the next stationary anchor after both character-specific actions recover.
CONTENT_ROUTE_ENTRY_ACTIONS = {
    "crouch_start_attack": 12,
    "crouch_wait_attack": 12,
    "crouch_end_attack": 12,
    "crouch_start_neutral_special": 64,
    "crouch_start_down_special": 66,
    "crouch_wait_down_special": 66,
    "crouch_end_down_special": 66,
    "crouch_start_grab": 49,
    "crouch_wait_grab": 12,
    "crouch_end_grab": 12,
    "ground_iasa_utilt_special_interrupt": 64,
    "ground_iasa_utilt_grab_interrupt": 49,
    "ground_iasa_fsmash_m_special_interrupt": 64,
    "ground_iasa_fsmash_m_grab_interrupt": 49,
}

# M4's Falcon movement values use a 12/115 world-unit scale relative to
# GALE01's Falcon attributes (for example, 2.0 becomes 24/115).
SSBM_TO_M4_F32 = 12.0 / 115.0
SSBM_TO_M4_Y_F32 = 11.0 / 62.0
GALE01_NTSC102_SHA256 = (
    "0de05981a34156b9cedcef73c73d4244ac05cf6149ab3c9cfed917698819e464"
)


def controller_axis(value: float) -> int:
    return round((value - 0.5) * 65534.0)


def controller_axis_y(value: float) -> int:
    return round((0.5 - value) * 65534.0)


def scaled_f32(value: float) -> float:
    return binary32(value * SSBM_TO_M4_F32)


def scaled_y_f32(value: float) -> float:
    return binary32(-value * SSBM_TO_M4_Y_F32)


def controller_trigger(value: float) -> int:
    return round(max(0.0, min(1.0, value)) * 65535.0)


def source_axis_q15(value: float, *, invert: bool = False) -> int:
    """Encode one source-normalized HSD axis without inventing raw history."""

    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError(f"source controller axis is out of range: {value!r}")
    result = round(value * 32767.0)
    return -result if invert else result


def native_input_line(
    row: dict[str, object],
    *,
    include_raw_main: bool = False,
    include_raw_c: bool = False,
) -> str:
    """Normalize one captured GameCube sample for the native CSV runner."""

    if include_raw_c and not include_raw_main:
        raise ValueError("exact raw C-stick input requires exact raw main input")

    observed_analog = float(row.get("observed_analog_shoulder", 0.0))
    observed_left = float(row.get("observed_left_shoulder", observed_analog))
    observed_right = float(row.get("observed_right_shoulder", observed_analog))
    # The project action packet has no device-specific Z bit. Its input
    # normalizer represents GameCube Z as the canonical full-shield-plus-A
    # grab chord, so replay the same physical sample through that mapping.
    left_trigger = (
        65535
        if bool(row.get("observed_grab", False))
        or bool(row.get("requested_digital_left"))
        else (
            controller_trigger(observed_left)
            if float(row.get("requested_left_shoulder", 0.0)) > 0.0
            else 0
        )
    )
    right_trigger = (
        65535
        if bool(row.get("requested_digital_right"))
        else (
            controller_trigger(observed_right)
            if float(row.get("requested_right_shoulder", 0.0)) > 0.0
            else 0
        )
    )
    buttons = 1 if bool(row.get("observed_jump", False)) else 0
    if bool(row.get("observed_attack", False)) or bool(
        row.get("observed_grab", False)
    ):
        buttons |= 2
    if bool(row.get("observed_special", False)):
        buttons |= 8
    if (
        abs(float(row.get("observed_c_x", 0.5)) - 0.5) > 0.02
        or abs(float(row.get("observed_c_y", 0.5)) - 0.5) > 0.02
    ):
        # Device normalization emits the canonical strong-attack bit with
        # every non-neutral C-stick sample.
        buttons |= 4
    if bool(row.get("observed_taunt", False)):
        buttons |= 16
    opponent_input_x = controller_axis(
        float(row.get("observed_opponent_main_x", 0.5))
    )
    opponent_buttons = (
        2 if bool(row.get("observed_opponent_attack", False)) else 0
    )
    input_memory = row.get("input_memory")
    if include_raw_c:
        if not isinstance(input_memory, dict):
            raise ValueError("captured row lacks input-memory probe schema 2")
        main_x = source_axis_q15(float(input_memory["fighter_pre_ucf_main_x"]))
        main_y = source_axis_q15(
            float(input_memory["fighter_pre_ucf_main_y"]),
            invert=True,
        )
        c_x = source_axis_q15(float(input_memory["fighter_pre_ucf_c_x"]))
        c_y = source_axis_q15(
            float(input_memory["fighter_pre_ucf_c_y"]),
            invert=True,
        )
    else:
        main_x = controller_axis(float(row["observed_main_x"]))
        main_y = controller_axis_y(float(row.get("observed_main_y", 0.5)))
        c_x = controller_axis(float(row.get("observed_c_x", 0.5)))
        c_y = controller_axis_y(float(row.get("observed_c_y", 0.5)))
    line = (
        f"{main_x},{main_y},{c_x},{c_y},"
        f"{left_trigger},{right_trigger},{buttons},{opponent_input_x},"
        f"{opponent_buttons}"
    )
    if not include_raw_main:
        return line
    raw_main_x = row.get("observed_raw_main_x")
    raw_main_y = row.get("observed_raw_main_y")
    if (
        not isinstance(raw_main_x, int)
        or isinstance(raw_main_x, bool)
        or not -128 <= raw_main_x <= 127
        or not isinstance(raw_main_y, int)
        or isinstance(raw_main_y, bool)
        or not -128 <= raw_main_y <= 127
    ):
        raise ValueError("captured row lacks exact signed raw main-stick bytes")
    if not include_raw_c:
        return f"{line},{raw_main_x},{raw_main_y},3"
    raw_c_x = row.get("observed_raw_c_x")
    raw_c_y = row.get("observed_raw_c_y")
    exact_axes = (raw_main_x, raw_main_y, raw_c_x, raw_c_y)
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or not -128 <= value <= 127
        for value in exact_axes
    ):
        raise ValueError("captured row lacks exact signed raw PADStatus bytes")
    return (
        f"{line},{raw_main_x},{raw_main_y},"
        f"{raw_c_x},{raw_c_y},15"
    )


def normalized_shield_strength(
    row: dict[str, object], retained_strength: int = 0
) -> int:
    if str(row.get("action")) not in {
        "SHIELD_START",
        "SHIELD_REFLECT",
        "SHIELD",
        "SHIELD_STUN",
    }:
        return 0
    if bool(row.get("requested_digital_left")) or bool(
        row.get("requested_digital_right")
    ):
        return 65535
    analog = float(row.get("observed_analog_shoulder", 0.0))
    if analog <= 0.30:
        # GuardOn/GuardReflect keep the trigger magnitude which created the
        # shield until their locked animation ends. libmelee exposes current
        # controller pressure, not that retained fighter field.
        if str(row.get("action")) in {"SHIELD_START", "SHIELD_REFLECT"}:
            return retained_strength
        return 0
    return round(((analog - 0.30) / 0.70) * 65535.0)


def expected_action_ticks(action: str, action_frame: float) -> int | None:
    frame = round(action_frame)
    if action == "PLATFORM_DROP":
        # Pass exposes source frames 0..29 directly; unlike Jump/Fall it does
        # not use the public displayed-frame-minus-one convention.
        return frame
    if action in {
        "DASHING",
        "RUN_BRAKE",
        "ROLL_FORWARD",
        "ROLL_BACKWARD",
        "SPOTDODGE",
        "CROUCH_START",
        "CROUCHING",
        "CROUCH_END",
        "TAUNT_RIGHT",
        "TAUNT_LEFT",
        "NEUTRAL_B_FULL_CHARGE_AIR",
        "NEUTRAL_B_ATTACKING_AIR",
        "SWORD_DANCE_1",
        "SWORD_DANCE_2_HIGH",
        "SWORD_DANCE_2_MID",
        "SWORD_DANCE_3_HIGH",
        "SHIELD_BREAK_FLY",
    }:
        return frame
    if action in {"NAIR", "FAIR", "BAIR", "UAIR", "DAIR"}:
        return frame - 1
    if action == "TURNING_RUN":
        return frame + 1
    if action in {"KNEE_BEND", "AIRDODGE", "LANDING"}:
        return frame - 1
    if action in {
        "SHIELD_BREAK_DOWN_U",
        "SHIELD_BREAK_DOWN_D",
        "SHIELD_BREAK_STAND_U",
        "SHIELD_BREAK_STAND_D",
    }:
        return frame - 1
    if action in {
        "JUMPING_FORWARD",
        "JUMPING_BACKWARD",
        "JUMPING_ARIAL_FORWARD",
        "JUMPING_ARIAL_BACKWARD",
        "FALLING",
        "FALLING_FORWARD",
        "FALLING_BACKWARD",
        "FALLING_AERIAL",
        "FALLING_AERIAL_FORWARD",
        "FALLING_AERIAL_BACKWARD",
    }:
        # The public M4 AIRBORNE action intentionally coalesces Melee's
        # jump/fall states. Its canonical submotion still exposes the source
        # animation clock, with action_ticks equal to displayed frame - 1.
        return frame - 1
    if action == "LANDING_SPECIAL":
        return (frame - 1) // 3
    return None


def expected_action_state(action: str, action_frame: float) -> int | None:
    return SSBM_TO_M4_ACTION.get(action)


def raptor_boost_expected_action(
    route: str,
    action: str,
    action_frame: float,
    hitlag_left: float,
) -> int | None:
    """Map one live side-special row to the production action contract."""

    expected = expected_action_state(action, action_frame)
    overrides = {
        "air_miss": {
            "SWORD_DANCE_2_MID": 111,
            "DEAD_FALL": 113,
        },
        "ground_edge": {
            "SWORD_DANCE_1": 109,
            "DEAD_FALL": 113,
        },
        "air_hit_floor": {
            "SWORD_DANCE_2_MID": 111,
            "SWORD_DANCE_3_HIGH": 112,
            "DEAD_FALL": 114,
            "LANDING_SPECIAL": 116,
            "STANDING": 0,
        },
    }
    expected = overrides.get(route, {}).get(action, expected)
    if route in {"ground_hit", "air_hit_floor"} and hitlag_left > 0.0:
        return 13
    return expected


def raptor_boost_expected_ticks(
    route: str,
    action: str,
    action_frame: float,
    hitlag_left: float,
) -> int | None:
    """Map one live side-special row to the production action clock."""

    if route in {"ground_hit", "air_hit_floor"} and hitlag_left > 0.0:
        return None
    frame = round(action_frame)
    if route == "air_miss":
        if action == "SWORD_DANCE_2_MID":
            return frame
        if action == "DEAD_FALL":
            return frame - 1
    elif route == "ground_edge":
        if action == "SWORD_DANCE_1":
            return frame
        if action == "DEAD_FALL":
            return frame - 1
    elif route == "air_hit_floor":
        if action in {"SWORD_DANCE_2_MID", "SWORD_DANCE_3_HIGH"}:
            return frame
        if action == "DEAD_FALL":
            return frame - 1
        if action == "LANDING_SPECIAL":
            return None
        if action == "STANDING":
            return 0
    return expected_action_ticks(action, action_frame)


def falcon_kick_expected_action(
    route: str,
    action: str,
    action_frame: float,
    hitlag_left: float,
) -> int | None:
    """Map one live down-special row to the production action contract."""

    expected = expected_action_state(action, action_frame)
    overrides = {
        "ground": {
            "SWORD_DANCE_4_LOW": 123,
            "SWORD_DANCE_1_AIR": 124,
            "STANDING": 0,
        },
        "ground_hit": {
            "SWORD_DANCE_4_LOW": 123,
            "SWORD_DANCE_1_AIR": 124,
            "STANDING": 0,
        },
        "ground_wall": {
            "SWORD_DANCE_4_LOW": 123,
            "SWORD_DANCE_1_AIR": 124,
            "SWORD_DANCE_3_LOW_AIR": 129,
        },
        "ground_edge": {
            "SWORD_DANCE_4_LOW": 123,
            "SWORD_DANCE_3_MID_AIR": 127,
            "FALLING": 6,
        },
        "air": {
            "SWORD_DANCE_2_HIGH_AIR": 125,
            "DOWN_B_GROUND": 128,
            "FALLING": 6,
        },
        "air_land": {
            "SWORD_DANCE_2_HIGH_AIR": 125,
            "DOWN_B_GROUND_START": 126,
            "STANDING": 0,
        },
    }
    expected = overrides.get(route, {}).get(action, expected)
    if route == "ground_hit" and hitlag_left > 0.0:
        return 13
    return expected


def falcon_kick_expected_ticks(
    route: str,
    action: str,
    action_frame: float,
    hitlag_left: float,
) -> int | None:
    """Map one live down-special row to the production action clock."""

    if route == "ground_hit" and hitlag_left > 0.0:
        return None
    frame = round(action_frame)
    if route in {"ground", "ground_hit", "ground_wall"}:
        if action in {"SWORD_DANCE_4_LOW", "SWORD_DANCE_3_LOW_AIR"}:
            return frame
        if action == "SWORD_DANCE_1_AIR":
            return frame - 1
        if action == "STANDING":
            return 0
    elif route == "ground_edge":
        if action in {"SWORD_DANCE_4_LOW", "SWORD_DANCE_3_MID_AIR"}:
            return frame
        if action == "FALLING":
            return frame - 1
    elif route == "air":
        if action == "SWORD_DANCE_2_HIGH_AIR":
            return frame
        if action == "DOWN_B_GROUND":
            return frame - 1
        if action == "FALLING":
            return 0
    elif route == "air_land":
        if action in {"SWORD_DANCE_2_HIGH_AIR", "DOWN_B_GROUND_START"}:
            return frame
        if action == "STANDING":
            return 0
    return expected_action_ticks(action, action_frame)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("runner", type=Path)
    parser.add_argument(
        "--position-tolerance-f32",
        type=float,
        default=0.009765625,
        help="allowed binary32 position difference",
    )
    parser.add_argument(
        "--velocity-tolerance-f32",
        type=float,
        default=0.00048828125,
        help="allowed binary32 velocity difference",
    )
    parser.add_argument(
        "--shield-health-tolerance-f32",
        type=float,
        help=(
            "binary32 shield-health envelope; defaults to the qualified "
            "accumulated-rounding bound"
        ),
    )
    parser.add_argument(
        "--animation-clock-tolerance-f32",
        type=float,
        default=0.0000152587890625,
        help="allowed binary32 source-animation clock difference",
    )
    parser.add_argument(
        "--native-output",
        type=Path,
        help="optionally preserve the native CSV trace for diagnostics",
    )
    parser.add_argument(
        "--native-input-output",
        type=Path,
        help="optionally preserve the normalized native input trace",
    )
    parser.add_argument(
        "--special-geometry-route",
        choices=(
            "side_ground_miss",
            "side_ground_edge",
            "side_air_miss",
            "side_air_hit",
            "side_air_hit_floor",
        ),
        help="select one route from a combined special-geometry capture",
    )
    args = parser.parse_args()
    if args.animation_clock_tolerance_f32 < 0:
        parser.error("--animation-clock-tolerance-f32 must be non-negative")

    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    disc = capture.get("disc")
    if (
        not isinstance(disc, dict)
        or disc.get("game_id") != "GALE01"
        or disc.get("revision") != 2
        or disc.get("sha256") != GALE01_NTSC102_SHA256
    ):
        print(
            "ssbm-movement-compare=fail reason=oracle-disc-identity",
            file=sys.stderr,
        )
        return 1
    oracle_rows = capture["rows"]
    aerial_iasa_mode = bool(capture.get("aerial_iasa_route", False))
    aerial_iasa_qualified_frames = (
        sum(
            1
            for row in oracle_rows
            if not (
                str(row.get("label", "")).endswith("_settle")
                or str(row.get("label", "")).endswith("_recover")
            )
        )
        if aerial_iasa_mode
        else 0
    )
    if args.special_geometry_route is not None:
        start_label = f"special_geometry_{args.special_geometry_route}_start"
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == start_label
        )
        next_route = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > first_special_row
                and str(row.get("label", "")).endswith("_opponent_pose_reset")
            ),
            len(oracle_rows),
        )
        oracle_rows = oracle_rows[first_special_row:next_route]
    falcon_punch_air_mode = any(
        str(row.get("label", "")) == "special_geometry_neutral_air_start"
        for row in oracle_rows
    )
    if falcon_punch_air_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_neutral_air_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
    raptor_boost_ground_hit_mode = any(
        str(row.get("label", "")) == "special_geometry_side_ground_hit_start"
        for row in oracle_rows
    )
    if raptor_boost_ground_hit_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_side_ground_hit_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_hit = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_hit + 1]
    raptor_boost_ground_miss_mode = any(
        str(row.get("label", "")) == "special_geometry_side_ground_miss_start"
        for row in oracle_rows
    )
    if raptor_boost_ground_miss_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_side_ground_miss_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_miss = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_miss + 1]
    raptor_boost_ground_edge_mode = any(
        str(row.get("label", "")) == "special_geometry_side_ground_edge_start"
        for row in oracle_rows
    )
    if raptor_boost_ground_edge_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_side_ground_edge_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_fall_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("action", "")) == "DEAD_FALL"
        )
        oracle_rows = oracle_rows[: first_fall_row + 32]
    raptor_boost_air_miss_mode = any(
        str(row.get("label", "")) == "special_geometry_side_air_miss_start"
        for row in oracle_rows
    )
    if raptor_boost_air_miss_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_side_air_miss_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
    raptor_boost_air_hit_floor_mode = any(
        str(row.get("label", "")) == "special_geometry_side_air_hit_floor_start"
        for row in oracle_rows
    )
    raptor_boost_air_hit_mode = raptor_boost_air_hit_floor_mode or any(
        str(row.get("label", "")) == "special_geometry_side_air_hit_start"
        for row in oracle_rows
    )
    if raptor_boost_air_hit_mode:
        start_label = (
            "special_geometry_side_air_hit_floor_start"
            if raptor_boost_air_hit_floor_mode
            else "special_geometry_side_air_hit_start"
        )
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == start_label
        )
        oracle_rows = oracle_rows[first_special_row:]
        # The native fixture reaches its ordinary floor on the executable's
        # hit-action frame 34 while the isolated Dolphin capture is held at
        # y=500. Qualify every source frame before that unrelated stage
        # contact, including the complete active/hitlag interval and 30
        # recovery frames; edge/landing conversion remains a separate route.
        if not raptor_boost_air_hit_floor_mode:
            first_fixture_floor_boundary = next(
                (
                    index
                    for index, row in enumerate(oracle_rows)
                    if str(row.get("action", "")) == "SWORD_DANCE_3_HIGH"
                    and round(float(row.get("action_frame", 0.0))) >= 34
                ),
                len(oracle_rows),
            )
            oracle_rows = oracle_rows[:first_fixture_floor_boundary]
    raptor_boost_route = next(
        (
            route
            for active, route in (
                (raptor_boost_ground_hit_mode, "ground_hit"),
                (raptor_boost_ground_miss_mode, "ground_miss"),
                (raptor_boost_air_miss_mode, "air_miss"),
                (raptor_boost_air_hit_mode, "air_hit_floor"),
                (raptor_boost_ground_edge_mode, "ground_edge"),
            )
            if active
        ),
        None,
    )
    falcon_dive_ground_miss_mode = any(
        str(row.get("label", "")) == "special_geometry_up_ground_miss_start"
        for row in oracle_rows
    )
    if falcon_dive_ground_miss_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_up_ground_miss_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_special + 1]
    falcon_dive_ground_catch_mode = any(
        str(row.get("label", "")) == "special_geometry_up_ground_catch_start"
        for row in oracle_rows
    )
    if falcon_dive_ground_catch_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_up_ground_catch_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_special + 1]
    falcon_dive_air_catch_mode = any(
        str(row.get("label", "")) == "special_geometry_up_air_catch_start"
        for row in oracle_rows
    )
    if falcon_dive_air_catch_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_up_air_catch_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_fall_after_throw = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "FALLING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_fall_after_throw + 1]
    falcon_dive_air_miss_start_label = next(
        (
            label
            for label in (
                "special_geometry_up_air_miss_start",
                "special_geometry_up_air_miss_natural_start",
            )
            if any(str(row.get("label", "")) == label for row in oracle_rows)
        ),
        None,
    )
    falcon_dive_air_miss_mode = falcon_dive_air_miss_start_label is not None
    falcon_dive_air_miss_position_isolated = (
        falcon_dive_air_miss_start_label ==
        "special_geometry_up_air_miss_start"
    )
    if falcon_dive_air_miss_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == falcon_dive_air_miss_start_label
        )
        oracle_rows = oracle_rows[first_special_row:]
    falcon_dive_air_ledge_start_label = next(
        (
            label
            for label in (
                "special_geometry_up_air_ledge_grab_start",
                "special_geometry_up_air_ledge_grab_behind_start",
            )
            if any(str(row.get("label", "")) == label for row in oracle_rows)
        ),
        None,
    )
    falcon_dive_air_ledge_mode = falcon_dive_air_ledge_start_label is not None
    falcon_dive_air_ledge_behind_mode = (
        falcon_dive_air_ledge_start_label
        == "special_geometry_up_air_ledge_grab_behind_start"
    )
    if falcon_dive_air_ledge_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == falcon_dive_air_ledge_start_label
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_ledge_catch = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("action", "")) == "EDGE_CATCHING"
        )
        oracle_rows = oracle_rows[:first_ledge_catch]
    falcon_kick_ground_mode = any(
        str(row.get("label", "")) == "special_geometry_down_ground_start"
        for row in oracle_rows
    )
    if falcon_kick_ground_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_ground_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_special + 1]
    falcon_kick_ground_hit_mode = any(
        str(row.get("label", "")) == "special_geometry_down_ground_hit_start"
        for row in oracle_rows
    )
    if falcon_kick_ground_hit_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_ground_hit_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_special + 1]
    falcon_kick_ground_wall_mode = any(
        str(row.get("label", "")) == "special_geometry_down_ground_wall_start"
        for row in oracle_rows
    )
    if falcon_kick_ground_wall_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_ground_wall_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        last_wall_rebound = max(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("action", "")) == "SWORD_DANCE_3_LOW_AIR"
        )
        oracle_rows = oracle_rows[: last_wall_rebound + 1]
    falcon_kick_ground_edge_mode = any(
        str(row.get("label", "")) == "special_geometry_down_ground_edge_start"
        for row in oracle_rows
    )
    if falcon_kick_ground_edge_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_ground_edge_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_fall_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "FALLING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_fall_after_special + 1]
    falcon_kick_air_mode = any(
        str(row.get("label", "")) == "special_geometry_down_air_start"
        for row in oracle_rows
    )
    if falcon_kick_air_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_air_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_fall_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "FALLING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_fall_after_special + 1]
    falcon_kick_air_land_mode = any(
        str(row.get("label", "")) == "special_geometry_down_air_land_start"
        for row in oracle_rows
    )
    if falcon_kick_air_land_mode:
        first_special_row = next(
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "special_geometry_down_air_land_start"
        )
        oracle_rows = oracle_rows[first_special_row:]
        first_idle_after_special = next(
            (
                index
                for index, row in enumerate(oracle_rows)
                if index > 0 and str(row.get("action", "")) == "STANDING"
            ),
            len(oracle_rows) - 1,
        )
        oracle_rows = oracle_rows[: first_idle_after_special + 1]
    falcon_kick_route = next(
        (
            route
            for active, route in (
                (falcon_kick_ground_mode, "ground"),
                (falcon_kick_ground_hit_mode, "ground_hit"),
                (falcon_kick_ground_wall_mode, "ground_wall"),
                (falcon_kick_ground_edge_mode, "ground_edge"),
                (falcon_kick_air_mode, "air"),
                (falcon_kick_air_land_mode, "air_land"),
            )
            if active
        ),
        None,
    )
    push_mode = bool(oracle_rows) and str(oracle_rows[0].get("label", "")).startswith(
        "push_"
    )
    shield_hit_mode = bool(oracle_rows) and str(
        oracle_rows[0].get("label", "")
    ).startswith("shield_hit_")
    shield_placement_index = next(
        (
            index
            for index, row in enumerate(oracle_rows)
            if str(row.get("label", "")) == "shield_hit_place"
        ),
        None,
    )
    if shield_hit_mode and shield_placement_index is not None:
        # The placement row is the deterministic theorem boundary.  The
        # preceding Dolphin-only settle frames neither encode inputs nor have
        # a native analogue, so compare both fighters relative to this row.
        oracle_rows = oracle_rows[shield_placement_index:]
    shield_clock_mode = shield_hit_mode and any(
        isinstance(row.get("hitbox_memory"), dict) for row in oracle_rows
    )
    two_player_mode = push_mode or shield_hit_mode
    # float32 accumulation can move a strict float overlap across the boundary
    # by one tick. Accept at most one 0.3-unit Melee push nudge per fighter in
    # this route, in addition to the ordinary position quantization envelope;
    # action, facing, grounded state, and self-induced velocity remain strict.
    position_tolerance_f32 = args.position_tolerance_f32
    if push_mode:
        position_tolerance_f32 += abs(scaled_f32(0.3))
    input_text = "".join(f"{native_input_line(row)}\n" for row in oracle_rows)
    if args.native_input_output is not None:
        args.native_input_output.write_text(input_text, encoding="utf-8")
    runner_command = [str(args.runner)]
    if capture.get("stage") == "BATTLEFIELD":
        runner_command.append("--platform")
    elif push_mode:
        runner_command.append("--push")
    elif shield_hit_mode:
        runner_command.append(
            "--shield-hit-place"
            if shield_placement_index is not None
            else "--shield-hit"
        )
    elif falcon_punch_air_mode:
        runner_command.append("--falcon-punch-air")
    elif raptor_boost_ground_miss_mode:
        runner_command.append("--raptor-boost-ground-miss")
    elif raptor_boost_ground_edge_mode:
        runner_command.append("--raptor-boost-ground-edge")
    elif raptor_boost_ground_hit_mode:
        runner_command.append("--raptor-boost-ground-hit")
    elif raptor_boost_air_miss_mode:
        runner_command.append("--raptor-boost-air-miss")
    elif raptor_boost_air_hit_mode:
        runner_command.append("--raptor-boost-air-hit")
    elif falcon_dive_ground_catch_mode:
        runner_command.append("--falcon-dive-ground-catch")
    elif falcon_dive_air_catch_mode:
        runner_command.append("--falcon-dive-air-catch")
    elif falcon_dive_air_miss_mode:
        runner_command.append("--falcon-dive-air-miss")
    elif falcon_dive_air_ledge_behind_mode:
        runner_command.append("--falcon-dive-air-ledge-behind")
    elif falcon_dive_air_ledge_mode:
        runner_command.append("--falcon-dive-air-ledge")
    elif falcon_kick_ground_mode:
        runner_command.append("--falcon-kick-ground")
    elif falcon_kick_ground_hit_mode:
        runner_command.append("--falcon-kick-ground-hit")
    elif falcon_kick_ground_wall_mode:
        runner_command.append("--falcon-kick-ground-wall")
    elif falcon_kick_ground_edge_mode:
        runner_command.append("--falcon-kick-ground-edge")
    elif falcon_kick_air_mode:
        runner_command.append("--falcon-kick-air")
    elif falcon_kick_air_land_mode:
        runner_command.append("--falcon-kick-air-land")
    completed = subprocess.run(
        runner_command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        return completed.returncode
    if args.native_output is not None:
        args.native_output.write_text(completed.stdout, encoding="utf-8")
    native_rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    if len(native_rows) != len(oracle_rows):
        print(
            "ssbm-movement-compare=fail reason=row-count "
            f"oracle={len(oracle_rows)} native={len(native_rows)}",
            file=sys.stderr,
        )
        return 1

    previous_oracle: dict[str, object] | None = None
    previous_native: dict[str, str] | None = None
    falcon_dive_target_checked_frames = 0
    oracle_anchor_x = (
        float(oracle_rows[0]["position_x_from_origin"])
        - float(oracle_rows[0]["ground_velocity_x"])
        if raptor_boost_ground_hit_mode or raptor_boost_ground_edge_mode
        else (
            float(oracle_rows[0]["position_x_from_origin"])
            if falcon_kick_ground_edge_mode
            or falcon_kick_ground_hit_mode
            or falcon_kick_ground_wall_mode
            else 0.0
        )
    )
    oracle_anchor_y = (
        float(oracle_rows[0]["position_y"])
        - (float(oracle_rows[0]["velocity_y"]) if falcon_kick_air_land_mode else 0.0)
        if capture.get("stage") == "BATTLEFIELD" or falcon_kick_air_land_mode
        else 0.0
    )
    if falcon_kick_ground_wall_mode:
        oracle_anchor_y = float(oracle_rows[0]["position_y"])
    elif (
        falcon_dive_air_catch_mode
        or falcon_dive_air_miss_mode
        or falcon_dive_air_ledge_mode
        or raptor_boost_air_miss_mode
        or raptor_boost_air_hit_mode
    ):
        oracle_anchor_x = float(oracle_rows[0]["position_x_from_origin"])
        oracle_anchor_y = float(oracle_rows[0]["position_y"])
    native_anchor_x = 0.0
    native_anchor_y = 0.0
    oracle_opponent_anchor_x = 0.0
    native_opponent_anchor_x = 0.0
    if shield_hit_mode and shield_placement_index is not None:
        oracle_anchor_x = float(oracle_rows[0]["position_x_from_origin"])
        native_anchor_x = float(native_rows[0]["position_x_f32_from_origin"])
        oracle_opponent_anchor_x = float(
            oracle_rows[0]["opponent_position_x_from_origin"]
        )
        native_opponent_anchor_x = float(
            native_rows[0]["opponent_position_x_f32_from_origin"]
        )
    horizontal_mirror = -1 if falcon_punch_air_mode or falcon_kick_air_mode else 1
    previous_label: str | None = None
    skip_character_content = False
    shield_contact_seen = False
    shield_numeric_ticks = 0
    shield_clock_checked_frames = 0
    expected_shield_strength = 0
    source_action_elapsed_ticks = 0
    for oracle_index, (oracle, native) in enumerate(
        zip(oracle_rows, native_rows, strict=True)
    ):
        frame = int(oracle["trace_frame"])
        label = str(oracle["label"])
        entering_anchor = (
            label != previous_label
            and (label in POSITION_ANCHOR_LABELS or label.endswith("_settle"))
            and previous_oracle is not None
        )
        if skip_character_content and not entering_anchor:
            previous_oracle = oracle
            previous_native = native
            previous_label = label
            continue
        if entering_anchor:
            skip_character_content = False
        if entering_anchor:
            oracle_anchor_x = float(previous_oracle["position_x_from_origin"])
            oracle_anchor_y = float(previous_oracle["position_y"])
            native_anchor_x = float(previous_native["position_x_f32_from_origin"])
            native_anchor_y = float(previous_native["position_y_f32_from_origin"])
        if (
            (falcon_dive_ground_catch_mode or falcon_dive_air_catch_mode)
            and str(oracle.get("action", "")) == "SWORD_DANCE_4_HIGH"
            and float(oracle.get("hitlag_left", 0.0)) > 0.0
            and (
                previous_oracle is None
                or float(previous_oracle.get("hitlag_left", 0.0)) <= 0.0
            )
        ):
            oracle_anchor_x = float(oracle["position_x_from_origin"])
            oracle_anchor_y = float(oracle["position_y"])
            native_anchor_x = float(native["position_x_f32_from_origin"])
            native_anchor_y = float(native["position_y_f32_from_origin"])
        action_name = str(oracle["action"])
        action_frame = round(float(oracle["action_frame"]))
        source_action_elapsed_ticks = (
            source_action_elapsed_ticks + 1
            if previous_oracle is not None
            and str(previous_oracle.get("action", "")) == action_name
            else 0
        )
        if (
            falcon_kick_ground_wall_mode
            and action_name == "SWORD_DANCE_3_LOW_AIR"
            and (
                previous_oracle is None
                or str(previous_oracle.get("action", "")) != "SWORD_DANCE_3_LOW_AIR"
            )
        ):
            # Hyrule's approach floor changes height before the wall. Anchor
            # the rebound state at its executable transition so the following
            # imported root trajectory is compared independently of that
            # unrelated stage topology.
            oracle_anchor_x = float(oracle["position_x_from_origin"])
            oracle_anchor_y = float(oracle["position_y"])
            native_anchor_x = float(native["position_x_f32_from_origin"])
            native_anchor_y = float(native["position_y_f32_from_origin"])
        if (
            falcon_punch_air_mode
            and action_name == "NEUTRAL_B_FULL_CHARGE_AIR"
            and action_frame == 49
        ):
            oracle_anchor_x = float(oracle["position_x_from_origin"])
            oracle_anchor_y = float(oracle["position_y"])
            native_anchor_x = float(native["position_x_f32_from_origin"])
            native_anchor_y = float(native["position_y_f32_from_origin"])
        expected_action = CONTENT_ROUTE_ENTRY_ACTIONS.get(label)
        if expected_action is None:
            expected_action = expected_action_state(
                action_name, float(oracle["action_frame"])
            )
        if falcon_dive_ground_miss_mode:
            expected_action = {
                "SWORD_DANCE_3_MID": 117,
                "DEAD_FALL": 121,
                "LANDING_SPECIAL": 122,
                "STANDING": 0,
            }.get(action_name, expected_action)
        if falcon_dive_ground_catch_mode:
            expected_action = {
                "SWORD_DANCE_3_MID": 117,
                "SWORD_DANCE_4_HIGH": 119,
                "SWORD_DANCE_4_MID": 120,
                "FALLING": 6,
                "LANDING_SPECIAL": 122,
                "LANDING": 7,
                "STANDING": 0,
            }.get(action_name, expected_action)
            if float(oracle.get("hitlag_left", 0.0)) > 0.0:
                expected_action = 13
        if (
            falcon_dive_air_catch_mode
            or falcon_dive_air_miss_mode
            or falcon_dive_air_ledge_mode
        ):
            expected_action = {
                "SWORD_DANCE_3_LOW": 118,
                "SWORD_DANCE_4_HIGH": 119,
                "SWORD_DANCE_4_MID": 120,
                "DEAD_FALL": 121,
                "LANDING_SPECIAL": 122,
                "FALLING": 6,
                "EDGE_CATCHING": 8,
                "EDGE_HANGING": 8,
            }.get(action_name, expected_action)
            if float(oracle.get("hitlag_left", 0.0)) > 0.0:
                expected_action = 13
        if raptor_boost_route is not None:
            expected_action = raptor_boost_expected_action(
                raptor_boost_route,
                action_name,
                float(oracle["action_frame"]),
                float(oracle.get("hitlag_left", 0.0)),
            )
        if falcon_kick_route is not None:
            expected_action = falcon_kick_expected_action(
                falcon_kick_route,
                action_name,
                float(oracle["action_frame"]),
                float(oracle.get("hitlag_left", 0.0)),
            )
        if shield_hit_mode and float(oracle.get("hitlag_left", 0.0)) > 0.0:
            expected_action = 13
        actual_action = int(native["action_state"])
        expected_ticks = (
            None
            if label in CONTENT_ROUTE_ENTRY_ACTIONS
            else expected_action_ticks(action_name, float(oracle["action_frame"]))
        )
        if action_name in CHARACTER_AERIAL_LANDING_ACTIONS:
            expected_ticks = source_action_elapsed_ticks
        if falcon_dive_ground_miss_mode:
            if action_name == "SWORD_DANCE_3_MID":
                expected_ticks = action_frame
            elif action_name == "DEAD_FALL":
                expected_ticks = action_frame - 1
            elif action_name == "LANDING_SPECIAL":
                expected_ticks = action_frame - 1
        if falcon_dive_ground_catch_mode:
            if action_name == "SWORD_DANCE_3_MID":
                expected_ticks = action_frame
            elif action_name == "SWORD_DANCE_4_HIGH":
                expected_ticks = None
            elif action_name == "SWORD_DANCE_4_MID":
                expected_ticks = None
            elif action_name == "LANDING_SPECIAL":
                expected_ticks = action_frame - 1
        if falcon_dive_air_catch_mode:
            if action_name == "SWORD_DANCE_3_LOW":
                expected_ticks = action_frame
            elif action_name in {"SWORD_DANCE_4_HIGH", "SWORD_DANCE_4_MID"}:
                expected_ticks = None
            elif action_name == "FALLING":
                expected_ticks = action_frame - 1
        if falcon_dive_air_miss_mode:
            if action_name == "SWORD_DANCE_3_LOW":
                expected_ticks = action_frame
            elif action_name == "DEAD_FALL":
                expected_ticks = action_frame - 1
            elif action_name == "LANDING_SPECIAL":
                expected_ticks = action_frame - 1
        if falcon_dive_air_ledge_mode:
            if action_name == "SWORD_DANCE_3_LOW":
                expected_ticks = action_frame
            elif action_name == "EDGE_CATCHING":
                expected_ticks = action_frame - 1
            elif action_name == "EDGE_HANGING":
                expected_ticks = min(8, action_frame + 6)
        if raptor_boost_route is not None:
            expected_ticks = raptor_boost_expected_ticks(
                raptor_boost_route,
                action_name,
                float(oracle["action_frame"]),
                float(oracle.get("hitlag_left", 0.0)),
            )
        if falcon_kick_route is not None:
            expected_ticks = falcon_kick_expected_ticks(
                falcon_kick_route,
                action_name,
                float(oracle["action_frame"]),
                float(oracle.get("hitlag_left", 0.0)),
            )
        if shield_hit_mode or (
            (
                raptor_boost_ground_hit_mode
                or raptor_boost_air_hit_mode
                or falcon_kick_ground_hit_mode
            )
            and float(oracle.get("hitlag_left", 0.0)) > 0.0
        ):
            expected_ticks = None
        actual_ticks = int(native["action_ticks"])
        expected_facing = int(oracle["facing"]) * horizontal_mirror
        actual_facing = int(native["facing"])
        expected_position = horizontal_mirror * scaled_f32(
            float(oracle["position_x_from_origin"]) - oracle_anchor_x
        )
        actual_position = float(native["position_x_f32_from_origin"]) - native_anchor_x
        expected_position_y = scaled_y_f32(
            float(oracle["position_y"]) - oracle_anchor_y
        )
        actual_position_y = float(native["position_y_f32_from_origin"]) - native_anchor_y
        expected_velocity_key = (
            "air_velocity_x"
            if (
                (
                    falcon_kick_ground_hit_mode
                    and float(oracle.get("opponent_damage_percent", 0.0)) > 0.0
                )
                or not bool(oracle["grounded"])
                or action_name
                in {
                    "JUMPING_FORWARD",
                    "JUMPING_BACKWARD",
                    "JUMPING_ARIAL_FORWARD",
                    "JUMPING_ARIAL_BACKWARD",
                    "FALLING",
                    "FALLING_FORWARD",
                    "FALLING_BACKWARD",
                    "FALLING_AERIAL",
                    "FALLING_AERIAL_FORWARD",
                    "FALLING_AERIAL_BACKWARD",
                    "AIRDODGE",
                    "NEUTRAL_B_FULL_CHARGE_AIR",
                }
            )
            else "ground_velocity_x"
        )
        expected_velocity = horizontal_mirror * scaled_f32(
            float(oracle[expected_velocity_key])
        )
        actual_velocity = float(native["velocity_x_f32"])
        expected_velocity_y = scaled_y_f32(float(oracle["velocity_y"]))
        actual_velocity_y = float(native["velocity_y_f32"])
        landing_transition_velocity_stale = (
            action_name
            in CHARACTER_AERIAL_LANDING_ACTIONS
            and previous_oracle is not None
            and str(previous_oracle.get("action", "")) != action_name
        )
        skip_special_physics = (
            (
                falcon_punch_air_mode
                and action_name == "NEUTRAL_B_FULL_CHARGE_AIR"
                and action_frame < 50
            )
            or (
                (falcon_dive_ground_catch_mode or falcon_dive_air_catch_mode)
                and action_name
                in {
                    "SWORD_DANCE_3_MID",
                    "SWORD_DANCE_4_HIGH",
                }
            )
            or (falcon_kick_ground_wall_mode and action_name == "SWORD_DANCE_4_LOW")
        )
        skip_vertical_position = (
            falcon_kick_air_mode
            and oracle.get("requested_fighter_y_override") is not None
        ) or (
            falcon_dive_air_catch_mode
            or falcon_dive_air_miss_position_isolated
            or falcon_dive_air_ledge_mode
            or raptor_boost_air_miss_mode
            or raptor_boost_air_hit_mode
        )
        expected_grounded = 1 if bool(oracle["grounded"]) else 0
        actual_grounded = int(native["grounded"])
        expected_support: int | None = None
        expected_surface_normal: tuple[float, float] | None = None
        if str(capture.get("stage", "")) == "BATTLEFIELD" and expected_grounded:
            collision_memory = oracle.get("surface_collision_memory")
            if isinstance(collision_memory, dict):
                surfaces = collision_memory.get("surfaces")
                floor = surfaces.get("floor") if isinstance(surfaces, dict) else None
                if isinstance(floor, dict):
                    source_floor = int(floor.get("index", 0xFFFFFFFF))
                    if 0 <= source_floor < 0xFFFFFFFF:
                        expected_support = source_floor + 1
                        normal = floor.get("normal")
                        if isinstance(normal, list) and len(normal) >= 2:
                            expected_surface_normal = (
                                binary32(float(normal[0])),
                                binary32(float(normal[1])),
                            )
        actual_support = int(native["support"])
        actual_surface_normal = (
            float(native["surface_normal_source_x_f32"]),
            float(native["surface_normal_source_y_f32"]),
        )
        expected_shield_health = binary32(float(oracle["shield_health"]))
        actual_shield_health = float(native["shield_health_f32"])
        expected_shield_strength = normalized_shield_strength(
            oracle, expected_shield_strength
        )
        actual_shield_strength = int(native["shield_strength"])
        expected_hitlag = round(float(oracle.get("hitlag_left", 0.0)))
        actual_hitlag = int(native["hitlag_ticks"])
        expected_invulnerable = (
            int(bool(oracle["invulnerable"]))
            if "invulnerable" in oracle
            else None
        )
        actual_invulnerable = int(native["invulnerable"])
        differences: list[str] = []
        if shield_clock_mode and action_name == "SHIELD_STUN":
            memory = oracle.get("hitbox_memory")
            if not isinstance(memory, dict):
                differences.append("missing_shield_hitbox_memory")
            else:
                expected_source_frame_f32 = binary32(
                    float(memory["fighter_animation_frame"])
                )
                expected_source_rate_f32 = binary32(
                    float(memory["fighter_animation_rate"])
                )
                actual_source_frame_f32 = float(
                    native["source_animation_frame_f32"]
                )
                actual_source_rate_f32 = float(
                    native["source_animation_rate_f32"]
                )
                rate_magnitude_f32 = max(
                    0.0000152587890625,
                    abs(expected_source_rate_f32),
                )
                clock_updates = max(
                    1,
                    math.ceil(
                        abs(expected_source_frame_f32) / rate_magnitude_f32
                    ),
                )
                frame_tolerance_f32 = (
                    args.animation_clock_tolerance_f32 * clock_updates
                )
                if (
                    abs(actual_source_frame_f32 - expected_source_frame_f32)
                    > frame_tolerance_f32
                ):
                    differences.append(
                        "source_animation_frame_f32 "
                        f"expected={expected_source_frame_f32} "
                        f"actual={actual_source_frame_f32} "
                        f"tolerance={frame_tolerance_f32}"
                    )
                if (
                    abs(actual_source_rate_f32 - expected_source_rate_f32)
                    > args.animation_clock_tolerance_f32
                ):
                    differences.append(
                        "source_animation_rate_f32 "
                        f"expected={expected_source_rate_f32} "
                        f"actual={actual_source_rate_f32}"
                    )
                shield_clock_checked_frames += 1
        if aerial_iasa_mode:
            qualifies_boundary = not (
                label.endswith("_settle") or label.endswith("_recover")
            )
            if qualifies_boundary:
                if expected_action is None:
                    differences.append(f"unsupported_action={action_name}")
                elif actual_action != expected_action:
                    differences.append(
                        f"action expected={action_name}/{expected_action} "
                        f"actual={actual_action}"
                    )
                elif expected_ticks is not None and actual_ticks != expected_ticks:
                    differences.append(
                        f"action_ticks expected={expected_ticks} "
                        f"actual={actual_ticks}"
                    )
            if differences:
                print(
                    "ssbm-movement-compare=fail "
                    f"frame={frame} label={oracle['label']} "
                    + " | ".join(differences)
                )
                return 1
            previous_oracle = oracle
            previous_native = native
            previous_label = label
            continue
        if expected_action is None:
            differences.append(f"unsupported_action={action_name}")
        elif actual_action != expected_action:
            differences.append(
                f"action expected={action_name}/{expected_action} actual={actual_action}"
            )
        elif expected_ticks is not None and actual_ticks != expected_ticks:
            differences.append(
                f"action_ticks expected={expected_ticks} actual={actual_ticks}"
            )
        if (
            expected_invulnerable is not None
            and actual_invulnerable != expected_invulnerable
        ):
            differences.append(
                "invulnerable "
                f"expected={expected_invulnerable} actual={actual_invulnerable}"
            )
        if actual_facing != expected_facing:
            differences.append(
                f"facing expected={expected_facing} actual={actual_facing}"
            )
        if actual_grounded != expected_grounded:
            differences.append(
                f"grounded expected={expected_grounded} actual={actual_grounded}"
            )
        if expected_support is not None and actual_support != expected_support:
            differences.append(
                f"support expected={expected_support} actual={actual_support}"
            )
        if expected_surface_normal is not None and any(
            abs(actual - expected) > 8
            for actual, expected in zip(
                actual_surface_normal, expected_surface_normal, strict=True
            )
        ):
            differences.append(
                "surface_normal_source_f32 "
                f"expected={expected_surface_normal} actual={actual_surface_normal}"
            )
        if (
            not skip_special_physics
            and abs(actual_position - expected_position) > position_tolerance_f32
        ):
            differences.append(
                f"position_f32 expected={expected_position} actual={actual_position} "
                f"delta={actual_position - expected_position}"
            )
        if (
            not skip_special_physics
            and not skip_vertical_position
            and abs(actual_position_y - expected_position_y)
            > args.position_tolerance_f32
        ):
            differences.append(
                "position_y_f32 "
                f"expected={expected_position_y} actual={actual_position_y} "
                f"delta={actual_position_y - expected_position_y}"
            )
        if (
            not skip_special_physics
            and abs(actual_velocity - expected_velocity) > args.velocity_tolerance_f32
        ):
            differences.append(
                f"velocity_f32 expected={expected_velocity} actual={actual_velocity} "
                f"delta={actual_velocity - expected_velocity}"
            )
        if (
            not skip_special_physics
            and not landing_transition_velocity_stale
            and abs(actual_velocity_y - expected_velocity_y)
            > args.velocity_tolerance_f32
        ):
            differences.append(
                "velocity_y_f32 "
                f"expected={expected_velocity_y} actual={actual_velocity_y} "
                f"delta={actual_velocity_y - expected_velocity_y}"
            )
        if previous_oracle is not None and float(oracle["shield_health"]) != float(
            previous_oracle["shield_health"]
        ):
            shield_numeric_ticks += 1
        shield_health_tolerance_f32 = (
            max(
                0.0009765625,
                shield_numeric_ticks * 0.000030517578125,
            )
            if args.shield_health_tolerance_f32 is None
            else args.shield_health_tolerance_f32
        )
        if (
            abs(actual_shield_health - expected_shield_health)
            > shield_health_tolerance_f32
        ):
            differences.append(
                "shield_health_f32 "
                f"expected={expected_shield_health} actual={actual_shield_health} "
                f"delta={actual_shield_health - expected_shield_health}"
            )
        if abs(actual_shield_strength - expected_shield_strength) > 1:
            differences.append(
                "shield_strength "
                f"expected={expected_shield_strength} "
                f"actual={actual_shield_strength} "
                f"delta={actual_shield_strength - expected_shield_strength}"
            )
        shield_memory = oracle.get("shield_memory")
        shield_state_memory = (
            oracle_rows[oracle_index + 1].get("shield_memory")
            if oracle_index + 1 < len(oracle_rows)
            and str(oracle_rows[oracle_index + 1]["action"]) == "SHIELD"
            else None
        )
        if (
            isinstance(shield_memory, dict)
            and isinstance(shield_state_memory, dict)
            and action_name == "SHIELD"
            and actual_shield_strength > 0
        ):
            expected_guard_magnitude = round(
                float(shield_state_memory["guard_magnitude"]) * 65535.0
            )
            actual_guard_magnitude = int(native["shield_magnitude"])
            expected_guard_angle = (
                round(
                    ((float(shield_state_memory["guard_angle_degrees"]) - 10.0) % 360.0)
                    * 65536.0
                    / 360.0
                )
                % 65536
            )
            actual_guard_angle = int(native["shield_angle_turn"])
            guard_angle_delta = (
                (actual_guard_angle - expected_guard_angle + 32768) % 65536
            ) - 32768
            fighter_position = shield_state_memory["fighter_position"]
            shield_matrix = shield_state_memory["shield_joint_matrix"]
            expected_center_offset_x = scaled_f32(
                float(shield_matrix[3]) - float(fighter_position[0])
            )
            expected_center_offset_y = binary32(
                scaled_y_f32(
                    float(shield_matrix[7]) - float(fighter_position[1])
                ) + 0.8
            )
            size_matrix = shield_memory["shield_joint_matrix"]
            shield_world_radius = (
                float(size_matrix[0]) ** 2
                + float(size_matrix[4]) ** 2
                + float(size_matrix[8]) ** 2
            ) ** 0.5
            expected_radius_x = scaled_f32(shield_world_radius)
            expected_radius_y = binary32(
                shield_world_radius * SSBM_TO_M4_Y_F32
            )
            geometry_pairs = (
                (
                    "shield_center_offset_x_f32",
                    expected_center_offset_x,
                    0.00146484375,
                ),
                (
                    "shield_center_offset_y_f32",
                    expected_center_offset_y,
                    0.00146484375,
                ),
                ("shield_radius_x_f32", expected_radius_x, 0.00146484375),
                ("shield_radius_y_f32", expected_radius_y, 0.00146484375),
            )
            if abs(actual_guard_magnitude - expected_guard_magnitude) > 64:
                differences.append(
                    "shield_magnitude "
                    f"expected={expected_guard_magnitude} "
                    f"actual={actual_guard_magnitude} "
                    f"delta={actual_guard_magnitude - expected_guard_magnitude}"
                )
            if abs(guard_angle_delta) > 64:
                differences.append(
                    "shield_angle_turn "
                    f"expected={expected_guard_angle} actual={actual_guard_angle} "
                    f"delta={guard_angle_delta}"
                )
            for field, expected_geometry, tolerance in geometry_pairs:
                actual_geometry = float(native[field])
                if abs(actual_geometry - expected_geometry) > tolerance:
                    differences.append(
                        f"{field} expected={expected_geometry} "
                        f"actual={actual_geometry} "
                        f"delta={actual_geometry - expected_geometry}"
                    )
        if (
            shield_hit_mode or falcon_kick_ground_hit_mode or raptor_boost_air_hit_mode
        ) and actual_hitlag != expected_hitlag:
            differences.append(
                f"hitlag expected={expected_hitlag} actual={actual_hitlag}"
            )
        if falcon_kick_ground_hit_mode or raptor_boost_air_hit_mode:
            expected_opponent_hitlag = round(
                float(oracle.get("opponent_hitlag_left", 0.0))
            )
            actual_opponent_hitlag = int(native["opponent_hitlag_ticks"])
            expected_opponent_damage_f32 = binary32(
                float(oracle.get("opponent_damage_percent", 0.0))
            )
            actual_opponent_damage_f32 = float(native["opponent_damage_f32"])
            if actual_opponent_hitlag != expected_opponent_hitlag:
                differences.append(
                    "opponent_hitlag "
                    f"expected={expected_opponent_hitlag} "
                    f"actual={actual_opponent_hitlag}"
                )
            if actual_opponent_damage_f32 != expected_opponent_damage_f32:
                differences.append(
                    "opponent_damage_f32 "
                    f"expected={expected_opponent_damage_f32} "
                    f"actual={actual_opponent_damage_f32}"
                )
        if falcon_dive_air_catch_mode:
            opponent_action_name = str(oracle["opponent_action"])
            actual_opponent_action = int(native["opponent_action_state"])
            actual_opponent_grounded = int(native["opponent_grounded"])
            oracle_hitstun = round(float(oracle.get("opponent_hitstun_left", 0.0)))
            actual_opponent_hitstun = int(native["opponent_hitstun_ticks"])
            capture_or_reaction = opponent_action_name in {
                "CAPTURE_CAPTAIN",
                "DAMAGE_AIR_3",
            }
            # The executable oracle is deliberately held at y=500 to isolate
            # the aerial route. The native runner uses a legitimate jump
            # fixture and can touch its floor for the final two reaction
            # samples; qualify every victim sample before that unrelated
            # contact, including 23/26 post-release hitstun frames.
            fixture_floor_contact = (
                opponent_action_name == "DAMAGE_AIR_3"
                and actual_opponent_grounded != 0
                and oracle_hitstun <= 3
            )
            if capture_or_reaction and not fixture_floor_contact:
                falcon_dive_target_checked_frames += 1
                expected_opponent_action = (
                    51
                    if opponent_action_name == "CAPTURE_CAPTAIN"
                    else 13 if oracle_hitstun == 26 else 14
                )
                if actual_opponent_action != expected_opponent_action:
                    differences.append(
                        "falcon_dive_opponent_action "
                        f"expected={expected_opponent_action} "
                        f"actual={actual_opponent_action}"
                    )
                if opponent_action_name == "DAMAGE_AIR_3" and (
                    actual_opponent_hitstun != oracle_hitstun
                ):
                    differences.append(
                        "falcon_dive_opponent_hitstun "
                        f"expected={oracle_hitstun} "
                        f"actual={actual_opponent_hitstun}"
                    )
                if actual_opponent_grounded != 0:
                    differences.append(
                        "falcon_dive_opponent_grounded expected=0 actual=1"
                    )
                expected_opponent_velocity_x = scaled_f32(
                    float(oracle["opponent_air_velocity_x"])
                )
                expected_opponent_velocity_y = scaled_y_f32(
                    float(oracle["opponent_velocity_y"])
                )
                actual_opponent_velocity_x = float(
                    native["opponent_velocity_x_f32"]
                )
                actual_opponent_velocity_y = float(
                    native["opponent_velocity_y_f32"]
                )
                if (
                    abs(actual_opponent_velocity_x - expected_opponent_velocity_x)
                    > args.velocity_tolerance_f32
                ):
                    differences.append(
                        "falcon_dive_opponent_velocity_x_f32 "
                        f"expected={expected_opponent_velocity_x} "
                        f"actual={actual_opponent_velocity_x}"
                    )
                if (
                    abs(actual_opponent_velocity_y - expected_opponent_velocity_y)
                    > args.velocity_tolerance_f32
                ):
                    differences.append(
                        "falcon_dive_opponent_velocity_y_f32 "
                        f"expected={expected_opponent_velocity_y} "
                        f"actual={actual_opponent_velocity_y}"
                    )
                hitbox_memory = oracle.get("hitbox_memory", {})
                if not isinstance(hitbox_memory, dict):
                    differences.append("missing_falcon_dive_hitbox_memory")
                else:
                    expected_damage = float(
                        hitbox_memory.get("opponent_damage_percent_internal", 0.0)
                    )
                    # y=500 enters Melee's off-screen magnifier and adds one
                    # unrelated percent at throw frame 25. Compare the source
                    # catch and throw damage through the last pre-magnifier row.
                    if expected_damage <= 15.93:
                        expected_damage_f32 = binary32(expected_damage)
                        actual_damage_f32 = float(native["opponent_damage_f32"])
                        if (
                            abs(actual_damage_f32 - expected_damage_f32)
                            > 0.00006103515625
                        ):
                            differences.append(
                                "falcon_dive_opponent_damage_f32 "
                                f"expected={expected_damage_f32} "
                                f"actual={actual_damage_f32}"
                            )
        if two_player_mode:
            opponent_action_name = str(oracle["opponent_action"])
            expected_opponent_action = expected_action_state(
                opponent_action_name,
                float(oracle["opponent_action_frame"]),
            )
            if shield_hit_mode and float(oracle.get("opponent_hitlag_left", 0.0)) > 0.0:
                expected_opponent_action = 13
            actual_opponent_action = int(native["opponent_action_state"])
            expected_opponent_ticks = expected_action_ticks(
                opponent_action_name,
                float(oracle["opponent_action_frame"]),
            )
            if shield_hit_mode:
                expected_opponent_ticks = None
            actual_opponent_ticks = int(native["opponent_action_ticks"])
            expected_opponent_hitlag = round(
                float(oracle.get("opponent_hitlag_left", 0.0))
            )
            actual_opponent_hitlag = int(native["opponent_hitlag_ticks"])
            expected_opponent_facing = int(oracle["opponent_facing"])
            actual_opponent_facing = int(native["opponent_facing"])
            expected_opponent_position = scaled_f32(
                float(oracle["opponent_position_x_from_origin"])
                - oracle_opponent_anchor_x
            )
            actual_opponent_position = float(
                native["opponent_position_x_f32_from_origin"]
            ) - native_opponent_anchor_x
            expected_opponent_grounded = 1 if bool(oracle["opponent_grounded"]) else 0
            actual_opponent_grounded = int(native["opponent_grounded"])
            expected_opponent_velocity = scaled_f32(
                float(oracle["opponent_ground_velocity_x"])
            )
            actual_opponent_velocity = float(native["opponent_velocity_x_f32"])
            opponent_hitlag = float(oracle.get("opponent_hitlag_left", 0.0))
            if shield_hit_mode and opponent_hitlag > 0.0:
                shield_contact_seen = True
            if expected_opponent_action is None:
                differences.append(
                    f"unsupported_opponent_action={opponent_action_name}"
                )
            elif actual_opponent_action != expected_opponent_action:
                differences.append(
                    "opponent_action "
                    f"expected={opponent_action_name}/{expected_opponent_action} "
                    f"actual={actual_opponent_action}"
                )
            elif (
                expected_opponent_ticks is not None
                and actual_opponent_ticks != expected_opponent_ticks
            ):
                differences.append(
                    "opponent_action_ticks "
                    f"expected={expected_opponent_ticks} "
                    f"actual={actual_opponent_ticks}"
                )
            if actual_opponent_facing != expected_opponent_facing:
                differences.append(
                    "opponent_facing "
                    f"expected={expected_opponent_facing} "
                    f"actual={actual_opponent_facing}"
                )
            if shield_hit_mode and actual_opponent_hitlag != expected_opponent_hitlag:
                differences.append(
                    "opponent_hitlag "
                    f"expected={expected_opponent_hitlag} "
                    f"actual={actual_opponent_hitlag}"
                )
            if (
                abs(actual_opponent_position - expected_opponent_position)
                > position_tolerance_f32
            ):
                differences.append(
                    "opponent_position_f32 "
                    f"expected={expected_opponent_position} "
                    f"actual={actual_opponent_position} "
                    "delta="
                    f"{actual_opponent_position - expected_opponent_position}"
                )
            if actual_opponent_grounded != expected_opponent_grounded:
                differences.append(
                    "opponent_grounded "
                    f"expected={expected_opponent_grounded} "
                    f"actual={actual_opponent_grounded}"
                )
            if (
                abs(actual_opponent_velocity - expected_opponent_velocity)
                > args.velocity_tolerance_f32
            ):
                differences.append(
                    "opponent_velocity_f32 "
                    f"expected={expected_opponent_velocity} "
                    f"actual={actual_opponent_velocity} "
                    "delta="
                    f"{actual_opponent_velocity - expected_opponent_velocity}"
                )
            if (
                shield_hit_mode
                and shield_contact_seen
                and opponent_hitlag == 0.0
                and previous_oracle is not None
            ):
                expected_opponent_recoil = scaled_f32(
                    float(oracle["opponent_position_x_from_origin"])
                    - float(previous_oracle["opponent_position_x_from_origin"])
                    - float(oracle["opponent_ground_velocity_x"])
                )
                actual_opponent_recoil = float(
                    native["opponent_shield_recoil_x_f32"]
                )
                if (
                    abs(actual_opponent_recoil - expected_opponent_recoil)
                    > args.velocity_tolerance_f32
                ):
                    differences.append(
                        "opponent_shield_recoil_f32 "
                        f"expected={expected_opponent_recoil} "
                        f"actual={actual_opponent_recoil} "
                        "delta="
                        f"{actual_opponent_recoil - expected_opponent_recoil}"
                    )
        if differences:
            print(
                "ssbm-movement-compare=fail "
                f"frame={frame} label={oracle['label']} " + " | ".join(differences)
            )
            return 1

        previous_oracle = oracle
        previous_native = native
        previous_label = label
        if label in CONTENT_ROUTE_ENTRY_ACTIONS:
            skip_character_content = True

    target_summary = (
        f" falcon_dive_target_frames={falcon_dive_target_checked_frames}"
        if falcon_dive_air_catch_mode
        else ""
    )
    if aerial_iasa_mode:
        target_summary += (
            f" aerial_iasa_action_frames={aerial_iasa_qualified_frames}"
        )
    if shield_clock_mode:
        if shield_clock_checked_frames == 0:
            print(
                "ssbm-movement-compare=fail reason=no-shield-clock-frames",
                file=sys.stderr,
            )
            return 1
        target_summary += f" shield_clock_frames={shield_clock_checked_frames}"
    print(
        f"ssbm-movement-compare=pass frames={len(oracle_rows)} "
        f"position_tolerance_f32={position_tolerance_f32}"
        f"{target_summary}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
