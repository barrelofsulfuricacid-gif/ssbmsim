#!/usr/bin/env python3
"""Qualify Falcon hit-sphere versus shield collision against Dolphin."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


EXPECTED_CAPTURE_SHA256 = (
    "2df522e9bc93a09b61d15406f9281f4638f9c81796da349d033d90a112d51289"
)
EXPECTED_COLLISION_SOURCE_SHA256 = (
    "fa47d275f86956edb3c3a228a7fcc160e6f467c2d4bfd5f86d71f1d55e13e1fb"
)
EXPECTED_DISC_SHA256 = (
    "0de05981a34156b9cedcef73c73d4244ac05cf6149ab3c9cfed917698819e464"
)
EXPECTED_DECOMP_REVISION = "9509dc04406fb2028bfab01243841ba4787c0fb7"
EXPECTED_BOUNDARIES = {
    "neutral": (28.60, 28.65),
    "up_right": (29.65, 29.70),
    "down_right": (29.60, 29.65),
}
CASE_PATTERN = re.compile(
    r"^(shield_collision_(neutral|up_right|down_right)_(\d+\.\d+))_"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_opponent_hitboxes(row: dict[str, Any]) -> list[dict[str, Any]]:
    memory = row.get("hitbox_memory")
    if not isinstance(memory, dict):
        return []
    return [
        dict(hitbox)
        for hitbox in memory.get("opponent_hitboxes", [])
        if int(hitbox.get("state", 0)) != 0
        and float(hitbox.get("radius", 0.0)) > 0.0
        and float(hitbox.get("damage", 0.0)) > 0.0
    ]


def closest_segment_distance(
    point: list[float],
    endpoint_a: list[float],
    endpoint_b: list[float],
) -> float:
    segment = [b - a for a, b in zip(endpoint_a, endpoint_b, strict=True)]
    from_a = [p - a for p, a in zip(point, endpoint_a, strict=True)]
    length_squared = sum(value * value for value in segment)
    if length_squared == 0.0:
        nearest = endpoint_a
    else:
        projection = sum(
            delta * direction
            for delta, direction in zip(from_a, segment, strict=True)
        ) / length_squared
        projection = min(1.0, max(0.0, projection))
        nearest = [
            a + projection * direction
            for a, direction in zip(endpoint_a, segment, strict=True)
        ]
    return math.dist(point, nearest)


def collision_margin(
    shield_memory: dict[str, Any], hitbox: dict[str, Any]
) -> float:
    matrix = [float(value) for value in shield_memory["shield_joint_matrix"]]
    center = [matrix[3], matrix[7], matrix[11]]
    uniform_scale = math.sqrt(matrix[0] ** 2 + matrix[4] ** 2 + matrix[8] ** 2)
    shield_radius = float(shield_memory["shield_radius"])
    hit_radius = float(hitbox["radius"])
    distance = closest_segment_distance(
        center,
        [float(value) for value in hitbox["previous_position"]],
        [float(value) for value in hitbox["position"]],
    )
    return uniform_scale * shield_radius + hit_radius - distance


def verify_case(case: str, rows: list[dict[str, Any]]) -> tuple[bool, float]:
    first_active = next(
        (index for index, row in enumerate(rows) if active_opponent_hitboxes(row)),
        None,
    )
    if first_active is None or first_active == 0:
        raise ValueError(f"{case}: incomplete active-hitbox timeline")
    evaluation = rows[first_active]
    hitboxes = active_opponent_hitboxes(evaluation)
    shield_memory = rows[first_active - 1].get("shield_memory")
    if not hitboxes or not isinstance(shield_memory, dict):
        raise ValueError(f"{case}: missing pre-collision shield or hitbox memory")

    margins = [collision_margin(shield_memory, hitbox) for hitbox in hitboxes]
    predicted = max(margins) >= 0.0
    actual = evaluation.get("action") == "SHIELD_STUN"
    if actual != any(row.get("action") == "SHIELD_STUN" for row in rows):
        raise ValueError(f"{case}: collision outcome is not on the evaluation frame")
    if predicted != actual:
        raise ValueError(
            f"{case}: source predicate predicted={predicted} actual={actual} "
            f"maximum_margin={max(margins):.9f}"
        )
    damage = {float(row["damage_percent"]) for row in rows}
    if len(damage) != 1:
        raise ValueError(f"{case}: shielded route changed defender damage")
    return actual, max(margins)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("collision_source", type=Path)
    args = parser.parse_args()

    capture_digest = sha256(args.capture)
    if capture_digest != EXPECTED_CAPTURE_SHA256:
        raise SystemExit(f"unexpected shield-collision capture SHA-256: {capture_digest}")
    source_digest = sha256(args.collision_source)
    if source_digest != EXPECTED_COLLISION_SOURCE_SHA256:
        raise SystemExit(f"unexpected lbcollision.c SHA-256: {source_digest}")
    capture: dict[str, Any] = json.loads(args.capture.read_text(encoding="utf-8"))
    hitbox_probe = capture.get("hitbox_memory_probe", {})
    disc = capture.get("disc", {})
    rows: list[dict[str, Any]] = capture.get("rows", [])
    if (
        capture.get("schema") != 10
        or capture.get("fighter") != "CPTFALCON"
        or capture.get("opponent") != "CPTFALCON"
        or capture.get("stage") != "FINAL_DESTINATION"
        or capture.get("dolphin_version") != "3.4.0"
        or disc.get("game_id") != "GALE01"
        or disc.get("revision") != 2
        or disc.get("sha256") != EXPECTED_DISC_SHA256
        or hitbox_probe.get("decomp_revision") != EXPECTED_DECOMP_REVISION
        or len(rows) != 2568
    ):
        raise SystemExit("unexpected shield-collision capture provenance")

    cases: dict[str, list[dict[str, Any]]] = {}
    directions: dict[str, list[tuple[float, bool, float]]] = {
        direction: [] for direction in EXPECTED_BOUNDARIES
    }
    for row in rows:
        match = CASE_PATTERN.match(str(row.get("label", "")))
        if match is not None:
            cases.setdefault(match.group(1), []).append(row)
    if len(cases) != 33:
        raise SystemExit(f"expected 33 shield-collision decisions, found {len(cases)}")

    for case, case_rows in cases.items():
        match = CASE_PATTERN.match(str(case_rows[0]["label"]))
        if match is None:
            raise AssertionError("case label was validated while grouping")
        actual, margin = verify_case(case, case_rows)
        directions[match.group(2)].append((float(match.group(3)), actual, margin))

    boundary_parts = []
    for direction, trials in directions.items():
        trials.sort()
        hits = [distance for distance, actual, _ in trials if actual]
        misses = [distance for distance, actual, _ in trials if not actual]
        boundary = (max(hits), min(misses))
        if boundary != EXPECTED_BOUNDARIES[direction]:
            raise SystemExit(
                f"{direction}: boundary {boundary} != {EXPECTED_BOUNDARIES[direction]}"
            )
        boundary_parts.append(f"{direction}={boundary[0]:.2f}/{boundary[1]:.2f}")

    print(
        "ssbm-shield-collision=pass "
        f"decisions={len(cases)} comparable_frames={len(rows)} "
        f"boundaries={','.join(boundary_parts)} capture_sha256={capture_digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
