#!/usr/bin/env python3
"""Replay one complete itemless tournament match through the native SSBM runtime."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "ssbm_slippi_extract.mjs"
LEGAL_STAGE_IDS = frozenset({2, 3, 8, 28, 31, 32})
# Slippi external IDs include Zelda and Sheik separately. Nana is an Ice
# Climbers subfighter rather than an independently selectable character.
ACCEPTANCE_CHARACTER_IDS = frozenset(range(26))
EXTRACT_CACHE_SCHEMA = 2
REPORT_SCHEMA = 2


class ReplayError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extractor_identity() -> str:
    digest = hashlib.sha256()
    for path in (EXTRACTOR, ROOT / "tools" / "ssbm_replay_mods.mjs"):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def f32(value: Any) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def extract_replay(
    replay: Path,
    parser_prefix: Path,
    cache_dir: Path | None,
    node: str,
    *,
    endpoint_inputs: bool = False,
) -> dict[str, Any]:
    replay_digest = sha256(replay)
    if endpoint_inputs and cache_dir is not None:
        raise ReplayError("endpoint projection cannot use the all-frame cache")
    cache_path = None if cache_dir is None else cache_dir / f"{replay_digest}.json"
    if cache_path is not None and cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and cached.get("schema") == EXTRACT_CACHE_SCHEMA
            and cached.get("replay_sha256") == replay_digest
            and isinstance(cached.get("replay"), dict)
        ):
            if cached.get("extractor_sha256") == extractor_identity():
                return cached["replay"]
        else:
            raise ReplayError(f"invalid extracted replay cache: {cache_path}")
    node_paths = [EXTRACTOR.resolve(), replay.resolve(), parser_prefix.resolve()]
    if node.lower().endswith(".exe"):
        converted: list[str] = []
        for path in node_paths:
            conversion = subprocess.run(
                ["wslpath", "-w", str(path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            if conversion.returncode != 0:
                raise ReplayError(
                    "Windows Node path conversion failed: "
                    + conversion.stderr.strip()
                )
            converted.append(conversion.stdout.strip())
        node_arguments = converted
    else:
        node_arguments = [str(path) for path in node_paths]
    process = subprocess.run(
        [node, *node_arguments, *(["--endpoint-inputs"] if endpoint_inputs else [])],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise ReplayError("Slippi extraction failed: " + process.stderr.strip())
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise ReplayError("Slippi extractor root must be an object")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "schema": EXTRACT_CACHE_SCHEMA,
                    "replay_sha256": replay_digest,
                    "extractor_sha256": extractor_identity(),
                    "replay": value,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    return value


def active_players(settings: dict[str, Any]) -> list[dict[str, Any]]:
    players = settings.get("players")
    if not isinstance(players, list):
        raise ReplayError("missing player settings")
    active = [player for player in players if isinstance(player, dict)]
    if len(active) != 2:
        raise ReplayError("native complete-match lane requires two players")
    active.sort(key=lambda player: int(player.get("playerIndex", -1)))
    ports = [player.get("playerIndex") for player in active]
    if any(isinstance(port, bool) or not isinstance(port, int) for port in ports):
        raise ReplayError("player ports are missing")
    if len(set(ports)) != 2 or any(not 0 <= int(port) < 4 for port in ports):
        raise ReplayError("player ports are invalid")
    return active


def validate_replay(
    replay: dict[str, Any],
    *,
    endpoint_frame_count: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = replay.get("settings")
    frames = replay.get("frames")
    provenance = replay.get("inputProvenance")
    if not isinstance(settings, dict):
        raise ReplayError("missing settings")
    if replay.get("schema") != EXTRACT_CACHE_SCHEMA:
        raise ReplayError("Slippi extraction does not include canonical followers")
    mods = settings.get("nativeReplayMods")
    if not isinstance(mods, dict) or mods.get("schema") != 1 or type(mods.get("fdSceneMode")) is not int or mods["fdSceneMode"] not in (0, 1, 2):
        raise ReplayError("missing or unsupported native replay modification settings")
    players = active_players(settings)
    if any(type(player.get("cpuLevel")) is not int or not 0 <= player["cpuLevel"] <= 9
           for player in players):
        raise ReplayError("missing or invalid recorded CPU level")
    if any(player.get("type") != 0 for player in players):
        raise ReplayError("only human players are accepted")
    if any(
        player.get("characterId") not in ACCEPTANCE_CHARACTER_IDS
        for player in players
    ):
        raise ReplayError("match contains a character outside the acceptance roster")
    if any(player.get("startStocks") != 4 for player in players):
        raise ReplayError("match is not four-stock")
    if any(player.get("controllerFix") != "UCF" for player in players):
        raise ReplayError("match is not explicitly UCF")
    if settings.get("isPAL") is not False or settings.get("isTeams") is not False:
        raise ReplayError("match is not NTSC singles")
    if settings.get("timerType") != 2 or settings.get("startingTimerSeconds") != 480:
        raise ReplayError("match is not eight-minute timed stock")
    if settings.get("itemSpawnBehavior") != 255:
        raise ReplayError("items are enabled")
    stage = settings.get("stageId")
    if stage not in LEGAL_STAGE_IDS:
        raise ReplayError(f"stage {stage!r} is not in the legal-stage slice")
    if stage == 3 and settings.get("isFrozenPS") is not True:
        raise ReplayError("Pokemon Stadium is not frozen")
    if not isinstance(settings.get("randomSeed"), int):
        raise ReplayError("missing GameStart random seed")
    if not isinstance(replay.get("gameEnd"), dict):
        raise ReplayError("missing GameEnd event")
    if not isinstance(frames, list) or not frames:
        raise ReplayError("missing finalized frames")
    numbers = [frame.get("frame") for frame in frames if isinstance(frame, dict)]
    expected_first = -123 if endpoint_frame_count is None else endpoint_frame_count - 124
    if endpoint_frame_count is not None and (
        type(endpoint_frame_count) is not int or endpoint_frame_count < 1 or len(frames) != 1
    ):
        raise ReplayError("invalid prepared endpoint frame count")
    if len(numbers) != len(frames) or numbers[0] != expected_first or any(
        not isinstance(left, int) or right != left + 1
        for left, right in zip(numbers, numbers[1:])
    ):
        raise ReplayError("finalized frame range is not contiguous from -123")
    if not isinstance(provenance, dict) or any(
        provenance.get(field) is not True
        for field in ("exactRawMainX", "exactRawMainY", "exactRawCX", "exactRawCY")
    ):
        raise ReplayError("exact raw stick bytes are unavailable")
    ports = [int(player["playerIndex"]) for player in players]
    for frame in frames:
        seed = frame.get("startSeed")
        samples = frame.get("players")
        followers = frame.get("followers")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
            raise ReplayError(f"missing FrameStart seed at {frame.get('frame')}")
        if not isinstance(samples, list) or any(
            port >= len(samples) or not isinstance(samples[port], dict)
            for port in ports
        ):
            raise ReplayError(f"missing player frame at {frame.get('frame')}")
        if not isinstance(followers, list) or any(
            port >= len(followers) for port in ports
        ):
            raise ReplayError(f"missing follower frame lane at {frame.get('frame')}")
    return settings, players


def player_input(pre: dict[str, Any]) -> list[str]:
    required = (
        "physicalButtons",
        "joystickX",
        "joystickY",
        "cStickX",
        "cStickY",
        "physicalLTrigger",
        "physicalRTrigger",
        "rawJoystickX",
        "rawJoystickY",
        "rawCStickX",
        "rawCStickY",
    )
    if any(pre.get(field) is None for field in required):
        raise ReplayError("complete physical controller sample is missing")
    return [
        str(int(pre["physicalButtons"])),
        repr(f32(pre["joystickX"])),
        repr(f32(pre["joystickY"])),
        repr(f32(pre["cStickX"])),
        repr(f32(pre["cStickY"])),
        repr(f32(pre["physicalLTrigger"])),
        repr(f32(pre["physicalRTrigger"])),
        str(int(pre["rawJoystickX"])),
        str(int(pre["rawJoystickY"])),
        str(int(pre["rawCStickX"])),
        str(int(pre["rawCStickY"])),
    ]


def native_input(replay: dict[str, Any], players: list[dict[str, Any]]) -> str:
    ports = [int(player["playerIndex"]) for player in players]
    lines: list[str] = []
    for frame in replay["frames"]:
        values = [str(int(frame["frame"])), str(int(frame["startSeed"]))]
        for port in ports:
            values.extend(player_input(frame["players"][port]["pre"]))
        lines.append(",".join(values))
    return "\n".join(lines) + "\n"


def extraction_cache_path(cache_dir: Path, replay_digest: str, scope: str) -> Path:
    suffix = ".endpoint.json" if scope == "final-state" else ".json"
    return cache_dir / (replay_digest + suffix)


def endpoint_preparation_identity(parser_prefix: Path) -> dict[str, str]:
    # A prepared input stream is independent of the runner and asset pack. It
    # must be rebuilt when its parser, extraction or validation code changes.
    package = parser_prefix / "node_modules" / "@slippi" / "slippi-js"
    digest = hashlib.sha256()
    sources = [package / "package.json", *sorted((package / "dist").rglob("*.cjs"))]
    for source in sources:
        digest.update(source.relative_to(package).as_posix().encode())
        digest.update(bytes.fromhex(sha256(source)))
    return {"preparer_sha256": sha256(Path(__file__)),
            "extractor_sha256": extractor_identity(), "parser_sha256": digest.hexdigest()}


def encode_prepared_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_endpoint(replay_path: Path, parser_prefix: Path,
                     cache_dir: Path | None, node: str) -> dict:
    """Validate once, cache physical inputs plus the final recorded frame.

    The cache never contains intermediate expected states or native output.
    Every screen still executes the entire native match from GameStart.
    """
    replay_digest = sha256(replay_path)
    identity = {"schema": 1, "kind": "native-inputs-and-recorded-endpoint",
                "replay_sha256": replay_digest, **endpoint_preparation_identity(parser_prefix)}
    path = (extraction_cache_path(cache_dir, replay_digest, "final-state")
            if cache_dir is not None else None)
    if path is not None and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cached, dict):
                raise ReplayError("prepared endpoint cache must be an object")
            if all(cached.get(key) == value for key, value in identity.items()):
                payload = cached["payload"]
                encoded = encode_prepared_payload(payload)
                if hashlib.sha256(encoded.encode()).hexdigest() != cached["payload_sha256"]:
                    raise ReplayError("prepared endpoint payload checksum mismatch")
                validate_replay(payload["replay"], endpoint_frame_count=payload["source_frames"])
                inputs = payload["input_csv"]
                if (not isinstance(inputs, str) or not inputs.endswith("\n")
                        or inputs.count("\n") != payload["source_frames"]):
                    raise ReplayError("prepared physical input frame count mismatch")
                return payload
        except (KeyError, TypeError, ValueError) as error:
            raise ReplayError(f"invalid prepared endpoint cache: {path}: {error}") from error
        # An old producer is safe to regenerate, but a corrupt current cache
        # fails closed rather than silently supplying unvalidated inputs.
    legacy = None if cache_dir is None else cache_dir / f"{replay_digest}.json"
    if legacy is not None and legacy.is_file():
        replay = extract_replay(replay_path, parser_prefix, cache_dir, node)
    else:
        replay = extract_replay(replay_path, parser_prefix, None, node, endpoint_inputs=True)
    _, players = validate_replay(replay)
    inputs = native_input(replay, players)
    endpoint = {key: replay[key] for key in ("schema", "settings", "gameEnd", "inputProvenance")}
    endpoint["frames"] = [replay["frames"][-1]]
    payload = {"replay": endpoint, "source_frames": len(replay["frames"]), "input_csv": inputs}
    if path is not None:
        encoded = encode_prepared_payload(payload)
        envelope = {**identity, "payload_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "payload": payload}
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish one complete file so concurrent/interrupted screening cannot
        # expose a partial header, input stream or endpoint.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(envelope, stream, separators=(",", ":"), allow_nan=False)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return payload


def run_native(
    replay: dict[str, Any],
    settings: dict[str, Any],
    players: list[dict[str, Any]],
    runner: Path,
    asset_pack: Path,
    *,
    final_state_only: bool = False,
    arithmetic_profile: int = 0,
    input_csv: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    ports = [int(player["playerIndex"]) for player in players]
    characters = [int(player["characterId"]) for player in players]
    costumes = [int(player["characterColor"]) for player in players]
    process = subprocess.run(
        [
            str(runner),
            str(asset_pack),
            "--stage-id",
            str(settings["stageId"]),
            "--seed",
            str(settings["randomSeed"]),
            "--enabled-items",
            str(settings["enabledItems"]),
            "--item-spawn-behavior",
            str(settings["itemSpawnBehavior"]),
            "--character-ids",
            ",".join(map(str, characters)),
            "--costume-ids",
            ",".join(map(str, costumes)),
            "--cpu-levels",
            ",".join(str(player["cpuLevel"]) for player in players),
            "--ports",
            ",".join(map(str, ports)),
            "--frozen-stadium",
            "1" if settings["stageId"] == 3 else "0",
            "--slippi-online",
            "1" if settings.get("gameMode") == 8 else "0",
            "--neutral-spawns",
            "1",
            "--friendly-fire",
            "1" if settings.get("friendlyFireEnabled") else "0",
            "--arithmetic-profile", str(arithmetic_profile),
            "--fd-scene-mode", str(settings["nativeReplayMods"]["fdSceneMode"]),
            *(["--final-state-only", "1"] if final_state_only else []),
        ],
        input=native_input(replay, players) if input_csv is None else input_csv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return process, list(csv.DictReader(io.StringIO(process.stdout)))


def first_divergence(
    replay: dict[str, Any],
    players: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    compare_start_rng: bool = True,
) -> dict[str, Any] | None:
    frames = replay["frames"]
    ports = [int(player["playerIndex"]) for player in players]
    for index, (frame, row) in enumerate(zip(frames, rows)):
        if int(row["source_frame"]) != int(frame["frame"]):
            return {
                "frame": frame["frame"],
                "field": "frame-alignment",
                "native": row["source_frame"],
            }
        if compare_start_rng and int(row["rng"]) != int(frame["startSeed"]):
            return {
                "frame": frame["frame"],
                "field": "rng",
                "source": frame["startSeed"],
                "native": int(row["rng"]),
            }
        fighter_lanes = (
            ("player", frame["players"], "p"),
            ("follower", frame["followers"], "p"),
        )
        for fighter_type, samples, prefix in fighter_lanes:
            for output_index, port in enumerate(ports):
                sample = samples[port]
                follower_suffix = "f" if fighter_type == "follower" else ""
                column_prefix = f"{prefix}{output_index}{follower_suffix}_"
                source_present = sample is not None
                native_present = int(row[column_prefix + "present"])
                if native_present != int(source_present):
                    return {
                        "frame": frame["frame"],
                        "player_port": port,
                        "fighter_type": fighter_type,
                        "field": "present",
                        "source": int(source_present),
                        "native": native_present,
                    }
                if not source_present:
                    continue
                post = sample["post"]
                expected = {
                    "action": int(post["actionStateId"]),
                    "x": f32(post["positionX"]),
                    "y": f32(post["positionY"]),
                    "facing": f32(post["facingDirection"]),
                    "damage": f32(post["percent"]),
                    "shield": f32(post["shieldSize"]),
                    "self_vx": f32(
                        post["selfAirX"]
                        if post["isAirborne"]
                        else post["selfGroundX"]
                    ),
                    "self_vy": f32(post["selfY"]),
                    "attack_vx": f32(post["selfAttackX"]),
                    "attack_vy": f32(post["selfAttackY"]),
                    "hitlag": f32(post["hitlagRemaining"]),
                    "anim_frame": f32(post["actionStateCounter"]),
                    "ground_id": int(post["lastGroundId"]),
                    "stocks": int(post["stocksRemaining"]),
                    "jumps": int(post["jumpsRemaining"]),
                    "airborne": 1 if post["isAirborne"] else 0,
                }
                for field, source_value in expected.items():
                    native_text = row[column_prefix + field]
                    native_value: int | float
                    if isinstance(source_value, float):
                        native_value = f32(native_text)
                    else:
                        native_value = int(native_text)
                    if native_value != source_value:
                        return {
                            "frame": frame["frame"],
                            "player_port": port,
                            "fighter_type": fighter_type,
                            "field": field,
                            "source": source_value,
                            "native": native_value,
                        }
    if len(rows) != len(frames):
        return {
            "frame": frames[len(rows)]["frame"] if len(rows) < len(frames) else None,
            "field": "frame-count",
            "source": len(frames),
            "native": len(rows),
        }
    return None


def final_state_divergence(replay, players, rows, *, source_frames=None):
    """Compare only the endpoint, while requiring every input to be executed.

    Slippi's FrameStart RNG is not a final-state observation. Keep its
    comparison in the all-frame diagnostic, not this endpoint screen.
    """
    expected_frames = len(replay["frames"]) if source_frames is None else source_frames
    if len(rows) != 1:
        return {"field": "endpoint-row-count", "source": 1, "native": len(rows)}
    executed = int(rows[0]["executed_frames"])
    if executed != expected_frames:
        return {"field": "executed-frame-count", "source": expected_frames,
                "native": executed}
    endpoint = {**replay, "frames": [replay["frames"][-1]]}
    return first_divergence(endpoint, players, rows, compare_start_rng=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("replay", type=Path)
    parser.add_argument("--parser-prefix", type=Path, required=True)
    parser.add_argument(
        "--node",
        default="node",
        help="Node.js executable; WSL paths are converted for a .exe runtime",
    )
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--asset-pack", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--arithmetic-profile", type=int, choices=(0, 1), default=0,
                        help="0: fused binary64; 1: separate binary64; fixed for the complete match")
    parser.add_argument("--comparison-scope", choices=("all-frames", "final-state"),
                        default="all-frames",
                        help="final-state screens candidates using only the replay endpoint")
    parser.add_argument(
        "--native-csv",
        type=Path,
        help="write native recorded-field output; final-state mode emits one endpoint row",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="write the validated physical-input stream for native debugger reuse",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=ROOT / "build" / "ssbm-native" / "replay-cache",
        help="hash-keyed cache for the expensive finalized Slippi extraction",
    )
    args = parser.parse_args()

    try:
        started = time.perf_counter()
        if args.comparison_scope == "final-state":
            prepared = prepare_endpoint(args.replay, args.parser_prefix, args.cache_dir, args.node)
            replay, source_frames = prepared["replay"], prepared["source_frames"]
            settings, players = validate_replay(replay, endpoint_frame_count=source_frames)
            input_csv = prepared["input_csv"]
        else:
            replay = extract_replay(args.replay, args.parser_prefix, args.cache_dir, args.node)
            settings, players = validate_replay(replay)
            source_frames = len(replay["frames"])
            input_csv = native_input(replay, players)
        prepared_at = time.perf_counter()
        if args.input_csv is not None:
            args.input_csv.parent.mkdir(parents=True, exist_ok=True)
            args.input_csv.write_text(
                input_csv, encoding="utf-8"
            )
        process, rows = run_native(
            replay, settings, players, args.runner, args.asset_pack,
            final_state_only=args.comparison_scope == "final-state",
            arithmetic_profile=args.arithmetic_profile,
            input_csv=input_csv,
        )
        simulated_at = time.perf_counter()
        if args.native_csv is not None:
            args.native_csv.parent.mkdir(parents=True, exist_ok=True)
            args.native_csv.write_text(process.stdout, encoding="utf-8")
        divergence = (final_state_divergence(replay, players, rows, source_frames=source_frames)
                      if args.comparison_scope == "final-state"
                      else first_divergence(replay, players, rows))
        compared_at = time.perf_counter()
        report = {
            "schema": REPORT_SCHEMA,
            "comparison_scope": args.comparison_scope,
            "arithmetic_profile": args.arithmetic_profile,
            "arithmetic_profile_provenance": "run configuration; recording mode unverified",
            "claim_boundary": "recorded-slippi-fields-not-full-canonical-oracle",
            "replay": str(args.replay.resolve()),
            "replay_sha256": sha256(args.replay),
            "asset_pack_sha256": sha256(args.asset_pack),
            "runner_sha256": sha256(args.runner),
            "stage_id": settings["stageId"],
            "player_ports": [player["playerIndex"] for player in players],
            "character_ids": [player["characterId"] for player in players],
            "cpu_levels": [player["cpuLevel"] for player in players],
            "replay_modifications": settings["nativeReplayMods"],
            "source_frames": source_frames,
            "native_frames": len(rows),
            "executed_frames": int(rows[-1]["executed_frames"]) if rows else 0,
            "runner_exit_code": process.returncode,
            "runner_stderr": process.stderr.strip(),
            "first_divergence": divergence,
            "complete_exact": process.returncode == 0 and divergence is None,
            "timing_seconds": {"prepare_inputs": prepared_at - started,
                               "native_process_and_output": simulated_at - prepared_at,
                               "compare": compared_at - simulated_at},
        }
    except (KeyError, TypeError, ValueError, ReplayError) as error:
        report = {
            "schema": REPORT_SCHEMA,
            "complete_exact": False,
            "configuration_error": str(error),
        }

    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report.get("complete_exact") else 1


if __name__ == "__main__":
    raise SystemExit(main())
