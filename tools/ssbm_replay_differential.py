#!/usr/bin/env python3
"""Run bounded public Slippi prefixes through a production CSV trace runner.

The worker never resumes an arbitrary post-frame. It finds naturally reached,
stationary Wait anchors with neutral input history, feeds subsequent recorded
pre-frame inputs through production, and compares finalized source post-frames.
The source disc, UCF revision, setup, and exact raw main-stick bytes are
fail-closed prerequisites.  Once those are proven, the same processed/raw pair
is sent through the production 12-field input contract so UCF boundaries are
compared instead of suppressed as external modifier behavior.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable
import urllib.request

from ssbm_collision import binary32


ROOT = Path(__file__).resolve().parent.parent
EXTRACTOR = ROOT / "tools" / "ssbm_slippi_extract.mjs"

PHYSICAL_Z = 0x0010
PHYSICAL_R = 0x0020
PHYSICAL_L = 0x0040
PHYSICAL_A = 0x0100
PHYSICAL_B = 0x0200
PHYSICAL_X = 0x0400
PHYSICAL_Y = 0x0800
PHYSICAL_START = 0x1000
PHYSICAL_DPAD = 0x000F

PF_JUMP = 1 << 0
PF_ATTACK = 1 << 1
PF_SPECIAL = 1 << 3
PF_TAUNT = 1 << 4

# Common action IDs used only to recognize the external UCF patch. They do not
# define a character's supported action map; that stays in the profile.
SSBM_TURN = 18
SSBM_DASH = 20
UCF_RAW_DELTA_THRESHOLD = 75
PF_RAW_MAIN_AXIS_VALID_MASK = 0x03

# A replay may have a complete, physically serialized raw input pair and the
# recorded UCF family while still lacking an independently pinned disc/modifier
# declaration.  Such a file is useful for divergence discovery, but it must
# never silently become an equivalence result.  The diagnostic execution path
# below permits only these two *unknown* provenance failures; explicit
# mismatches, malformed framing, and missing raw axes remain fail-closed.
DIAGNOSTIC_REFERENCE_FAILURES = frozenset(
    {"disc-identity-unproven", "ucf-revision-unproven"}
)


class ConfigurationError(RuntimeError):
    """Raised when a manifest, profile, dependency, or runner is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfigurationError(f"{path}: root must be an object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "ssbm-replay-corpus-v1":
        raise ConfigurationError("unsupported replay corpus schema")
    parser = manifest.get("parser")
    entries = manifest.get("entries")
    if not isinstance(parser, dict) or not isinstance(entries, list) or not entries:
        raise ConfigurationError("manifest requires parser and non-empty entries")
    if parser.get("package") != "@slippi/slippi-js":
        raise ConfigurationError("only the audited slippi-js parser is supported")
    if not all(
        isinstance(parser.get(field), str) and parser[field]
        for field in ("version", "license", "audited_upstream_commit")
    ):
        raise ConfigurationError(
            "parser requires version, license, and audited_upstream_commit"
        )
    names: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigurationError(f"manifest entry {index} must be an object")
        required = {"local_name", "url", "size", "sha256", "license", "revision"}
        missing = sorted(required - entry.keys())
        if missing:
            raise ConfigurationError(
                f"manifest entry {index} missing {', '.join(missing)}"
            )
        name = str(entry["local_name"])
        if Path(name).name != name or not name.endswith(".slp"):
            raise ConfigurationError(f"unsafe replay local_name: {name!r}")
        if name in names:
            raise ConfigurationError(f"duplicate replay local_name: {name}")
        names.add(name)
        expected_hash = str(entry["sha256"])
        if len(expected_hash) != 64 or any(
            char not in "0123456789abcdef" for char in expected_hash
        ):
            raise ConfigurationError(f"invalid SHA-256 for {name}")
        source_reference = entry.get("source_reference")
        if source_reference is not None:
            validate_source_reference(
                source_reference, f"manifest entry {name} source_reference"
            )


def validate_source_reference(reference: Any, context: str) -> None:
    if not isinstance(reference, dict):
        raise ConfigurationError(f"{context} must be an object")
    disc = reference.get("disc")
    modifier = reference.get("modifier")
    if not isinstance(disc, dict) or not isinstance(modifier, dict):
        raise ConfigurationError(f"{context} requires disc and modifier")
    if (
        not isinstance(disc.get("game_id"), str)
        or not isinstance(disc.get("revision"), int)
        or not isinstance(disc.get("sha256"), str)
        or len(disc["sha256"]) != 64
    ):
        raise ConfigurationError(f"{context} has invalid disc identity")
    if (
        not isinstance(modifier.get("name"), str)
        or not isinstance(modifier.get("revision"), str)
        or not isinstance(modifier.get("official_release_tag"), str)
        or not isinstance(modifier.get("official_release_revision"), str)
        or len(modifier["official_release_revision"]) != 40
    ):
        raise ConfigurationError(f"{context} has invalid modifier identity")


def validate_profile(profile: dict[str, Any]) -> None:
    if profile.get("schema") != "ssbm-replay-differential-profile-v1":
        raise ConfigurationError("unsupported replay differential profile schema")
    required = {
        "source_character_id",
        "source_wait_action_id",
        "source_main_floor_ground_ids",
        "supported_stage_ids",
        "source_to_target_x_scale",
        "source_to_target_y_scale",
        "anchor",
        "qualification",
        "comparison",
        "source_actions",
        "reference_target",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ConfigurationError(f"profile missing {', '.join(missing)}")
    actions = profile["source_actions"]
    validate_source_reference(profile["reference_target"], "profile reference_target")
    if (
        not isinstance(actions, dict)
        or str(profile["source_wait_action_id"]) not in actions
    ):
        raise ConfigurationError("profile source_actions must contain Wait")
    for source_id, action in actions.items():
        try:
            int(source_id)
        except ValueError as error:
            raise ConfigurationError(
                f"invalid source action id {source_id!r}"
            ) from error
        if not isinstance(action, dict) or not {
            "name",
            "target_action",
        }.issubset(action):
            raise ConfigurationError(f"incomplete action mapping {source_id}")


def package_version(prefix: Path) -> str | None:
    package_json = (
        prefix / "node_modules" / "@slippi" / "slippi-js" / "package.json"
    )
    if not package_json.is_file():
        return None
    return str(load_json(package_json).get("version"))


def install_parser(prefix: Path, version: str) -> None:
    if package_version(prefix) == version:
        return
    npm = shutil.which("npm")
    if npm is None:
        raise ConfigurationError("npm is required to install pinned slippi-js")
    prefix.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            npm,
            "install",
            "--prefix",
            str(prefix),
            f"@slippi/slippi-js@{version}",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--save-exact",
        ],
        check=True,
    )
    actual = package_version(prefix)
    if actual != version:
        raise ConfigurationError(
            f"slippi-js version mismatch expected={version} actual={actual}"
        )


def verify_replay(path: Path, entry: dict[str, Any]) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    actual_size = path.stat().st_size
    if actual_size != int(entry["size"]):
        return False, f"size:{actual_size}"
    actual_hash = sha256(path)
    if actual_hash != entry["sha256"]:
        return False, f"sha256:{actual_hash}"
    return True, actual_hash


def download_replay(
    destination: Path,
    entry: dict[str, Any],
    attempts: int = 6,
) -> None:
    valid, _ = verify_replay(destination, entry)
    if valid:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        temporary_path: Path | None = None
        try:
            request = urllib.request.Request(
                str(entry["url"]),
                headers={"User-Agent": "pf-ssbm-replay-differential/1"},
            )
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".part",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                with urllib.request.urlopen(request, timeout=60) as response:
                    shutil.copyfileobj(response, temporary)
            valid, evidence = verify_replay(temporary_path, entry)
            if not valid:
                temporary_path.unlink(missing_ok=True)
                raise ConfigurationError(
                    f"download provenance mismatch for {destination.name}: {evidence}"
                )
            temporary_path.replace(destination)
            return
        except Exception as error:  # network failures are retried with context
            last_error = error
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(min(attempt, 3))
    raise ConfigurationError(
        f"failed to download {destination.name} after {attempts} attempts: "
        f"{last_error}"
    )


def bootstrap(manifest_path: Path, work_dir: Path) -> int:
    manifest = load_json(manifest_path)
    validate_manifest(manifest)
    parser_version = str(manifest["parser"]["version"])
    install_parser(work_dir, parser_version)
    corpus_dir = work_dir / "corpus"
    for entry in manifest["entries"]:
        destination = corpus_dir / str(entry["local_name"])
        download_replay(destination, entry)
        print(
            "ssbm-replay-bootstrap=verified "
            f"file={destination.name} size={destination.stat().st_size} "
            f"sha256={entry['sha256']}"
        )
    return 0


def extract_replay(path: Path, parser_prefix: Path) -> dict[str, Any]:
    if package_version(parser_prefix) is None:
        raise ConfigurationError(
            f"slippi-js is not installed under {parser_prefix}; run bootstrap"
        )
    node = shutil.which("node")
    if node is None:
        raise ConfigurationError("node is required to run pinned slippi-js")
    result = subprocess.run(
        [node, str(EXTRACTOR), str(path), str(parser_prefix)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit-code={result.returncode}"
        raise ConfigurationError(f"Slippi extraction failed for {path.name}: {detail}")
    try:
        extracted = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            f"Slippi extractor emitted invalid JSON for {path.name}: {error}"
        ) from error
    if not isinstance(extracted, dict):
        raise ConfigurationError(f"Slippi extractor root is not an object: {path.name}")
    return extracted


def extract_replay_timed(
    path: Path, parser_prefix: Path
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    replay = extract_replay(path, parser_prefix)
    return replay, time.perf_counter() - started


def frame_map(replay: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(frame["frame"]): frame for frame in replay["frames"]}


def player(frame: dict[str, Any], player_index: int) -> dict[str, Any] | None:
    players = frame["players"]
    return players[player_index] if player_index < len(players) else None


def near(left: float, right: float, tolerance: float = 1e-6) -> bool:
    return abs(left - right) <= tolerance


def neutral_input(pre: dict[str, Any]) -> bool:
    # Physical trigger sensor noise is allowed only while the processed Melee
    # trigger is zero. The raw values are still replayed into production.
    return (
        abs(float(pre["joystickX"])) <= 0.025
        and abs(float(pre["joystickY"])) <= 0.025
        and abs(float(pre["cStickX"])) <= 0.025
        and abs(float(pre["cStickY"])) <= 0.025
        and int(pre["physicalButtons"]) == 0
        and float(pre["trigger"]) == 0.0
    )


def source_player_settings(
    replay: dict[str, Any], player_index: int
) -> dict[str, Any]:
    return next(
        entry
        for entry in replay["settings"]["players"]
        if int(entry["playerIndex"]) == player_index
    )


def reference_qualification(
    replay: dict[str, Any],
    entry: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Prove the replay is the exact configured disc/UCF/input source.

    Historical SLP setup records identify a broad controller-fix family only.
    An entry therefore needs independent, reviewable source provenance before
    it can satisfy the exact disc and modifier revision.  Raw-axis availability
    is taken only from the physical pre-frame payload, never reconstructed from
    normalized floats.
    """

    target = profile["reference_target"]
    declared = entry.get("source_reference")
    failures: list[str] = []
    if not isinstance(declared, dict):
        failures.extend(("disc-identity-unproven", "ucf-revision-unproven"))
    else:
        if declared.get("disc") != target.get("disc"):
            failures.append("disc-identity-mismatch")
        if declared.get("modifier") != target.get("modifier"):
            failures.append("ucf-revision-mismatch")

    settings = replay.get("settings")
    players = settings.get("players", []) if isinstance(settings, dict) else []
    target_players = [
        value
        for value in players
        if isinstance(value, dict)
        and isinstance(value.get("characterId"), int)
        and not isinstance(value.get("characterId"), bool)
        and value["characterId"] == int(profile["source_character_id"])
    ]
    observed_fixes = sorted(
        {str(value.get("controllerFix")) for value in target_players}
    )
    expected_fix = str(target["modifier"]["name"])
    if not target_players or any(
        value.get("controllerFix") != expected_fix for value in target_players
    ):
        failures.append("controller-fix-mismatch-or-missing")

    input_provenance = replay.get("inputProvenance")
    if not isinstance(input_provenance, dict):
        failures.append("raw-main-provenance-missing")
    else:
        payload_bytes = input_provenance.get("preFramePayloadBytes")
        exact_raw_x = input_provenance.get("exactRawMainX") is True
        exact_raw_y = input_provenance.get("exactRawMainY") is True
        if input_provenance.get("framing") != "slp-message-sizes-v1":
            failures.append("raw-main-framing-unknown")
        if (
            input_provenance.get("rawMainXOffset") != 0x3B
            or input_provenance.get("rawMainYOffset") != 0x40
            or not isinstance(payload_bytes, int)
            or (exact_raw_x and payload_bytes < 0x3B)
            or (exact_raw_y and payload_bytes < 0x40)
        ):
            failures.append("raw-main-layout-unproven")
        if not exact_raw_x:
            failures.append("raw-main-x-unavailable")
        if not exact_raw_y:
            failures.append("raw-main-y-unavailable")

    return {
        "status": (
            "exact" if not failures else "unsupported-reference-configuration"
        ),
        "target": target,
        "declared": declared,
        "observed_controller_fixes": observed_fixes,
        "input_provenance": input_provenance,
        "failures": failures,
    }


def diagnostic_execution_reference(
    reference: dict[str, Any], allow_unverified: bool
) -> dict[str, Any] | None:
    """Return an execution-only reference view for bounded discovery.

    Exact runs use the original reference result.  Diagnostic runs may
    execute only when the replay has no explicit provenance mismatch and all
    raw-input/layout checks passed; the returned copy marks the runner-side
    view as exact solely so the existing 12-field raw-input contract is
    required.  The caller retains the original qualification in its report.
    """

    if reference.get("status") == "exact":
        return reference
    if not allow_unverified:
        return None
    failures = reference.get("failures")
    if not isinstance(failures, list):
        return None
    if set(str(value) for value in failures) - DIAGNOSTIC_REFERENCE_FAILURES:
        return None
    return {
        **reference,
        "status": "exact",
        "execution_authority": "diagnostic-unverified-reference",
    }


def exact_raw_main(pre: dict[str, Any], mirror: int = 1) -> tuple[int, int] | None:
    raw_x = pre.get("rawJoystickX")
    raw_y = pre.get("rawJoystickY")
    if (
        isinstance(raw_x, bool)
        or not isinstance(raw_x, int)
        or isinstance(raw_y, bool)
        or not isinstance(raw_y, int)
        or not -128 <= raw_x <= 127
        or not -128 <= raw_y <= 127
    ):
        return None
    if mirror not in (-1, 1):
        raise ConfigurationError("input mirror must be -1 or +1")
    mirrored_x = raw_x * mirror
    if not -128 <= mirrored_x <= 127:
        # Signed PADStatus has no positive representation for mirrored -128.
        return None
    return mirrored_x, raw_y


def detect_ucf_dashback(
    replay: dict[str, Any],
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
) -> dict[str, Any] | None:
    """Return the audited UCF raw-history dashback signature, if present.

    The audited UCF 0.8 and 0.84 dashback injections consume a raw X delta
    between current and two-frames-old PADStatus samples.  Detection is only a
    diagnostic; source-reference and raw-pair qualification decide whether the
    boundary may be compared.
    """

    settings = source_player_settings(replay, player_index)
    if settings.get("controllerFix") != "UCF":
        return None
    current_frame = frames.get(frame_number)
    previous_frame = frames.get(frame_number - 1)
    two_back_frame = frames.get(frame_number - 2)
    if current_frame is None or previous_frame is None or two_back_frame is None:
        return None
    current = player(current_frame, player_index)
    previous = player(previous_frame, player_index)
    two_back = player(two_back_frame, player_index)
    if current is None or previous is None or two_back is None:
        return None
    current_pre = current["pre"]
    current_post = current["post"]
    previous_pre = previous["pre"]
    previous_post = previous["post"]
    current_raw_x = current_pre.get("rawJoystickX")
    two_back_raw_x = two_back["pre"].get("rawJoystickX")
    if (
        isinstance(current_raw_x, bool)
        or not isinstance(current_raw_x, int)
        or isinstance(two_back_raw_x, bool)
        or not isinstance(two_back_raw_x, int)
    ):
        return None
    raw_delta = current_raw_x - two_back_raw_x
    matches = (
        int(previous_post["actionStateId"]) == SSBM_TURN
        and float(previous_post["actionStateCounter"]) == 1.0
        and int(current_post["actionStateId"]) == SSBM_DASH
        and abs(float(previous_pre["joystickX"])) < 0.8
        and abs(float(current_pre["joystickX"])) >= 0.8
        and abs(raw_delta) > UCF_RAW_DELTA_THRESHOLD
    )
    if not matches:
        return None
    return {
        "classification": "ucf-raw-history-dashback",
        "source_frame": frame_number,
        "controller_fix": "UCF",
        "source_action_transition": [SSBM_TURN, SSBM_DASH],
        "processed_x": float(current_pre["joystickX"]),
        "previous_processed_x": float(previous_pre["joystickX"]),
        "current_raw_x": current_raw_x,
        "two_frames_back_raw_x": two_back_raw_x,
        "raw_delta": raw_delta,
        "audited_ucf_raw_delta_threshold": UCF_RAW_DELTA_THRESHOLD,
    }


def detect_ucf084_cardinal_mismatch(
    replay: dict[str, Any],
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
) -> dict[str, Any] | None:
    """Detect a recorded processed stick that contradicts UCF 0.84.

    The pinned Pad Buffer + 1.0 Cardinals hook snaps a main-stick primary raw
    axis at magnitude 80 or greater to exactly +/-1 when the orthogonal raw
    axis is at most 6, and clears the orthogonal processed axis.  Public SLPs
    normally identify only the broad ``UCF`` family.  A raw-complete sample
    that still records the unsnapped processed pair therefore proves that the
    replay is not an exact observation of our pinned UCF 0.84 target.
    """

    settings = source_player_settings(replay, player_index)
    if settings.get("controllerFix") != "UCF":
        return None
    source_frame = frames.get(frame_number)
    sample = None if source_frame is None else player(source_frame, player_index)
    if sample is None:
        return None
    pre = sample["pre"]
    raw = exact_raw_main(pre)
    if raw is None:
        return None
    raw_x, raw_y = raw
    processed_x_value = pre.get("joystickX")
    processed_y_value = pre.get("joystickY")
    if not isinstance(processed_x_value, (int, float)) or not isinstance(
        processed_y_value, (int, float)
    ):
        return None
    processed_x = float(processed_x_value)
    processed_y = float(processed_y_value)
    expected_x = processed_x
    expected_y = processed_y
    snapped_axis: str | None = None
    if abs(raw_x) >= 80 and abs(raw_y) <= 6:
        expected_x = -1.0 if raw_x < 0 else 1.0
        expected_y = 0.0
        snapped_axis = "x"
    elif abs(raw_y) >= 80 and abs(raw_x) <= 6:
        expected_x = 0.0
        expected_y = -1.0 if raw_y < 0 else 1.0
        snapped_axis = "y"
    if snapped_axis is None or (
        abs(processed_x - expected_x) <= 1e-6
        and abs(processed_y - expected_y) <= 1e-6
    ):
        return None
    return {
        "classification": "ucf084-cardinal-signature-mismatch",
        "source_frame": frame_number,
        "controller_fix": "UCF",
        "snapped_axis": snapped_axis,
        "raw_main": [raw_x, raw_y],
        "recorded_processed_main": [processed_x, processed_y],
        "ucf084_processed_main": [expected_x, expected_y],
        "reason": (
            "serialized raw/processed main-stick pair contradicts the pinned "
            "UCF 0.84 1.0-cardinal hook"
        ),
    }


def classify_source_modifier(
    replay: dict[str, Any],
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fail closed only when a detected UCF boundary lacks exact authority."""

    cardinal_mismatch = detect_ucf084_cardinal_mismatch(
        replay, frames, frame_number, player_index
    )
    if cardinal_mismatch is not None:
        return cardinal_mismatch
    signature = detect_ucf_dashback(replay, frames, frame_number, player_index)
    if signature is None:
        return None
    if reference is None or reference.get("status") != "exact":
        return {
            **signature,
            "classification": "unsupported-ucf-reference-configuration",
            "reference_failures": (
                [] if reference is None else list(reference.get("failures", []))
            ),
            "reason": (
                "UCF dashback signature is present, but exact disc/UCF "
                "provenance has not been established"
            ),
        }
    required_frames = (frame_number - 2, frame_number - 1, frame_number)
    unavailable = []
    for required_frame in required_frames:
        source_frame = frames.get(required_frame)
        sample = (
            None
            if source_frame is None
            else player(source_frame, player_index)
        )
        if sample is None or exact_raw_main(sample["pre"]) is None:
            unavailable.append(required_frame)
    if unavailable:
        return {
            **signature,
            "classification": "unsupported-ucf-raw-main-unavailable",
            "missing_source_frames": unavailable,
            "reason": (
                "UCF dashback signature requires exact serialized raw main "
                "X/Y pairs for the production mask=3 input contract"
            ),
        }
    return None


def first_semantic_difference(
    expected_rows: Iterable[dict[str, Any]],
    actual_rows: Iterable[dict[str, Any]],
    compare: Callable[[dict[str, Any], dict[str, Any]], list[str]],
) -> tuple[int, list[str]] | None:
    """Return the earliest mismatching index, which is the minimal prefix."""

    expected = list(expected_rows)
    actual = list(actual_rows)
    if len(expected) != len(actual):
        raise ValueError("expected and actual row counts differ")
    for index, (expected_row, actual_row) in enumerate(
        zip(expected, actual, strict=True)
    ):
        differences = compare(expected_row, actual_row)
        if differences:
            return index, differences
    return None


def input_axis(value: float) -> int:
    return max(-32768, min(32767, round(value * 32767.0)))


def input_trigger(value: float) -> int:
    # Melee exposes the analog trigger travel and the final digital L/R click
    # independently. The production input contract reserves UINT16_MAX for
    # that click, so a physically unclicked analog endpoint must not consume
    # the digital edge one frame early.
    return max(0, min(65534, round(value * 65535.0)))


def logical_buttons(pre: dict[str, Any]) -> int:
    physical = int(pre["physicalButtons"])
    buttons = 0
    if physical & (PHYSICAL_X | PHYSICAL_Y):
        buttons |= PF_JUMP
    if physical & (PHYSICAL_A | PHYSICAL_Z):
        buttons |= PF_ATTACK
    if physical & PHYSICAL_B:
        buttons |= PF_SPECIAL
    if physical & (PHYSICAL_START | PHYSICAL_DPAD):
        buttons |= PF_TAUNT
    return buttons


def exact_raw_c(pre: dict[str, Any], mirror: int = 1) -> tuple[int, int] | None:
    raw_x = pre.get("rawCStickX")
    raw_y = pre.get("rawCStickY")
    if (
        isinstance(raw_x, bool)
        or not isinstance(raw_x, int)
        or isinstance(raw_y, bool)
        or not isinstance(raw_y, int)
        or not -128 <= raw_x <= 127
        or not -128 <= raw_y <= 127
    ):
        return None
    if mirror not in (-1, 1):
        raise ConfigurationError("input mirror must be -1 or +1")
    mirrored_x = raw_x * mirror
    if not -128 <= mirrored_x <= 127:
        return None
    return mirrored_x, raw_y


def native_input(
    pre: dict[str, Any], mirror: int, require_exact_raw_main: bool = False
) -> str:
    physical = int(pre["physicalButtons"])
    buttons = logical_buttons(pre)
    c_x = float(pre["cStickX"])
    c_y = float(pre["cStickY"])
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
    values = [
        input_axis(float(pre["joystickX"]) * mirror),
        input_axis(-float(pre["joystickY"])),
        input_axis(c_x * mirror),
        input_axis(-c_y),
        left,
        right,
        buttons,
        0,
        0,
    ]
    raw_main = exact_raw_main(pre, mirror)
    if raw_main is not None:
        values.extend((*raw_main, PF_RAW_MAIN_AXIS_VALID_MASK))
    elif require_exact_raw_main:
        raise ConfigurationError(
            "exact serialized raw main X/Y pair is required for UCF input"
        )
    return ",".join(str(value) for value in values)


def scale_f32(value: float, scale: dict[str, Any]) -> float:
    sign = -1.0 if bool(scale.get("invert", False)) else 1.0
    return binary32(
        value
        * sign
        * int(scale["numerator"])
        / int(scale["denominator"])
    )


def stable_wait_anchor(
    replay: dict[str, Any],
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
    opponent_index: int,
    profile: dict[str, Any],
) -> bool:
    history = int(profile["anchor"]["neutral_history_frames"])
    current_frame = frames.get(frame_number)
    next_frame = frames.get(frame_number + 1)
    if current_frame is None or next_frame is None:
        return False
    current = player(current_frame, player_index)
    following = player(next_frame, player_index)
    opponent = player(current_frame, opponent_index)
    if current is None or following is None or opponent is None:
        return False
    post = current["post"]
    main_floor = {int(value) for value in profile["source_main_floor_ground_ids"]}
    if (
        int(post["actionStateId"]) != int(profile["source_wait_action_id"])
        or bool(post["isAirborne"])
        or int(post["lastGroundId"]) not in main_floor
        or neutral_input(following["pre"])
        or abs(float(post["positionX"]))
        >= float(profile["anchor"]["maximum_abs_source_x"])
        or abs(float(opponent["post"]["positionX"]) - float(post["positionX"]))
        < float(profile["anchor"]["minimum_opponent_x_distance"])
    ):
        return False
    reference_x = float(post["positionX"])
    reference_y = float(post["positionY"])
    reference_percent = float(post["percent"])
    reference_stocks = int(post["stocksRemaining"])
    for history_frame in range(frame_number - history + 1, frame_number + 1):
        sample_frame = frames.get(history_frame)
        if sample_frame is None:
            return False
        sample = player(sample_frame, player_index)
        sample_opponent = player(sample_frame, opponent_index)
        if sample is None or sample_opponent is None:
            return False
        sample_post = sample["post"]
        if (
            int(sample_post["actionStateId"])
            != int(profile["source_wait_action_id"])
            or bool(sample_post["isAirborne"])
            or int(sample_post["lastGroundId"]) not in main_floor
            or not neutral_input(sample["pre"])
            or not near(float(sample_post["positionX"]), reference_x)
            or not near(float(sample_post["positionY"]), reference_y)
            or not near(float(sample_post["percent"]), reference_percent)
            or int(sample_post["stocksRemaining"]) != reference_stocks
            or abs(
                float(sample_opponent["post"]["positionX"])
                - float(sample_post["positionX"])
            )
            < float(profile["anchor"]["minimum_opponent_x_distance"])
        ):
            return False
    return True


def find_anchors(
    replay: dict[str, Any], profile: dict[str, Any]
) -> list[tuple[int, int, int]]:
    settings_players = replay["settings"].get("players", [])
    if len(settings_players) != 2:
        return []
    indices = [int(entry["playerIndex"]) for entry in settings_players]
    target_indices = {
        int(entry["playerIndex"])
        for entry in settings_players
        if int(entry["characterId"]) == int(profile["source_character_id"])
    }
    frames = frame_map(replay)
    anchors: list[tuple[int, int, int]] = []
    ordered_pairs = (
        (indices[0], indices[1]),
        (indices[1], indices[0]),
    )
    for player_index, opponent_index in ordered_pairs:
        if player_index not in target_indices:
            continue
        for frame_number in sorted(frames):
            if stable_wait_anchor(
                replay,
                frames,
                frame_number,
                player_index,
                opponent_index,
                profile,
            ):
                anchors.append((frame_number, player_index, opponent_index))
    return anchors


def expected_target_action(
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
    profile: dict[str, Any],
) -> tuple[str, int]:
    sample = player(frames[frame_number], player_index)
    if sample is None:
        raise ConfigurationError(
            f"missing source player {player_index} at frame {frame_number}"
        )
    source_id = int(sample["post"]["actionStateId"])
    mapping = profile["source_actions"].get(str(source_id))
    if mapping is None:
        raise ConfigurationError(f"unmapped source action {source_id}")
    target_action = int(mapping["target_action"])
    l_cancel_target = mapping.get("l_cancel_target_action")
    if l_cancel_target is not None:
        # Slippi exposes lCancelStatus only on the landing transition. Carry
        # that route over the contiguous landing action without inventing a
        # target-side state transition.
        scan = frame_number
        while True:
            history_frame = frames.get(scan)
            history_player = (
                None
                if history_frame is None
                else player(history_frame, player_index)
            )
            if history_player is None:
                break
            history_post = history_player["post"]
            if int(history_post["actionStateId"]) != source_id:
                break
            if int(history_post.get("lCancelStatus") or 0) == 1:
                target_action = int(l_cancel_target)
                break
            scan -= 1
    return str(mapping["name"]), target_action


def validate_setup(
    replay: dict[str, Any], profile: dict[str, Any]
) -> tuple[list[str], list[str]]:
    settings = replay.get("settings")
    if not isinstance(settings, dict):
        return ["missing-settings"], []
    unsupported: list[str] = []
    limitations = [
        "natural-Wait-anchor-is-not-arbitrary-state-resumption",
    ]
    if settings.get("isPAL") is True:
        unsupported.append("PAL")
    elif settings.get("isPAL") is not False:
        unsupported.append("pal-status:unknown")
    stage_id = settings.get("stageId")
    if isinstance(stage_id, bool) or not isinstance(stage_id, int):
        unsupported.append("stage:unknown")
    elif stage_id not in {int(value) for value in profile["supported_stage_ids"]}:
        unsupported.append(f"stage:{stage_id}")
    if settings.get("isTeams") is True:
        unsupported.append("teams")
    elif settings.get("isTeams") is not False:
        unsupported.append("teams-status:unknown")
    raw_players = settings.get("players", [])
    players = raw_players if isinstance(raw_players, list) else []
    valid_players = [
        entry
        for entry in players
        if isinstance(entry, dict)
        and isinstance(entry.get("playerIndex"), int)
        and not isinstance(entry.get("playerIndex"), bool)
        and isinstance(entry.get("characterId"), int)
        and not isinstance(entry.get("characterId"), bool)
    ]
    if not isinstance(raw_players, list) or len(players) != 2:
        player_count = len(players) if isinstance(raw_players, list) else "invalid"
        unsupported.append(f"player-count:{player_count}")
    elif len(valid_players) != len(players):
        unsupported.append("player-settings:malformed")
    elif not any(
        entry["characterId"] == int(profile["source_character_id"])
        for entry in valid_players
    ):
        unsupported.append("missing-profile-character")
    controller_fixes = {
        entry.get("controllerFix")
        for entry in players
        if isinstance(entry, dict) and entry.get("controllerFix") is not None
    }
    if controller_fixes:
        limitations.append(
            "source-controller-modifiers-present:"
            + ",".join(sorted(str(value) for value in controller_fixes))
        )

    # Old Slippi formats do not serialize self-induced velocities, hitlag, or
    # animation index. The worker reports that coverage reduction explicitly.
    target_indices = {
        entry["playerIndex"]
        for entry in valid_players
        if entry["characterId"] == int(profile["source_character_id"])
    }
    first_target: dict[str, Any] | None = None
    for source_frame in replay.get("frames", []):
        for player_index in target_indices:
            first_target = player(source_frame, player_index)
            if first_target is not None:
                break
        if first_target is not None:
            break
    if first_target is not None:
        post = first_target["post"]
        unavailable = [
            field
            for field in (
                "selfAirX",
                "selfGroundX",
                "selfY",
                "hitlagRemaining",
                "animationIndex",
            )
            if post.get(field) is None
        ]
        if unavailable:
            limitations.append(
                "source-post-frame-fields-unavailable:" + ",".join(unavailable)
            )
    return unsupported, limitations


def qualify_segment(
    replay: dict[str, Any],
    frames: dict[int, dict[str, Any]],
    anchor_frame: int,
    player_index: int,
    opponent_index: int,
    profile: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    anchor = player(frames[anchor_frame], player_index)
    if anchor is None:
        raise ConfigurationError("anchor player frame disappeared")
    base_percent = float(anchor["post"]["percent"])
    base_stocks = int(anchor["post"]["stocksRemaining"])
    maximum = int(profile["qualification"]["maximum_prefix_frames"])
    main_floor = {int(value) for value in profile["source_main_floor_ground_ids"]}
    last_supported = anchor_frame
    stop_reason = "maximum-prefix"
    modifier_boundary: dict[str, Any] | None = None
    exercised_ucf_boundaries: list[dict[str, Any]] = []
    for frame_number in range(anchor_frame + 1, anchor_frame + maximum + 1):
        source_frame = frames.get(frame_number)
        if source_frame is None:
            stop_reason = "end-of-replay"
            break
        sample = player(source_frame, player_index)
        opponent = player(source_frame, opponent_index)
        if sample is None or opponent is None:
            stop_reason = "missing-player-frame"
            break
        modifier_boundary = classify_source_modifier(
            replay, frames, frame_number, player_index, reference
        )
        if modifier_boundary is not None:
            stop_reason = f"source-modifier:{modifier_boundary['classification']}"
            break
        ucf_boundary = detect_ucf_dashback(
            replay, frames, frame_number, player_index
        )
        if ucf_boundary is not None:
            exercised_ucf_boundaries.append(ucf_boundary)
        post = sample["post"]
        source_action_id = int(post["actionStateId"])
        if str(source_action_id) not in profile["source_actions"]:
            stop_reason = f"unmapped-action:{source_action_id}"
            break
        if not near(float(post["percent"]), base_percent):
            stop_reason = "damage-changed"
            break
        if int(post["stocksRemaining"]) != base_stocks:
            stop_reason = "stock-changed"
            break
        if abs(float(post["positionX"])) >= float(
            profile["qualification"]["maximum_abs_source_x"]
        ):
            stop_reason = "stage-edge-envelope"
            break
        opponent_post = opponent["post"]
        if (
            abs(float(opponent_post["positionX"]) - float(post["positionX"]))
            < float(profile["qualification"]["minimum_opponent_x_distance"])
            and abs(
                float(opponent_post["positionY"]) - float(post["positionY"])
            )
            < float(profile["qualification"]["minimum_opponent_y_distance"])
        ):
            stop_reason = "opponent-proximity-envelope"
            break
        if not bool(post["isAirborne"]) and int(post["lastGroundId"]) not in main_floor:
            stop_reason = f"unsupported-support:{post['lastGroundId']}"
            break
        last_supported = frame_number
    return {
        "last_supported_frame": last_supported,
        "stop_reason": stop_reason,
        "modifier_boundary": modifier_boundary,
        "exercised_ucf_boundaries": exercised_ucf_boundaries,
    }


def run_native(
    runner: Path, input_lines: list[str]
) -> tuple[list[dict[str, str]], float]:
    started = time.perf_counter()
    result = subprocess.run(
        [str(runner)],
        input=("\n".join(input_lines) + "\n") if input_lines else "",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit-code={result.returncode}"
        raise ConfigurationError(f"native runner failed: {detail}")
    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    if len(rows) != len(input_lines):
        raise ConfigurationError(
            f"native row count {len(rows)} != input count {len(input_lines)}"
        )
    return rows, elapsed


def source_velocity(
    post: dict[str, Any], grounded: bool
) -> tuple[float | None, float | None]:
    velocity_x = post.get("selfGroundX") if grounded else post.get("selfAirX")
    velocity_y = post.get("selfY")
    if velocity_x is not None:
        velocity_x = float(velocity_x) + float(post.get("selfAttackX") or 0.0)
    if velocity_y is not None:
        velocity_y = float(velocity_y) + float(post.get("selfAttackY") or 0.0)
    return velocity_x, velocity_y


def expected_row(
    frames: dict[int, dict[str, Any]],
    frame_number: int,
    player_index: int,
    anchor_x: float,
    anchor_y: float,
    mirror: int,
    input_line: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    sample = player(frames[frame_number], player_index)
    if sample is None:
        raise ConfigurationError("missing expected player frame")
    post = sample["post"]
    grounded = not bool(post["isAirborne"])
    action_name, target_action = expected_target_action(
        frames, frame_number, player_index, profile
    )
    velocity_x, velocity_y = source_velocity(post, grounded)
    return {
        "source_frame": frame_number,
        "source_action_id": int(post["actionStateId"]),
        "source_action": action_name,
        "source_action_counter": float(post["actionStateCounter"]),
        "input": input_line,
        "action_state": target_action,
        "facing": int(post["facingDirection"]) * mirror,
        "grounded": int(grounded),
        "position_x_f32_from_origin": scale_f32(
            (float(post["positionX"]) - anchor_x) * mirror,
            profile["source_to_target_x_scale"],
        ),
        "position_y_f32_from_origin": scale_f32(
            float(post["positionY"]) - anchor_y,
            profile["source_to_target_y_scale"],
        ),
        "velocity_x_f32": (
            None
            if velocity_x is None
            else scale_f32(
                velocity_x * mirror, profile["source_to_target_x_scale"]
            )
        ),
        "velocity_y_f32": (
            None
            if velocity_y is None
            else scale_f32(velocity_y, profile["source_to_target_y_scale"])
        ),
    }


def actual_row(row: dict[str, str]) -> dict[str, int | float]:
    integer_fields = (
        "tick",
        "action_state",
        "action_ticks",
        "facing",
        "grounded",
    )
    float_fields = (
        "position_x_f32_from_origin",
        "position_y_f32_from_origin",
        "velocity_x_f32",
        "velocity_y_f32",
    )
    try:
        return {
            **{field: int(row[field]) for field in integer_fields},
            **{field: float(row[field]) for field in float_fields},
        }
    except (KeyError, ValueError) as error:
        raise ConfigurationError(f"native CSV field error: {error}") from error


def compare_rows(
    expected: dict[str, Any],
    actual: dict[str, Any],
    profile: dict[str, Any],
) -> list[str]:
    differences: list[str] = []
    for field in ("action_state", "facing", "grounded"):
        if int(actual[field]) != int(expected[field]):
            differences.append(
                f"{field} expected={expected[field]} actual={actual[field]}"
            )
    position_tolerance = float(profile["comparison"]["position_tolerance_f32"])
    velocity_tolerance = float(profile["comparison"]["velocity_tolerance_f32"])
    for field in (
        "position_x_f32_from_origin",
        "position_y_f32_from_origin",
    ):
        delta = float(actual[field]) - float(expected[field])
        if abs(delta) > position_tolerance:
            differences.append(
                f"{field} expected={expected[field]} actual={actual[field]} "
                f"delta={delta} tolerance={position_tolerance}"
            )
    for field in ("velocity_x_f32", "velocity_y_f32"):
        if expected[field] is None:
            continue
        delta = float(actual[field]) - float(expected[field])
        if abs(delta) > velocity_tolerance:
            differences.append(
                f"{field} expected={expected[field]} actual={actual[field]} "
                f"delta={delta} tolerance={velocity_tolerance}"
            )
    return differences


def comparison_trail(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    end_index: int,
) -> list[dict[str, Any]]:
    start = max(0, end_index - 7)
    return [
        {
            "source_frame": expected[index]["source_frame"],
            "source_action": expected[index]["source_action"],
            "source_action_counter": expected[index]["source_action_counter"],
            "target_action": actual[index]["action_state"],
            "target_action_ticks": actual[index]["action_ticks"],
            "source_x_f32": expected[index]["position_x_f32_from_origin"],
            "target_x_f32": actual[index]["position_x_f32_from_origin"],
            "source_y_f32": expected[index]["position_y_f32_from_origin"],
            "target_y_f32": actual[index]["position_y_f32_from_origin"],
        }
        for index in range(start, end_index + 1)
    ]


def compare_segment(
    replay_path: Path,
    replay: dict[str, Any],
    runner: Path,
    anchor_frame: int,
    player_index: int,
    opponent_index: int,
    profile: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    frames = frame_map(replay)
    anchor = player(frames[anchor_frame], player_index)
    if anchor is None:
        raise ConfigurationError("anchor player frame disappeared")
    anchor_post = anchor["post"]
    source_facing = int(anchor_post["facingDirection"])
    target_facing = int(profile.get("target_initial_facing", 1))
    if source_facing not in (-1, 1) or target_facing not in (-1, 1):
        raise ConfigurationError("facing values must be -1 or +1")
    mirror = target_facing * source_facing
    history = int(profile["anchor"]["neutral_history_frames"])
    qualification = qualify_segment(
        replay,
        frames,
        anchor_frame,
        player_index,
        opponent_index,
        profile,
        reference,
    )
    safe_end = int(qualification["last_supported_frame"])
    modifier = qualification["modifier_boundary"]
    execution_end = (
        int(modifier["source_frame"]) if modifier is not None else safe_end
    )
    warmup_start = anchor_frame - history + 1
    replay_frames = list(range(warmup_start, execution_end + 1))
    input_lines: list[str] = []
    for frame_number in replay_frames:
        sample = player(frames[frame_number], player_index)
        if sample is None:
            raise ConfigurationError("missing input player frame")
        input_lines.append(
            native_input(
                sample["pre"],
                mirror,
                require_exact_raw_main=reference.get("status") == "exact",
            )
        )
    native_rows, runner_seconds = run_native(runner, input_lines)
    safe_source_frames = list(range(anchor_frame + 1, safe_end + 1))
    expected = [
        expected_row(
            frames,
            frame_number,
            player_index,
            float(anchor_post["positionX"]),
            float(anchor_post["positionY"]),
            mirror,
            input_lines[frame_number - warmup_start],
            profile,
        )
        for frame_number in safe_source_frames
    ]
    actual = [
        actual_row(native_rows[frame_number - warmup_start])
        for frame_number in safe_source_frames
    ]
    first = first_semantic_difference(
        expected,
        actual,
        lambda source, target: compare_rows(source, target, profile),
    )
    mismatch: dict[str, Any] | None = None
    status = "qualified-pass"
    semantic_frames_checked = len(expected)
    minimizer_seconds = 0.0
    if first is not None:
        mismatch_index, differences = first
        source = expected[mismatch_index]
        target = actual[mismatch_index]
        semantic_frames_checked = mismatch_index + 1
        native_index = history + mismatch_index
        minimized_inputs = input_lines[: native_index + 1]
        first_repeat, first_seconds = run_native(runner, minimized_inputs)
        second_repeat, second_seconds = run_native(runner, minimized_inputs)
        minimizer_seconds = first_seconds + second_seconds
        status = "semantic-differential-candidate"
        mismatch = {
            "classification": status,
            "source_frame": source["source_frame"],
            "source_action_id": source["source_action_id"],
            "source_action": source["source_action"],
            "source_action_counter": source["source_action_counter"],
            "prefix_length_after_anchor": mismatch_index + 1,
            "minimized_total_input_rows": len(minimized_inputs),
            "minimized_source_frame_range": [
                warmup_start,
                int(source["source_frame"]),
            ],
            "input": source["input"],
            "differences": differences,
            "expected": source,
            "actual": target,
            "comparison_trail": comparison_trail(expected, actual, mismatch_index),
            "repeat_deterministic": first_repeat == second_repeat,
            "repeat_matches_original_prefix": (
                first_repeat == native_rows[: native_index + 1]
            ),
            "minimized_native_rows": [
                actual_row(row)
                for row in first_repeat[max(0, native_index - 4) : native_index + 1]
            ],
        }
    elif modifier is not None:
        status = "unsupported-source-modifier"

    modifier_report: dict[str, Any] | None = None
    if modifier is not None:
        boundary_index = int(modifier["source_frame"]) - warmup_start
        boundary_source = player(
            frames[int(modifier["source_frame"])], player_index
        )
        if boundary_source is None:
            raise ConfigurationError("missing source modifier boundary frame")
        boundary_post = boundary_source["post"]
        modifier_report = dict(modifier)
        modifier_report.update(
            {
                "prefix_length_after_anchor": int(modifier["source_frame"])
                - anchor_frame,
                "total_input_rows_through_boundary": boundary_index + 1,
                "target_input": input_lines[boundary_index],
                "source_boundary_observation": {
                    "action_state_id": int(boundary_post["actionStateId"]),
                    "action_state_counter": float(
                        boundary_post["actionStateCounter"]
                    ),
                    "facing": int(boundary_post["facingDirection"]),
                    "grounded": int(not bool(boundary_post["isAirborne"])),
                    "position_x": float(boundary_post["positionX"]),
                    "position_y": float(boundary_post["positionY"]),
                },
                "target_boundary_diagnostic": actual_row(native_rows[boundary_index]),
            }
        )
    velocity_fields_available = {
        axis: sum(row[axis] is not None for row in expected)
        for axis in ("velocity_x_f32", "velocity_y_f32")
    }
    return {
        "replay": replay_path.name,
        "anchor_frame": anchor_frame,
        "player_index": player_index,
        "opponent_index": opponent_index,
        "mirror": mirror,
        "status": status,
        "warmup_history_frames": history,
        "qualified_end_frame": safe_end,
        "qualified_prefix_frames": max(0, safe_end - anchor_frame),
        "qualification_stop": qualification["stop_reason"],
        "semantic_frames_checked": semantic_frames_checked,
        "source_modifier_boundary": modifier_report,
        "ucf_dashback_boundaries_exercised": qualification[
            "exercised_ucf_boundaries"
        ],
        "first_mismatch": mismatch,
        "timing_seconds": {
            "runner": runner_seconds,
            "minimizer_repeats": minimizer_seconds,
        },
        "field_coverage": {
            "strict": ["mapped_action", "facing", "grounded"],
            "float32_tolerant": ["relative_position_x", "relative_position_y"],
            "conditional_f32_tolerant_samples": velocity_fields_available,
            "observed_not_compared": [
                "source_action_counter",
                "target_action_ticks",
            ],
            "excluded_by_anchor_contract": [
                "absolute_position",
                "source_support_identity",
                "opponent_state",
                "combat",
                "shield_geometry",
            ],
        },
    }


def run_corpus(
    manifest_path: Path,
    profile_path: Path,
    work_dir: Path,
    runner: Path,
    report_path: Path,
    maximum_anchors: int,
    allow_unverified_reference: bool = False,
    extract_workers: int = 8,
) -> int:
    started = time.perf_counter()
    manifest = load_json(manifest_path)
    profile = load_json(profile_path)
    validate_manifest(manifest)
    validate_profile(profile)
    expected_parser = str(manifest["parser"]["version"])
    actual_parser = package_version(work_dir)
    if actual_parser != expected_parser:
        raise ConfigurationError(
            f"parser expected={expected_parser} actual={actual_parser}; run bootstrap"
        )
    if not runner.is_file():
        raise ConfigurationError(f"native runner not found: {runner}")
    if maximum_anchors <= 0:
        raise ConfigurationError("maximum anchors must be positive")
    if extract_workers <= 0 or extract_workers > 32:
        raise ConfigurationError("extract workers must be between 1 and 32")

    summary = {
        "replays": 0,
        "unsupported_setups": 0,
        "unsupported_reference_configurations": 0,
        "anchors_found": 0,
        "anchors_executed": 0,
        "semantic_frames_checked": 0,
        "ucf_dashback_boundaries_exercised": 0,
        "qualified_passes": 0,
        "unsupported_source_modifiers": 0,
        "semantic_differential_candidates": 0,
        "diagnostic_unverified_references": 0,
    }
    report: dict[str, Any] = {
        "schema": "ssbm-replay-production-differential-v1",
        "scope": (
            "exact-reference-gated naturally anchored isolated prefixes; "
            "not arbitrary replay resumption or whole-game equivalence"
            + (
                "; diagnostic-unverified execution explicitly enabled"
                if allow_unverified_reference
                else ""
            )
        ),
        "parser": manifest["parser"],
        "profile": {
            "id": profile.get("id"),
            "path": str(profile_path),
            "sha256": sha256(profile_path),
            "comparison": profile["comparison"],
            "reference_target": profile["reference_target"],
        },
        "manifest": {
            "id": manifest.get("id"),
            "path": str(manifest_path),
            "sha256": sha256(manifest_path),
        },
        "worker": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
            "extractor_path": str(EXTRACTOR),
            "extractor_sha256": sha256(EXTRACTOR),
            "extract_workers": extract_workers,
        },
        "runner": {
            "path": str(runner),
            "size": runner.stat().st_size,
            "sha256": sha256(runner),
        },
        "replays": [],
        "summary": summary,
    }
    corpus_dir = work_dir / "corpus"
    entries = iter(manifest["entries"])
    pending: list[
        tuple[dict[str, Any], Path, float, Future[tuple[dict[str, Any], float]]]
    ] = []

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        try:
            entry = next(entries)
        except StopIteration:
            return False
        replay_started = time.perf_counter()
        replay_path = corpus_dir / str(entry["local_name"])
        valid, evidence = verify_replay(replay_path, entry)
        if not valid:
            raise ConfigurationError(
                f"replay provenance mismatch {replay_path.name}: {evidence}"
            )
        future = executor.submit(extract_replay_timed, replay_path, work_dir)
        pending.append((entry, replay_path, replay_started, future))
        return True

    with ThreadPoolExecutor(
        max_workers=extract_workers, thread_name_prefix="slp-extract"
    ) as executor:
        for _ in range(min(extract_workers, len(manifest["entries"]))):
            submit_next(executor)
        while pending:
            entry, replay_path, replay_started, future = pending.pop(0)
            replay, parse_seconds = future.result()
            submit_next(executor)
            unsupported, limitations = validate_setup(replay, profile)
            reference = reference_qualification(replay, entry, profile)
            settings = replay.get("settings", {})
            replay_report: dict[str, Any] = {
                "file": replay_path.name,
                "size": replay_path.stat().st_size,
                "sha256": entry["sha256"],
                "provenance": {
                    key: entry.get(key)
                    for key in ("source", "revision", "license", "path", "url")
                },
                "settings": {
                    "slp_version": settings.get("slpVersion"),
                    "stage_id": settings.get("stageId"),
                    "is_pal": settings.get("isPAL"),
                    "ports": [
                        value.get("port") for value in settings.get("players", [])
                    ],
                    "characters": [
                        value.get("characterId")
                        for value in settings.get("players", [])
                    ],
                    "controller_fixes": [
                        value.get("controllerFix")
                        for value in settings.get("players", [])
                    ],
                },
                "unsupported_setup": unsupported,
                "reference_qualification": reference,
                "limitations": limitations,
                "anchors_found": 0,
                "segments": [],
                "timing_seconds": {"parse": parse_seconds},
            }
            summary["replays"] += 1
            if unsupported:
                summary["unsupported_setups"] += 1
            else:
                anchors = find_anchors(replay, profile)
                replay_report["anchors_found"] = len(anchors)
                summary["anchors_found"] += len(anchors)
                if reference["status"] != "exact":
                    execution_reference = diagnostic_execution_reference(
                        reference, allow_unverified_reference
                    )
                    if execution_reference is None:
                        # Keep parsing/anchor/provenance results, but never execute
                        # a source trace whose raw contract is incomplete or whose
                        # declared disc/modifier explicitly disagrees.
                        summary["unsupported_reference_configurations"] += 1
                        anchors = []
                    else:
                        summary["diagnostic_unverified_references"] += 1
                else:
                    execution_reference = reference
                if anchors:
                    if execution_reference is None:
                        raise ConfigurationError(
                            "internal reference execution state is missing"
                        )
                for anchor in anchors[:maximum_anchors]:
                    segment = compare_segment(
                        replay_path,
                        replay,
                        runner,
                        *anchor,
                        profile,
                        execution_reference,
                    )
                    if reference["status"] != "exact":
                        segment["reference_authority"] = (
                            "diagnostic-unverified-reference"
                        )
                        segment["reference_failures"] = reference["failures"]
                    replay_report["segments"].append(segment)
                    summary["anchors_executed"] += 1
                    summary["semantic_frames_checked"] += int(
                        segment["semantic_frames_checked"]
                    )
                    summary["ucf_dashback_boundaries_exercised"] += len(
                        segment["ucf_dashback_boundaries_exercised"]
                    )
                    status = segment["status"]
                    if status == "qualified-pass":
                        summary["qualified_passes"] += 1
                    elif status == "unsupported-source-modifier":
                        summary["unsupported_source_modifiers"] += 1
                    elif status == "semantic-differential-candidate":
                        summary["semantic_differential_candidates"] += 1
                    print(
                        "ssbm-replay-segment "
                        f"file={replay_path.name} anchor={anchor[0]} "
                        f"player={anchor[1]} status={status} "
                        f"checked={segment['semantic_frames_checked']}"
                    )
            replay_report["timing_seconds"]["total"] = (
                time.perf_counter() - replay_started
            )
            report["replays"].append(replay_report)
    report["timing_seconds"] = {"total": time.perf_counter() - started}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "ssbm-replay-differential=complete "
        f"replays={summary['replays']} "
        f"anchors-found={summary['anchors_found']} "
        f"anchors-executed={summary['anchors_executed']} "
        f"frames={summary['semantic_frames_checked']} "
        f"unsupported-reference={summary['unsupported_reference_configurations']} "
        f"diagnostic-unverified={summary['diagnostic_unverified_references']} "
        f"ucf-dashbacks={summary['ucf_dashback_boundaries_exercised']} "
        f"passes={summary['qualified_passes']} "
        f"unsupported-modifiers={summary['unsupported_source_modifiers']} "
        f"candidates={summary['semantic_differential_candidates']} "
        f"seconds={report['timing_seconds']['total']:.3f} "
        f"report={report_path}"
    )
    return 1 if summary["semantic_differential_candidates"] else 0


def watch_corpus(
    manifest_path: Path,
    profile_path: Path,
    work_dir: Path,
    runner: Path,
    report_path: Path,
    maximum_anchors: int,
    interval_seconds: float,
    allow_unverified_reference: bool,
    extract_workers: int = 8,
) -> int:
    """Keep a local replay lane hot as the pinned manifest grows.

    The watcher is intentionally manifest-driven: a new or replaced replay
    must be hash-pinned in the manifest before it is considered.  Unchanged
    manifests are not rerun, so a long-lived process does not duplicate native
    runner churn while a replay corpus is idle.  Ctrl+C stops the watcher and
    preserves a non-zero result if any iteration found a candidate.
    """

    if interval_seconds <= 0:
        raise ConfigurationError("watch interval must be positive")
    previous_manifest_sha: str | None = None
    last_result = 0
    print(
        "ssbm-replay-watch=started "
        f"manifest={manifest_path} interval={interval_seconds:g}s"
    )
    try:
        while True:
            current_manifest_sha = sha256(manifest_path)
            if current_manifest_sha != previous_manifest_sha:
                print(
                    "ssbm-replay-watch=run "
                    f"manifest-sha256={current_manifest_sha}"
                )
                last_result = max(
                    last_result,
                    run_corpus(
                        manifest_path,
                        profile_path,
                        work_dir,
                        runner,
                        report_path,
                        maximum_anchors,
                        allow_unverified_reference,
                        extract_workers,
                    ),
                )
                previous_manifest_sha = current_manifest_sha
            else:
                print("ssbm-replay-watch=idle")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("ssbm-replay-watch=stopped")
    return last_result


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="install the pinned parser and verify corpus downloads"
    )
    bootstrap_parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "tools" / "ssbm_falcon_replay_corpus.json",
    )
    bootstrap_parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "ssbm-replay-differential",
    )
    run_parser = subparsers.add_parser(
        "run", help="run every pinned replay and write a bounded JSON report"
    )
    run_parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "tools" / "ssbm_falcon_replay_corpus.json",
    )
    run_parser.add_argument(
        "--profile",
        type=Path,
        default=ROOT / "tools" / "ssbm_falcon_replay_profile.json",
    )
    run_parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "ssbm-replay-differential",
    )
    run_parser.add_argument("--runner", type=Path, required=True)
    run_parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "build" / "ssbm-replay-differential" / "report.json",
    )
    run_parser.add_argument("--maximum-anchors-per-replay", type=int, default=16)
    run_parser.add_argument(
        "--extract-workers",
        type=int,
        default=8,
        help="number of bounded parallel Slippi parser workers (1-32)",
    )
    run_parser.add_argument(
        "--allow-unverified-reference",
        action="store_true",
        help=(
            "execute only raw-complete/UCF-labeled replays lacking external "
            "disc/modifier proof; results are diagnostic, never equivalence"
        ),
    )
    watch_parser = subparsers.add_parser(
        "watch",
        help=(
            "keep a manifest-driven differential lane hot; rerun only when "
            "the pinned manifest changes"
        ),
    )
    watch_parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "tools" / "ssbm_falcon_replay_corpus.json",
    )
    watch_parser.add_argument(
        "--profile",
        type=Path,
        default=ROOT / "tools" / "ssbm_falcon_replay_profile.json",
    )
    watch_parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "ssbm-replay-differential",
    )
    watch_parser.add_argument("--runner", type=Path, required=True)
    watch_parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "build" / "ssbm-replay-differential" / "report.json",
    )
    watch_parser.add_argument("--maximum-anchors-per-replay", type=int, default=16)
    watch_parser.add_argument(
        "--extract-workers",
        type=int,
        default=8,
        help="number of bounded parallel Slippi parser workers (1-32)",
    )
    watch_parser.add_argument(
        "--interval-seconds", type=float, default=30.0
    )
    watch_parser.add_argument(
        "--allow-unverified-reference",
        action="store_true",
        help=(
            "execute only raw-complete/UCF-labeled replays lacking external "
            "disc/modifier proof; results are diagnostic, never equivalence"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "bootstrap":
            return bootstrap(args.manifest.resolve(), args.work_dir.resolve())
        if args.command == "watch":
            return watch_corpus(
                args.manifest.resolve(),
                args.profile.resolve(),
                args.work_dir.resolve(),
                args.runner.resolve(),
                args.report.resolve(),
                args.maximum_anchors_per_replay,
                args.interval_seconds,
                args.allow_unverified_reference,
                args.extract_workers,
            )
        return run_corpus(
            args.manifest.resolve(),
            args.profile.resolve(),
            args.work_dir.resolve(),
            args.runner.resolve(),
            args.report.resolve(),
            args.maximum_anchors_per_replay,
            args.allow_unverified_reference,
            args.extract_workers,
        )
    except (ConfigurationError, json.JSONDecodeError) as error:
        print(f"ssbm-replay-differential=error detail={error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
