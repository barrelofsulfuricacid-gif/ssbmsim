#!/usr/bin/env python3
"""Replay one complete two-player Slippi match through production.

This is deliberately a match-start-to-game-end lane. It does not search for
anchors, inject mid-match state, omit an opponent, or stop comparison at the
first supported prefix. Every finalized source pre-frame is translated for
both ports and submitted to the native simulator in chronological order. The
report retains the first semantic divergence while still recording whether
the target consumed the complete source match.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "ssbm_slippi_extract.mjs"

sys.path.insert(0, str(ROOT / "tools"))
from ssbm_replay_differential import (  # noqa: E402
    ConfigurationError,
    PHYSICAL_L,
    PHYSICAL_R,
    PHYSICAL_Z,
    detect_ucf084_cardinal_mismatch,
    exact_raw_c,
    exact_raw_main,
    input_axis,
    input_trigger,
    load_json,
    logical_buttons,
    scale_f32,
)
from ssbm_collision import binary32  # noqa: E402


REQUIRED_STAGE_IDS = frozenset({28, 31, 32})
FALCON_CHARACTER_ID = 0
PHYSICAL_RAW_MAIN_MASK = 0x03
PHYSICAL_RAW_PAD_MASK = 0x0F


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_replay(replay: Path, parser_prefix: Path) -> dict[str, Any]:
    process = subprocess.run(
        ["node", str(EXTRACTOR), str(replay), str(parser_prefix)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise ConfigurationError(
            "Slippi extraction failed: " + process.stderr.strip()
        )
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise ConfigurationError("Slippi extractor root must be an object")
    return value


def ordered_players(settings: dict[str, Any]) -> list[dict[str, Any]]:
    players = settings.get("players")
    if not isinstance(players, list) or len(players) != 2:
        raise ConfigurationError("complete-match lane requires exactly 2 players")
    if not all(isinstance(player, dict) for player in players):
        raise ConfigurationError("player settings are malformed")
    ordered = sorted(players, key=lambda player: int(player.get("playerIndex", -1)))
    if [player.get("playerIndex") for player in ordered] != [0, 1]:
        raise ConfigurationError("complete-match lane requires player indices 0 and 1")
    return ordered


def validate_complete_match(
    replay: dict[str, Any],
    *,
    allow_missing_raw_c: bool,
) -> list[str]:
    failures: list[str] = []
    settings = replay.get("settings")
    frames = replay.get("frames")
    provenance = replay.get("inputProvenance")
    if not isinstance(settings, dict):
        return ["missing-settings"]
    try:
        players = ordered_players(settings)
    except ConfigurationError as error:
        return [str(error)]
    if any(player.get("type") != 0 for player in players):
        failures.append("non-human-player")
    if any(player.get("characterId") != FALCON_CHARACTER_ID for player in players):
        failures.append("not-falcon-ditto")
    if any(player.get("startStocks") != 4 for player in players):
        failures.append("not-four-stock")
    if any(player.get("controllerFix") != "UCF" for player in players):
        failures.append("ucf-not-enabled")
    if settings.get("isPAL") is not False:
        failures.append("not-ntsc")
    if settings.get("isTeams") is not False:
        failures.append("teams")
    if settings.get("timerType") != 2 or settings.get("startingTimerSeconds") != 480:
        failures.append("not-eight-minute-timer")
    if settings.get("itemSpawnBehavior") != 255:
        failures.append("items-enabled")
    stage_id = settings.get("stageId")
    if stage_id not in REQUIRED_STAGE_IDS:
        failures.append(f"stage:{stage_id}")
    if stage_id == 28 and settings.get("isFrozenPS") is not True:
        failures.append("pokemon-stadium-not-frozen")
    if not isinstance(replay.get("gameEnd"), dict):
        failures.append("missing-game-end")
    if not isinstance(frames, list) or not frames:
        failures.append("missing-frames")
    else:
        numbers = [frame.get("frame") for frame in frames if isinstance(frame, dict)]
        if len(numbers) != len(frames) or any(
            isinstance(number, bool) or not isinstance(number, int)
            for number in numbers
        ):
            failures.append("malformed-frame-number")
        elif (
            numbers[0] != -123
            or any(right != left + 1 for left, right in zip(numbers, numbers[1:]))
        ):
            failures.append("incomplete-finalized-frame-range")
        for frame in frames:
            samples = frame.get("players") if isinstance(frame, dict) else None
            start_seed = frame.get("startSeed") if isinstance(frame, dict) else None
            if (
                isinstance(start_seed, bool)
                or not isinstance(start_seed, int)
                or not 0 <= start_seed <= 0xFFFFFFFF
            ):
                failures.append(f"missing-frame-start-seed:{frame.get('frame')}")
                break
            if (
                not isinstance(samples, list)
                or len(samples) < 2
                or not isinstance(samples[0], dict)
                or not isinstance(samples[1], dict)
            ):
                failures.append(f"missing-player-frame:{frame.get('frame')}")
                break
            if any(
                isinstance(sample.get("pre", {}).get("seed"), bool)
                or not isinstance(sample.get("pre", {}).get("seed"), int)
                or not 0 <= sample["pre"]["seed"] <= 0xFFFFFFFF
                for sample in samples[:2]
            ):
                failures.append(f"missing-pre-frame-seed:{frame.get('frame')}")
                break
        if not failures:
            by_number = {int(frame["frame"]): frame for frame in frames}
            for frame in frames:
                frame_number = int(frame["frame"])
                for player_index in (0, 1):
                    mismatch = detect_ucf084_cardinal_mismatch(
                        replay, by_number, frame_number, player_index
                    )
                    if mismatch is not None:
                        failures.append(
                            "ucf084-cardinal-signature-mismatch:"
                            f"frame={frame_number}:player={player_index}"
                        )
                        break
                if failures:
                    break
    if not isinstance(provenance, dict):
        failures.append("missing-input-provenance")
    else:
        if (
            provenance.get("framing") != "slp-message-sizes-v1"
            or provenance.get("exactRawMainX") is not True
            or provenance.get("exactRawMainY") is not True
        ):
            failures.append("exact-raw-main-unavailable")
        exact_raw_c = (
            provenance.get("exactRawCX") is True
            and provenance.get("exactRawCY") is True
        )
        if not exact_raw_c and not allow_missing_raw_c:
            failures.append("exact-raw-c-unavailable")
    return failures


def native_player_fields(
    pre: dict[str, Any],
    *,
    allow_missing_raw_c: bool,
) -> list[int]:
    physical = int(pre["physicalButtons"])
    left = (
        65535
        if physical & (PHYSICAL_L | PHYSICAL_Z)
        else input_trigger(float(pre["physicalLTrigger"]))
    )
    right = (
        65535
        if physical & PHYSICAL_R
        else input_trigger(float(pre["physicalRTrigger"]))
    )
    raw_main = exact_raw_main(pre)
    if raw_main is None:
        raise ConfigurationError("complete match requires exact raw main X/Y")
    raw_c = exact_raw_c(pre)
    if raw_c is None:
        if not allow_missing_raw_c:
            raise ConfigurationError("complete match requires exact raw C X/Y")
        raw_c = (0, 0)
        raw_mask = PHYSICAL_RAW_MAIN_MASK
    else:
        raw_mask = PHYSICAL_RAW_PAD_MASK
    return [
        input_axis(float(pre["joystickX"])),
        input_axis(-float(pre["joystickY"])),
        input_axis(float(pre["cStickX"])),
        input_axis(-float(pre["cStickY"])),
        left,
        right,
        logical_buttons(pre),
        raw_main[0],
        raw_main[1],
        raw_c[0],
        raw_c[1],
        raw_mask,
    ]


def native_match_input(
    replay: dict[str, Any],
    *,
    allow_missing_raw_c: bool,
) -> str:
    lines: list[str] = []
    for frame in replay["frames"]:
        samples = frame["players"]
        # Official input-driven Slippi playback restores the process-global
        # HSD stream from FrameStart before stage and fighter updates. Per-
        # fighter PreFrame seeds are resync diagnostics, not the normal
        # playback boundary.
        values = [int(frame["frame"]), int(frame["startSeed"])]
        for player_index in (0, 1):
            values.extend(
                native_player_fields(
                    samples[player_index]["pre"],
                    allow_missing_raw_c=allow_missing_raw_c,
                )
            )
        lines.append(",".join(str(value) for value in values))
    return "\n".join(lines) + "\n"


def run_target(
    replay: dict[str, Any],
    runner: Path,
    *,
    allow_missing_raw_c: bool,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    settings = replay["settings"]
    players = ordered_players(settings)
    costume_ids = [player.get("characterColor") for player in players]
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 6
        for value in costume_ids
    ):
        raise ConfigurationError("Falcon costume ids are missing or invalid")
    source_input = native_match_input(
        replay, allow_missing_raw_c=allow_missing_raw_c
    )
    process = subprocess.run(
        [
            str(runner),
            "--stage-id",
            str(settings["stageId"]),
            "--seed",
            str(settings["randomSeed"]),
            "--max-ticks",
            str(len(replay["frames"]) + 1),
            "--costume-ids",
            ",".join(str(value) for value in costume_ids),
        ],
        input=source_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    rows = list(csv.DictReader(io.StringIO(process.stdout)))
    return process, rows


def expected_target_action(
    profile: dict[str, Any],
    source_action: int,
    source_pre: dict[str, Any],
    source_post: dict[str, Any],
    *,
    l_cancel_active: bool = False,
    entered_grounded: bool | None = None,
) -> int | None:
    mapping = profile["source_actions"].get(str(source_action))
    if not isinstance(mapping, dict):
        return None
    if l_cancel_active or int(source_post.get("lCancelStatus") or 0) == 1:
        l_cancel = mapping.get("l_cancel_target_action")
        if isinstance(l_cancel, int):
            return l_cancel
    if int(source_post.get("hitlagRemaining") or 0) > 0:
        hitlag = mapping.get(
            "hitlag_target_action", profile.get("hitlag_target_action")
        )
        if isinstance(hitlag, int):
            return hitlag
    if entered_grounded is None:
        entered_grounded = source_post.get("isAirborne") is False
    if entered_grounded:
        grounded = mapping.get("grounded_target_action")
        if isinstance(grounded, int):
            return grounded
    held_physical = mapping.get("physical_button_held_target_action")
    if isinstance(held_physical, dict):
        mask = held_physical.get("mask")
        target = held_physical.get("target_action")
        if (
            isinstance(mask, int)
            and mask > 0
            and isinstance(target, int)
            and int(source_pre.get("physicalButtons") or 0) & mask
        ):
            return target
    target = mapping.get("target_action")
    return target if isinstance(target, int) else None


def canonical_target_action(profile: dict[str, Any], action: int) -> int:
    """Project route-specific production states onto Melee's public action.

    The simulation may use a more specific zero-cost enum value to retain
    route-owned FallSpecial parameters. This changes only the observation
    vocabulary; clocks, motion, positions, and match outcome remain compared
    independently on every frame.
    """
    aliases = profile.get("target_action_aliases", {})
    value = aliases.get(str(action), action)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(
            f"target action alias for {action} must be an integer"
        )
    return value


def expected_target_position_f32(
    profile: dict[str, Any], source_post: dict[str, Any]
) -> tuple[float, float]:
    x_scale = profile["source_to_target_x_scale"]
    y_scale = profile["source_to_target_y_scale"]
    source_x = float(source_post["positionX"])
    source_y = float(source_post["positionY"])
    target_x = scale_f32(source_x, x_scale)
    target_y = binary32(
        float(y_scale["origin_f32"])
        + scale_f32(source_y, y_scale)
        - float(y_scale["fighter_root_to_body_center_f32"])
    )
    return target_x, target_y


def expected_target_self_velocity_f32(
    profile: dict[str, Any], source_post: dict[str, Any]
) -> tuple[float, float]:
    """Project Slippi's source-owned velocity into production units.

    Slippi 2.0.1 does not record the complete knockback velocity, but it does
    retain the fighter-owned ground/air and animation translation channels.
    Those are the exact channels production exposes as ``self_v*``.
    """
    source_x = float(
        source_post["selfAirX"]
        if bool(source_post["isAirborne"])
        else source_post["selfGroundX"]
    )
    source_y = float(source_post["selfY"])
    return (
        scale_f32(source_x, profile["source_to_target_x_scale"]),
        scale_f32(source_y, profile["source_to_target_y_scale"]),
    )


def equivalent_collision_adjusted_displacement(
    *,
    source_position: float,
    target_position: float,
    source_displacement: float,
    target_displacement: float,
    source_self_velocity: float,
    target_self_velocity: float,
    tolerance: float,
) -> bool:
    """Recognize the same collision clamp without hiding motion drift.

    A tiny accepted residual on the preceding position can appear as a larger
    displacement error when both engines clamp to the same floor endpoint.
    This exception is valid only when the current positions and the unclamped
    fighter-owned velocities match tightly, and collision changed the motion
    in both engines.  A global displacement-tolerance increase would also hide
    ordinary movement errors and is deliberately not used.
    """
    return (
        abs(source_position - target_position) <= tolerance
        and abs(source_self_velocity - target_self_velocity) <= tolerance
        and abs(source_displacement - source_self_velocity) > tolerance
        and abs(target_displacement - target_self_velocity) > tolerance
    )


def first_divergence(
    replay: dict[str, Any],
    target_rows: list[dict[str, str]],
    profile: dict[str, Any],
    *,
    ignore_position: bool = False,
    displacement_tolerance_f32: float | None = None,
) -> dict[str, Any] | None:
    source_frames = replay["frames"]
    l_cancel_action: list[int | None] = [None, None]
    source_action_entry: list[tuple[int, bool] | None] = [None, None]
    previous_positions: list[tuple[float, float, float, float] | None] = [
        None,
        None,
    ]
    for row_index, source_frame in enumerate(source_frames):
        if row_index >= len(target_rows):
            return {
                "row": row_index,
                "source_frame": source_frame["frame"],
                "field": "target-row",
                "source": "present",
                "target": "missing",
            }
        target = target_rows[row_index]
        if int(target["source_frame"]) != int(source_frame["frame"]):
            return {
                "row": row_index,
                "source_frame": source_frame["frame"],
                "field": "source-frame-alignment",
                "source": source_frame["frame"],
                "target": target["source_frame"],
            }
        for player_index in (0, 1):
            source_post = source_frame["players"][player_index]["post"]
            source_pre = source_frame["players"][player_index]["pre"]
            source_action = int(source_post["actionStateId"])
            if (
                source_action_entry[player_index] is None
                or source_action_entry[player_index][0] != source_action
            ):
                source_action_entry[player_index] = (
                    source_action,
                    source_post.get("isAirborne") is False,
                )
            if l_cancel_action[player_index] != source_action:
                l_cancel_action[player_index] = None
            if int(source_post.get("lCancelStatus") or 0) == 1:
                l_cancel_action[player_index] = source_action
            expected_action = expected_target_action(
                profile,
                source_action,
                source_pre,
                source_post,
                l_cancel_active=l_cancel_action[player_index] == source_action,
                entered_grounded=source_action_entry[player_index][1],
            )
            if expected_action is None:
                return {
                    "row": row_index,
                    "source_frame": source_frame["frame"],
                    "player": player_index,
                    "field": "action-mapping",
                    "source": source_action,
                    "target": "unmapped",
                }
            raw_target_action = int(target[f"p{player_index}_action"])
            target_action = canonical_target_action(profile, raw_target_action)
            if target_action != expected_action:
                return {
                    "row": row_index,
                    "source_frame": source_frame["frame"],
                    "player": player_index,
                    "field": "action",
                    "source_action": source_action,
                    "expected_target_action": expected_action,
                    "raw_target_action": raw_target_action,
                    "target_action": target_action,
                }
            expected_x_f32, expected_y_f32 = expected_target_position_f32(
                profile, source_post
            )
            target_x_f32 = float(target[f"p{player_index}_x_f32"])
            target_y_f32 = float(target[f"p{player_index}_y_f32"])
            expected_self_vx_f32, expected_self_vy_f32 = (
                expected_target_self_velocity_f32(profile, source_post)
            )
            target_self_vx_f32 = float(target[f"p{player_index}_self_vx_f32"])
            target_self_vy_f32 = float(target[f"p{player_index}_self_vy_f32"])
            comparisons = {
                "facing": (
                    round(float(source_post["facingDirection"])),
                    int(target[f"p{player_index}_facing"]),
                ),
                "grounded": (
                    0 if bool(source_post["isAirborne"]) else 1,
                    int(target[f"p{player_index}_grounded"]),
                ),
                "stocks": (
                    int(source_post["stocksRemaining"]),
                    int(target[f"p{player_index}_stocks"]),
                ),
                "damage_f32": (
                    binary32(float(source_post["percent"])),
                    float(target[f"p{player_index}_damage_f32"]),
                ),
                "position_x_f32": (
                    expected_x_f32,
                    target_x_f32,
                ),
                "position_y_f32": (
                    expected_y_f32,
                    target_y_f32,
                ),
            }
            collision_adjusted_axes: set[str] = set()
            previous = previous_positions[player_index]
            if previous is not None:
                previous_source_x, previous_source_y, previous_target_x, previous_target_y = previous
                velocity_tolerance = float(
                    profile["comparison"]["velocity_tolerance_f32"]
                )
                source_displacement_x = expected_x_f32 - previous_source_x
                target_displacement_x = target_x_f32 - previous_target_x
                source_displacement_y = expected_y_f32 - previous_source_y
                target_displacement_y = target_y_f32 - previous_target_y
                if equivalent_collision_adjusted_displacement(
                    source_position=expected_x_f32,
                    target_position=target_x_f32,
                    source_displacement=source_displacement_x,
                    target_displacement=target_displacement_x,
                    source_self_velocity=expected_self_vx_f32,
                    target_self_velocity=target_self_vx_f32,
                    tolerance=velocity_tolerance,
                ):
                    collision_adjusted_axes.add("x")
                if equivalent_collision_adjusted_displacement(
                    source_position=expected_y_f32,
                    target_position=target_y_f32,
                    source_displacement=source_displacement_y,
                    target_displacement=target_displacement_y,
                    source_self_velocity=expected_self_vy_f32,
                    target_self_velocity=target_self_vy_f32,
                    tolerance=velocity_tolerance,
                ):
                    collision_adjusted_axes.add("y")
                comparisons = {
                    "displacement_x_f32": (
                        source_displacement_x,
                        target_displacement_x,
                    ),
                    "displacement_y_f32": (
                        source_displacement_y,
                        target_displacement_y,
                    ),
                    **comparisons,
                }
            previous_positions[player_index] = (
                expected_x_f32,
                expected_y_f32,
                target_x_f32,
                target_y_f32,
            )
            for field, (source_value, target_value) in comparisons.items():
                if field == "displacement_x_f32" and "x" in collision_adjusted_axes:
                    continue
                if field == "displacement_y_f32" and "y" in collision_adjusted_axes:
                    continue
                if ignore_position and field.startswith("position_"):
                    continue
                if (
                    ignore_position
                    and int(source_frame["frame"]) < 0
                    and field.startswith("displacement_")
                ):
                    continue
                tolerance = (
                    float(profile["comparison"]["position_tolerance_f32"])
                    if field.startswith("position_")
                    else (
                        displacement_tolerance_f32
                        if displacement_tolerance_f32 is not None
                        else float(
                            profile["comparison"]["velocity_tolerance_f32"]
                        )
                    )
                    if field.startswith("displacement_")
                    else float(profile["comparison"]["damage_tolerance_f32"])
                    if field == "damage_f32"
                    else 0
                )
                if abs(source_value - target_value) > tolerance:
                    return {
                        "row": row_index,
                        "source_frame": source_frame["frame"],
                        "player": player_index,
                        "field": field,
                        "source": source_value,
                        "target": target_value,
                        "tolerance": tolerance,
                    }
    if len(target_rows) != len(source_frames):
        return {
            "row": len(source_frames),
            "source_frame": None,
            "field": "target-extra-rows",
            "source": len(source_frames),
            "target": len(target_rows),
        }
    return None


def winner_mask(game_end: dict[str, Any]) -> int | None:
    placements = game_end.get("placements")
    if not isinstance(placements, list):
        return None
    mask = 0
    for placement in placements:
        if (
            isinstance(placement, dict)
            and placement.get("position") == 0
            and placement.get("playerIndex") in (0, 1)
        ):
            mask |= 1 << int(placement["playerIndex"])
    return mask or None


def scan_candidate(
    replay_path: Path,
    parser_prefix: Path,
    *,
    allow_missing_raw_c: bool,
) -> dict[str, Any]:
    try:
        replay = extract_replay(replay_path, parser_prefix)
        failures = validate_complete_match(
            replay, allow_missing_raw_c=allow_missing_raw_c
        )
        return {
            "path": str(replay_path),
            "sha256": sha256(replay_path),
            "stage_id": replay.get("settings", {}).get("stageId"),
            "frames": len(replay.get("frames", [])),
            "input_provenance": replay.get("inputProvenance"),
            "failures": failures,
            "status": "qualifying" if not failures else "configuration-mismatch",
        }
    except (ConfigurationError, OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "path": str(replay_path),
            "failures": [f"parse-error:{error}"],
            "status": "invalid",
        }


def scan_directory(args: argparse.Namespace) -> int:
    directory = Path(args.scan_directory).resolve()
    parser_prefix = Path(args.parser_prefix).resolve()
    replay_paths = sorted(directory.glob("*.slp"))
    started = time.perf_counter()

    def inspect(path: Path) -> dict[str, Any]:
        return scan_candidate(
            path,
            parser_prefix,
            allow_missing_raw_c=args.allow_missing_raw_c,
        )

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        entries = list(executor.map(inspect, replay_paths))
    report = {
        "schema": "ssbm-full-match-corpus-scan-v1",
        "directory": str(directory),
        "files": len(entries),
        "qualifying": sum(entry["status"] == "qualifying" for entry in entries),
        "configuration_mismatches": sum(
            entry["status"] == "configuration-mismatch" for entry in entries
        ),
        "invalid": sum(entry["status"] == "invalid" for entry in entries),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "entries": entries,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report["qualifying"] > 0 else 1


def run(args: argparse.Namespace) -> int:
    if args.scan_directory is not None:
        return scan_directory(args)
    if args.replay is None or args.runner is None:
        raise ConfigurationError("single-match mode requires REPLAY and --runner")
    replay_path = Path(args.replay).resolve()
    runner = Path(args.runner).resolve()
    parser_prefix = Path(args.parser_prefix).resolve()
    profile = load_json(Path(args.profile).resolve())
    replay = extract_replay(replay_path, parser_prefix)
    failures = validate_complete_match(
        replay, allow_missing_raw_c=args.allow_missing_raw_c
    )
    report: dict[str, Any] = {
        "schema": "ssbm-full-match-differential-report-v1",
        "replay": str(replay_path),
        "replay_sha256": sha256(replay_path),
        "stage_id": replay.get("settings", {}).get("stageId"),
        "source_frames": len(replay.get("frames", [])),
        "source_first_frame": (
            replay["frames"][0]["frame"] if replay.get("frames") else None
        ),
        "source_last_frame": (
            replay["frames"][-1]["frame"] if replay.get("frames") else None
        ),
        "source_game_end": replay.get("gameEnd"),
        "input_provenance": replay.get("inputProvenance"),
        "setup_failures": failures,
    }
    if failures:
        # A replay that does not prove the configured disc/modifier/input
        # contract is outside the qualifying corpus.  It is not an
        # unsupported gameplay prefix: no production frame was executed.
        report["status"] = "configuration-mismatch"
    else:
        process, target_rows = run_target(
            replay,
            runner,
            allow_missing_raw_c=args.allow_missing_raw_c,
        )
        divergence = first_divergence(
            replay,
            target_rows,
            profile,
            ignore_position=args.diagnostic_ignore_position,
            displacement_tolerance_f32=(
                args.diagnostic_displacement_tolerance_f32
            ),
        )
        source_winner = winner_mask(replay["gameEnd"])
        target_winner = (
            int(target_rows[-1]["winner_mask"]) if target_rows else None
        )
        terminal_match = bool(
            target_rows
            and int(target_rows[-1]["terminated"]) == 1
            and source_winner is not None
            and target_winner == source_winner
        )
        report.update(
            {
                "target_exit_code": process.returncode,
                "target_stderr": process.stderr.strip(),
                "target_rows": len(target_rows),
                "consumed_complete_match": len(target_rows) == len(replay["frames"]),
                "first_divergence": divergence,
                "source_winner_mask": source_winner,
                "target_winner_mask": target_winner,
                "terminal_match": terminal_match,
                "diagnostic_ignore_position": args.diagnostic_ignore_position,
                "diagnostic_displacement_tolerance_f32": (
                    args.diagnostic_displacement_tolerance_f32
                ),
            }
        )
        report["status"] = (
            "pass"
            if process.returncode == 0
            and divergence is None
            and report["consumed_complete_match"]
            and terminal_match
            else "diverged"
        )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report["status"] == "pass" else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("replay", nargs="?")
    result.add_argument("--runner")
    result.add_argument("--parser-prefix", required=True)
    result.add_argument("--scan-directory")
    result.add_argument("--jobs", type=int, default=8)
    result.add_argument(
        "--profile",
        default=str(ROOT / "tools" / "ssbm_falcon_replay_profile.json"),
    )
    result.add_argument("--output")
    result.add_argument(
        "--allow-missing-raw-c",
        action="store_true",
        help="diagnostic only; exact corpus qualification keeps this disabled",
    )
    result.add_argument(
        "--diagnostic-ignore-position",
        action="store_true",
        help=(
            "diagnostic only; skip position comparisons so a later semantic "
            "boundary can be localized (never valid for qualification)"
        ),
    )
    result.add_argument(
        "--diagnostic-displacement-tolerance-f32",
        type=float,
        help=(
            "diagnostic only; override the per-frame displacement tolerance "
            "without weakening the qualifying profile"
        ),
    )
    return result


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
