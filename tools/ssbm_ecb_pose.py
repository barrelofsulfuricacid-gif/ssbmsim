"""Shared canonical representation for captured SSBM action-owned ECB poses."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any


X_SIM_PER_MELEE_UNIT = 12.0 / 115.0
Y_SIM_PER_MELEE_UNIT = 11.0 / 62.0
ECB_POINTS = ("top", "bottom", "right", "left")


def canonical_source_ecb(
    ecb: dict[str, Any], facing: int
) -> dict[str, list[float]]:
    if facing not in (-1, 1):
        raise ValueError(f"invalid ECB facing {facing}")
    source_points: dict[str, list[float]] = {}
    for point in ECB_POINTS:
        coordinates = ecb.get(point)
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in coordinates
            )
        ):
            raise ValueError(f"invalid ECB {point} point")
        source_points[point] = [float(coordinates[0]), float(coordinates[1])]
    if facing == 1:
        return source_points
    return {
        "top": [-source_points["top"][0], source_points["top"][1]],
        "bottom": [-source_points["bottom"][0], source_points["bottom"][1]],
        "right": [-source_points["left"][0], source_points["left"][1]],
        "left": [-source_points["right"][0], source_points["right"][1]],
    }


def binary32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def coordinate_f32(value: float, axis: int) -> float:
    if axis not in (0, 1):
        raise ValueError(f"invalid ECB coordinate axis {axis}")
    scale = X_SIM_PER_MELEE_UNIT if axis == 0 else Y_SIM_PER_MELEE_UNIT
    return binary32(value * scale)


def pose_f32(ecb: dict[str, Any]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for point in ECB_POINTS:
        coordinates = ecb.get(point)
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in coordinates
            )
        ):
            raise ValueError(f"invalid ECB {point} point")
        result[point] = [
            coordinate_f32(float(coordinates[0]), 0),
            coordinate_f32(float(coordinates[1]), 1),
        ]
    return result


def semantic_payload(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": 2,
        "coordinate_system": "simulation-float32-from-melee-source-units",
        "tracks": [
            {
                "id": track["id"],
                "source_action": track["source_action"],
                "poses": [
                    {
                        "displayed_frame": frame["displayed_frame"],
                        "ecb_f32": frame["ecb_f32"],
                    }
                    for frame in track["frames"]
                ],
            }
            for track in tracks
        ],
    }


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
