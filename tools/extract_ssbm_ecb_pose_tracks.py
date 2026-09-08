#!/usr/bin/env python3
"""Canonicalize action-owned ECB tracks from a Dolphin movement capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from ssbm_ecb_pose import (
    ECB_POINTS,
    canonical_source_ecb,
    canonical_sha256,
    pose_f32,
    semantic_payload,
)


def captured_ecb(row: dict[str, Any], track_id: str) -> dict[str, Any]:
    surface = row.get("surface_collision_memory")
    if isinstance(surface, dict) and isinstance(surface.get("ecb"), dict):
        return surface["ecb"]
    hitbox = row.get("hitbox_memory")
    if isinstance(hitbox, dict) and isinstance(hitbox.get("fighter_ecb"), dict):
        return hitbox["fighter_ecb"]
    raise ValueError(f"track {track_id!r} is missing an ECB probe")


def extract_track(
    rows: list[dict[str, Any]],
    track_id: str,
    source_action: str,
    label_substring: str,
    first_displayed_frame: int,
    last_displayed_frame: int,
    frame_mode: str = "action",
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row.get("action") == source_action
        and label_substring in str(row.get("label", ""))
    ]
    if not selected:
        raise ValueError(f"track {track_id!r} selected no rows")

    frames: dict[int, dict[str, Any]] = {}
    last_new_frame = first_displayed_frame - 1
    for selected_index, row in enumerate(selected):
        if frame_mode == "sequential":
            displayed_frame = first_displayed_frame + selected_index
        elif frame_mode == "fixed":
            displayed_frame = first_displayed_frame
        else:
            action_frame = row.get("action_frame")
            if (
                not isinstance(action_frame, (int, float))
                or isinstance(action_frame, bool)
                or float(action_frame) != int(action_frame)
            ):
                raise ValueError(f"track {track_id!r} has a non-integral frame")
            displayed_frame = int(action_frame)
        raw_facing = row.get("facing")
        if raw_facing not in (-1, 1) or isinstance(raw_facing, bool):
            raise ValueError(f"track {track_id!r} has invalid facing")
        source_ecb = canonical_source_ecb(
            captured_ecb(row, track_id), int(raw_facing)
        )
        current_f32 = pose_f32(source_ecb)
        existing = frames.get(displayed_frame)
        if existing is not None:
            if existing["ecb_f32"] != current_f32:
                raise ValueError(
                    f"track {track_id!r} frame {displayed_frame} has "
                    "non-deterministic float32 ECB values"
                )
            continue
        if displayed_frame != last_new_frame + 1:
            raise ValueError(
                f"track {track_id!r} first exposed frame {displayed_frame} "
                f"after {last_new_frame}"
            )
        frames[displayed_frame] = {
            "displayed_frame": displayed_frame,
            "source_ecb": source_ecb,
            "ecb_f32": current_f32,
        }
        last_new_frame = displayed_frame

    expected_frames = list(range(first_displayed_frame, last_displayed_frame + 1))
    if list(frames) != expected_frames:
        raise ValueError(
            f"track {track_id!r} frames are {list(frames)}, "
            f"expected {expected_frames}"
        )
    return {
        "id": track_id,
        "source_action": source_action,
        "canonical_facing": 1,
        "label_substring": label_substring,
        "first_displayed_frame": first_displayed_frame,
        "frame_count": last_displayed_frame - first_displayed_frame + 1,
        "frames": list(frames.values()),
    }


def extract_cyclic_track(
    rows: list[dict[str, Any]],
    track_id: str,
    source_action: str,
    label_substring: str,
    frame_count: int,
    frame_value: Callable[[dict[str, Any]], object] | None = None,
) -> dict[str, Any]:
    """Canonicalize one looping ECB motion into complete frame-index order."""

    selected = [
        row
        for row in rows
        if row.get("action") == source_action
        and label_substring in str(row.get("label", ""))
    ]
    if not selected or frame_count <= 0:
        raise ValueError(f"track {track_id!r} selected no cyclic rows")

    def displayed_frame(row: dict[str, Any]) -> int:
        raw = row.get("action_frame") if frame_value is None else frame_value(row)
        if (
            not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or float(raw) != int(raw)
        ):
            raise ValueError(f"track {track_id!r} has a non-integral loop frame")
        return int(raw)

    frames_by_index: dict[int, dict[str, Any]] = {}
    previous_frame: int | None = None
    for row in selected:
        current_frame = displayed_frame(row)
        if not 0 <= current_frame < frame_count:
            raise ValueError(f"track {track_id!r} has an invalid loop frame")
        if (
            previous_frame is not None
            and current_frame != (previous_frame + 1) % frame_count
        ):
            raise ValueError(
                f"track {track_id!r} frame order diverged after {previous_frame}"
            )
        previous_frame = current_frame
        facing = row.get("facing")
        if facing not in (-1, 1) or isinstance(facing, bool):
            raise ValueError(f"track {track_id!r} has an invalid ECB row")
        source_ecb = canonical_source_ecb(
            captured_ecb(row, track_id), int(facing)
        )
        current_f32 = pose_f32(source_ecb)
        existing = frames_by_index.get(current_frame)
        if existing is not None and existing["ecb_f32"] != current_f32:
            raise ValueError(
                f"track {track_id!r} frame {current_frame} is non-deterministic"
            )
        if existing is None:
            frames_by_index[current_frame] = {
                "displayed_frame": current_frame,
                "source_ecb": source_ecb,
                "ecb_f32": current_f32,
            }
    expected_frames = list(range(frame_count))
    if sorted(frames_by_index) != expected_frames:
        raise ValueError(f"track {track_id!r} is incomplete")
    frames = [frames_by_index[index] for index in expected_frames]
    return {
        "id": track_id,
        "source_action": source_action,
        "canonical_facing": 1,
        "label_substring": label_substring,
        "first_displayed_frame": 0,
        "frame_count": frame_count,
        "frames": frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--track",
        action="append",
        nargs="+",
        metavar="TRACK_FIELD",
        required=True,
        help=(
            "ID SOURCE_ACTION LABEL_SUBSTRING LAST_FRAME, or append "
            "FIRST_FRAME before LAST_FRAME for a nonzero displayed-frame origin"
        ),
    )
    parser.add_argument(
        "--sequential-frame-track",
        action="append",
        metavar="TRACK_ID",
        help="derive hidden/manual source frames from selected row order",
    )
    parser.add_argument(
        "--fixed-frame-track",
        action="append",
        metavar="TRACK_ID",
        help="map every selected row to the declared first frame",
    )
    args = parser.parse_args()

    capture_bytes = args.capture.read_bytes()
    capture = json.loads(capture_bytes)
    rows = capture.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("capture has no rows")

    tracks: list[dict[str, Any]] = []
    track_ids: set[str] = set()
    sequential_frame_tracks = set(args.sequential_frame_track or [])
    fixed_frame_tracks = set(args.fixed_frame_track or [])
    if sequential_frame_tracks & fixed_frame_tracks:
        raise SystemExit("a track cannot use both sequential and fixed frames")
    for raw_track in args.track:
        if len(raw_track) == 4:
            raw_id, source_action, label_substring, raw_last_frame = raw_track
            raw_first_frame = "0"
        elif len(raw_track) == 5:
            (
                raw_id,
                source_action,
                label_substring,
                raw_first_frame,
                raw_last_frame,
            ) = raw_track
        else:
            raise SystemExit(
                "--track expects 4 fields (zero-based) or 5 fields "
                "(explicit first/last displayed frame)"
            )
        if (
            not raw_id
            or raw_id in track_ids
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in raw_id)
        ):
            raise SystemExit(f"invalid or duplicate track id: {raw_id!r}")
        try:
            first_frame = int(raw_first_frame)
            last_frame = int(raw_last_frame)
        except ValueError as error:
            raise SystemExit(
                "invalid displayed-frame span: "
                f"{raw_first_frame!r}..{raw_last_frame!r}"
            ) from error
        if (
            first_frame < 0
            or last_frame < first_frame
            or str(first_frame) != raw_first_frame
            or str(last_frame) != raw_last_frame
        ):
            raise SystemExit(
                "invalid displayed-frame span: "
                f"{raw_first_frame!r}..{raw_last_frame!r}"
            )
        tracks.append(
            extract_track(
                rows,
                raw_id,
                source_action,
                label_substring,
                first_frame,
                last_frame,
                (
                    "sequential"
                    if raw_id in sequential_frame_tracks
                    else "fixed" if raw_id in fixed_frame_tracks else "action"
                ),
            )
        )
        track_ids.add(raw_id)

    unknown_frame_tracks = (
        sequential_frame_tracks | fixed_frame_tracks
    ) - track_ids
    if unknown_frame_tracks:
        raise SystemExit(
            "frame modes reference unknown tracks: "
            + ", ".join(sorted(unknown_frame_tracks))
        )

    semantic = semantic_payload(tracks)
    profile = {
        "schema": 1,
        "scope": "ssbm-action-owned-ecb-pose-tracks",
        "oracle": capture.get("oracle"),
        "disc": capture.get("disc"),
        "fighter": capture.get("fighter"),
        "stage": capture.get("stage"),
        "capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
        "semantic_sha256": canonical_sha256(semantic),
        "coordinate_conversion": {
            "x_sim_units_per_melee_unit": "12/115",
            "y_sim_units_per_melee_unit": "11/62",
            "rounding": "ieee754-binary32",
        },
        "tracks": tracks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        "ssbm-ecb-pose-tracks=pass "
        f"tracks={len(tracks)} "
        f"poses={sum(track['frame_count'] for track in tracks)} "
        f"capture_sha256={profile['capture_sha256']} "
        f"semantic_sha256={profile['semantic_sha256']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
