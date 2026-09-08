#!/usr/bin/env python3
"""Generate immutable C hurt-pose tracks from a pinned canonical profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from ssbm_collision import (
    binary32,
    canonical_json_sha256,
    hurt_pose_tracks_semantic_payload,
)


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is not a C identifier")
    return value


def c_float32(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError(f"hurt-pose coordinate is non-finite: {value}")
    literal = f"{binary32(value):.9g}"
    if "." not in literal and "e" not in literal:
        literal += ".0"
    return literal + "f"


def uint8(value: int) -> str:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"hurt-pose byte is outside uint8: {value}")
    return f"UINT8_C({value})"


def uint16(value: int) -> str:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"hurt-pose offset is outside uint16: {value}")
    return f"UINT16_C({value})"


def load_and_validate(
    repository: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("scope") != "ssbm-hurt-pose-import":
        raise ValueError("unsupported hurt-pose import manifest")
    profile_value = manifest.get("profile")
    if not isinstance(profile_value, str):
        raise ValueError("hurt-pose import manifest is missing profile")
    profile_path = repository / profile_value
    profile_digest = file_sha256(profile_path)
    if profile_digest != manifest.get("profile_sha256"):
        raise ValueError(
            f"hurt-pose profile SHA-256 is {profile_digest}, "
            f"expected {manifest.get('profile_sha256')}"
        )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    tracks = profile.get("tracks")
    declared_tracks = manifest.get("tracks")
    if (
        profile.get("schema") != 1
        or profile.get("scope") != "ssbm-bounded-hurt-pose-tracks"
        or profile.get("fighter") != manifest.get("fighter")
        or profile.get("capture_sha256") != manifest.get("capture_sha256")
        or profile.get("semantic_sha256") != manifest.get("semantic_sha256")
        or not isinstance(tracks, list)
        or not isinstance(declared_tracks, list)
        or len(tracks) != len(declared_tracks)
    ):
        raise ValueError("hurt-pose profile provenance or track count mismatch")
    semantic_digest = canonical_json_sha256(
        hurt_pose_tracks_semantic_payload(tracks)
    )
    if semantic_digest != manifest.get("semantic_sha256"):
        raise ValueError(
            f"hurt-pose semantic SHA-256 is {semantic_digest}, "
            f"expected {manifest.get('semantic_sha256')}"
        )

    pose_count = 0
    unique_poses: set[tuple[tuple[float | int, ...], ...]] = set()
    for track_index, (track, declared) in enumerate(
        zip(tracks, declared_tracks, strict=True)
    ):
        frames = track.get("frames")
        expected_count = declared.get("frame_count")
        require_identifier(declared.get("enum"), f"track {track_index} enum")
        if (
            track.get("id") != declared.get("id")
            or track.get("canonical_facing") != 1
            or not isinstance(track.get("first_displayed_frame"), int)
            or isinstance(track.get("first_displayed_frame"), bool)
            or track.get("first_displayed_frame") < 0
            or not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or track.get("frame_count") != expected_count
            or not isinstance(frames, list)
            or len(frames) != expected_count
        ):
            raise ValueError(f"hurt-pose track {track_index} does not match manifest")
        first_displayed_frame = int(track["first_displayed_frame"])
        for displayed_frame, frame in enumerate(
            frames,
            start=first_displayed_frame,
        ):
            capsules = frame.get("capsules_f32")
            if (
                frame.get("displayed_frame") != displayed_frame
                or not isinstance(capsules, list)
                or len(capsules) != 11
            ):
                raise ValueError(
                    f"invalid pose boundary in track {track.get('id')!r} "
                    f"frame {displayed_frame}"
                )
            pose: list[tuple[float | int, ...]] = []
            for capsule_index, capsule in enumerate(capsules):
                if (
                    not isinstance(capsule, list)
                    or len(capsule) != 10
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        for value in capsule[:7]
                    )
                    or any(
                        not isinstance(value, int) or isinstance(value, bool)
                        for value in capsule[7:]
                    )
                    or capsule[7] != capsule_index
                ):
                    raise ValueError(
                        f"invalid capsule in track {track.get('id')!r} "
                        f"frame {displayed_frame}"
                    )
                pose.append(
                    (
                        *(binary32(float(value)) for value in capsule[:7]),
                        *(int(value) for value in capsule[7:]),
                    )
                )
            unique_poses.add(tuple(pose))
            pose_count += 1

    expected_pose_count = manifest.get("expected_pose_count")
    expected_unique_count = manifest.get("expected_unique_pose_count")
    expected_capsule_count = manifest.get("expected_capsule_count")
    if (
        pose_count != expected_pose_count
        or len(unique_poses) != expected_unique_count
        or sum(len(pose) for pose in unique_poses) != expected_capsule_count
    ):
        raise ValueError(
            "hurt-pose completeness mismatch: "
            f"poses={pose_count} unique={len(unique_poses)} "
            f"capsules={sum(len(pose) for pose in unique_poses)}"
        )
    require_identifier(manifest.get("symbol_prefix"), "symbol_prefix")
    require_identifier(manifest.get("enum_prefix"), "enum_prefix")
    return manifest, profile


def generate(manifest: dict[str, Any], profile: dict[str, Any]) -> str:
    symbol_prefix = str(manifest["symbol_prefix"])
    enum_prefix = str(manifest["enum_prefix"])
    tracks = profile["tracks"]
    declared_tracks = manifest["tracks"]
    moves: list[tuple[int, int, int]] = []
    frames: list[tuple[int, int]] = []
    capsules: list[tuple[float | int, ...]] = []
    pose_offsets: dict[tuple[tuple[float | int, ...], ...], int] = {}

    for track in tracks:
        frame_offset = len(frames)
        for frame in track["frames"]:
            pose = tuple(
                (
                    *(binary32(float(value)) for value in capsule[:7]),
                    *(int(value) for value in capsule[7:]),
                )
                for capsule in frame["capsules_f32"]
            )
            capsule_offset = pose_offsets.get(pose)
            if capsule_offset is None:
                capsule_offset = len(capsules)
                pose_offsets[pose] = capsule_offset
                capsules.extend(pose)
            frames.append((capsule_offset, len(pose)))
        moves.append(
            (
                frame_offset,
                int(track["first_displayed_frame"]),
                int(track["frame_count"]),
            )
        )

    lines = [
        "/* Generated by tools/generate_ssbm_hurt_pose_include.py. */",
        f"/* profile SHA-256: {manifest['profile_sha256']} */",
        f"/* capture SHA-256: {manifest['capture_sha256']} */",
        f"/* semantic SHA-256: {manifest['semantic_sha256']} */",
        "",
        "enum",
        "{",
    ]
    for index, declared in enumerate(declared_tracks):
        lines.append(
            f"    {enum_prefix}_{declared['enum']} = {index},"
        )
    lines.extend(
        [
            f"    {enum_prefix}_COUNT = {len(declared_tracks)}",
            "};",
            "",
            "static const reference_hurt_move",
            f"{symbol_prefix}_moves[{enum_prefix}_COUNT] = {{",
        ]
    )
    lines.extend(
        f"    {{ {uint16(offset)}, {uint8(first)}, {uint8(count)} }},"
        for offset, first, count in moves
    )
    lines.extend(
        [
            "};",
            "",
            "static const reference_hurt_frame",
            f"{symbol_prefix}_frames[] = {{",
        ]
    )
    lines.extend(
        f"    {{ {uint16(offset)}, {uint8(count)}, UINT8_C(0) }},"
        for offset, count in frames
    )
    lines.extend(
        [
            "};",
            "",
            "static const reference_hurt_capsule",
            f"{symbol_prefix}_capsules[] = {{",
        ]
    )
    for capsule in capsules:
        lines.append(
            "    { "
            + ", ".join(
                [*(c_float32(float(value)) for value in capsule[:7]),
                 *(uint8(value) for value in capsule[7:]),
                 "UINT8_C(0)"]
            )
            + " },"
        )
    lines.extend(
        [
            "};",
            "",
            "_Static_assert(",
            f"    sizeof({symbol_prefix}_moves) / sizeof({symbol_prefix}_moves[0]) ==",
            f"        (size_t){enum_prefix}_COUNT,",
            '    "generated hurt-pose move table is incomplete");',
            "_Static_assert(",
            f"    sizeof({symbol_prefix}_frames) / sizeof({symbol_prefix}_frames[0]) ==",
            f"        (size_t){manifest['expected_pose_count']},",
            '    "generated hurt-pose frame table is incomplete");',
            "_Static_assert(",
            f"    sizeof({symbol_prefix}_capsules) / sizeof({symbol_prefix}_capsules[0]) ==",
            f"        (size_t){manifest['expected_capsule_count']},",
            '    "generated hurt-pose capsule table is incomplete");',
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[1]
    manifest, profile = load_and_validate(repository, args.manifest.resolve())
    output = generate(manifest, profile)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != output:
            raise SystemExit(f"generated hurt-pose include is stale: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8", newline="\n")
    print(
        "ssbm-hurt-pose-include=pass "
        f"tracks={len(profile['tracks'])} "
        f"poses={manifest['expected_pose_count']} "
        f"capsules={manifest['expected_capsule_count']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
