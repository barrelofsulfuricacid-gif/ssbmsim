#!/usr/bin/env python3
"""Evaluate the joint-space subset needed by deterministic HSD hurt poses.

This is an offline source-data helper.  It deliberately models only the
Euler-SRT, parented HSD_Joint surface used by Melee fighter hurt capsules;
unsupported joint flags or RObj constraints fail closed instead of silently
producing an approximate pose.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Iterable

from hsd_figatree import FigaTree, sample_track
from ssbm_dat import HsdArchive, ft_common_data


JOBJ_CLASSICAL_SCALE = 1 << 3
JOBJ_INSTANCE = 1 << 12
JOBJ_SPLINE = 1 << 14
JOBJ_USE_QUATERNION = 1 << 17
JOBJ_JOINT_MASK = 3 << 21
JOBJ_USER_DEFINED_MATRIX = 1 << 23
JOBJ_INDEPENDENT_PARENT = 1 << 24
JOBJ_INDEPENDENT_SRT = 1 << 25
FIGHTER_ANIMATION_TRANSLATION_FLAG = 0x80000000

TRACK_ROTATE_X = 1
TRACK_ROTATE_Y = 2
TRACK_ROTATE_Z = 3
TRACK_TRANSLATE_X = 5
TRACK_TRANSLATE_Y = 6
TRACK_TRANSLATE_Z = 7
TRACK_SCALE_X = 8
TRACK_SCALE_Y = 9
TRACK_SCALE_Z = 10

SUPPORTED_TRACK_TYPES = frozenset(
    {
        TRACK_ROTATE_X,
        TRACK_ROTATE_Y,
        TRACK_ROTATE_Z,
        TRACK_TRANSLATE_X,
        TRACK_TRANSLATE_Y,
        TRACK_TRANSLATE_Z,
        TRACK_SCALE_X,
        TRACK_SCALE_Y,
        TRACK_SCALE_Z,
    }
)

_COMMON_ATTRIBUTE_MODEL_SCALING = 35


@dataclass(frozen=True)
class Joint:
    source_index: int
    parent_index: int
    flags: int
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    translation: tuple[float, float, float]


@dataclass(frozen=True)
class HurtCapsule:
    bone_index: int
    height: int
    grabbable: int
    offset_a: tuple[float, float, float]
    offset_b: tuple[float, float, float]
    radius: float


@dataclass(frozen=True)
class FighterPartLayout:
    """One fighter kind's semantic/runtime/model-joint correspondence."""

    joint_to_part: tuple[int, ...]
    part_to_joint: tuple[int, ...]
    source_joint_by_runtime_part: tuple[int, ...]


Matrix = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


def fighter_model_scale(archive: HsdArchive, root_name: str) -> float:
    """Read the fighter common-attribute model scale used by hurt geometry."""

    root = archive.root(root_name)
    if root + 4 > len(archive.data):
        raise ValueError("fighter root is truncated")
    attributes = struct.unpack_from(">I", archive.data, root)[0]
    offset = attributes + _COMMON_ATTRIBUTE_MODEL_SCALING * 4
    if offset + 4 > len(archive.data):
        raise ValueError("fighter model scale is out of bounds")
    value = struct.unpack_from(">f", archive.data, offset)[0]
    if not 0.1 <= value <= 4.0:
        raise ValueError("fighter model scale is invalid")
    return value


def fighter_animation_slice(
    fighter_archive: HsdArchive,
    animation_archive: bytes,
    fighter_root_name: str,
    submotion_index: int,
) -> bytes:
    """Return one fighter FigaTree archive from its concatenated AJ file."""

    root = fighter_archive.root(fighter_root_name)
    if root + 0x10 > len(fighter_archive.data):
        raise ValueError("fighter root is truncated")
    subactions = struct.unpack_from(">I", fighter_archive.data, root + 0x0C)[0]
    record = subactions + submotion_index * 0x18
    if record + 12 > len(fighter_archive.data):
        raise ValueError("fighter submotion record is out of bounds")
    offset, size = struct.unpack_from(">2I", fighter_archive.data, record + 4)
    if size == 0 or offset + size > len(animation_archive):
        raise ValueError("fighter animation slice is invalid")
    return animation_archive[offset : offset + size]


def fighter_animation_flags(
    fighter_archive: HsdArchive,
    fighter_root_name: str,
    submotion_index: int,
) -> int:
    """Return the submotion flags installed into Fighter.x594."""

    root = fighter_archive.root(fighter_root_name)
    if root + 0x10 > len(fighter_archive.data):
        raise ValueError("fighter root is truncated")
    subactions = struct.unpack_from(">I", fighter_archive.data, root + 0x0C)[0]
    record = subactions + submotion_index * 0x18
    if record + 0x14 > len(fighter_archive.data):
        raise ValueError("fighter submotion record is out of bounds")
    return struct.unpack_from(">I", fighter_archive.data, record + 0x10)[0]


def read_fighter_part_layout(
    common_dat: bytes,
    fighter_kind: int,
) -> FighterPartLayout:
    """Decode PlCo.dat's ftPartsTable and omitted runtime-part slots.

    ``ftParts_SetupParts`` consumes the model tree in traversal order while
    inserting null runtime parts named by ``Fighter_804D6540``.  Hurtbox bone
    indices address that runtime-parts array, not the semantic Fighter_Part
    enum, so importers must retain this mapping even for characters such as
    Falcon whose omitted-slot list is empty.
    """

    data, pointers = ft_common_data(common_dat)
    if not 0 <= fighter_kind < 33:
        raise ValueError("fighter kind is out of bounds")
    table_slot = pointers[4] + fighter_kind * 4
    omitted_slot = pointers[5] + fighter_kind * 4
    if table_slot + 4 > len(data) or omitted_slot + 4 > len(data):
        raise ValueError("fighter part pointer table is truncated")
    table = struct.unpack_from(">I", data, table_slot)[0]
    omitted = struct.unpack_from(">I", data, omitted_slot)[0]
    if table == 0 or table + 12 > len(data):
        raise ValueError("fighter part table is absent or truncated")
    joint_to_part_offset, part_to_joint_offset, part_count = struct.unpack_from(
        ">3I", data, table
    )
    if (
        part_count == 0
        or part_count > 140
        or joint_to_part_offset + part_count > len(data)
        or part_to_joint_offset + 54 > len(data)
    ):
        raise ValueError("fighter part table has invalid bounds")

    omitted_parts: set[int] = set()
    if omitted != 0:
        if omitted + 8 > len(data):
            raise ValueError("fighter omitted-part descriptor is truncated")
        entries, count = struct.unpack_from(">2I", data, omitted)
        if count > 32 or entries + count * 4 > len(data):
            raise ValueError("fighter omitted-part entries are invalid")
        for index in range(count):
            part = data[entries + index * 4]
            if part >= part_count or part in omitted_parts:
                raise ValueError("fighter omitted-part entry is invalid")
            omitted_parts.add(part)

    source_joint = 0
    source_joint_by_runtime_part: list[int] = []
    for part in range(part_count):
        if part in omitted_parts:
            source_joint_by_runtime_part.append(-1)
        else:
            source_joint_by_runtime_part.append(source_joint)
            source_joint += 1
    return FighterPartLayout(
        tuple(data[joint_to_part_offset : joint_to_part_offset + part_count]),
        tuple(data[part_to_joint_offset : part_to_joint_offset + 54]),
        tuple(source_joint_by_runtime_part),
    )


def read_joint_tree(archive: HsdArchive, root_name: str) -> tuple[Joint, ...]:
    """Flatten one ordinary HSD_Joint tree in Melee's runtime traversal order."""

    data = archive.data
    joints: list[Joint] = []

    def visit(offset: int, parent_index: int) -> None:
        if offset + 0x40 > len(data):
            raise ValueError("HSD_Joint is out of bounds")
        source_index = len(joints)
        flags, child, _next = struct.unpack_from(">3I", data, offset + 0x04)
        rotation_scale_translation = struct.unpack_from(">9f", data, offset + 0x14)
        robj = struct.unpack_from(">I", data, offset + 0x3C)[0]
        unsupported_flags = flags & (
            JOBJ_INSTANCE
            | JOBJ_SPLINE
            | JOBJ_USE_QUATERNION
            | JOBJ_JOINT_MASK
            | JOBJ_USER_DEFINED_MATRIX
            | JOBJ_INDEPENDENT_PARENT
            | JOBJ_INDEPENDENT_SRT
        )
        if unsupported_flags or robj:
            raise ValueError(
                f"joint {source_index} uses unsupported HSD behavior: "
                f"flags=0x{flags:08x} robj=0x{robj:08x}"
            )
        joints.append(
            Joint(
                source_index,
                parent_index,
                flags,
                tuple(rotation_scale_translation[0:3]),
                tuple(rotation_scale_translation[3:6]),
                tuple(rotation_scale_translation[6:9]),
            )
        )
        sibling = child
        while sibling:
            if sibling + 0x10 > len(data):
                raise ValueError("HSD_Joint sibling is out of bounds")
            next_sibling = struct.unpack_from(">I", data, sibling + 0x0C)[0]
            visit(sibling, source_index)
            sibling = next_sibling

    visit(archive.root(root_name), -1)
    return tuple(joints)


def read_fighter_hurt_capsules(
    fighter_archive: HsdArchive,
    fighter_root_name: str,
) -> tuple[HurtCapsule, ...]:
    """Read the immutable ftData.x30 hurt-capsule descriptors."""

    data = fighter_archive.data
    fighter = fighter_archive.root(fighter_root_name)
    if fighter + 0x34 > len(data):
        raise ValueError("fighter data root is truncated")
    descriptor = struct.unpack_from(">I", data, fighter + 0x30)[0]
    if descriptor + 8 > len(data):
        raise ValueError("fighter hurt-capsule descriptor is out of bounds")
    count, entries = struct.unpack_from(">II", data, descriptor)
    if count == 0 or count > 15 or entries + count * 0x28 > len(data):
        raise ValueError("invalid fighter hurt-capsule table")
    result: list[HurtCapsule] = []
    for index in range(count):
        values = struct.unpack_from(">3I7f", data, entries + index * 0x28)
        result.append(
            HurtCapsule(
                int(values[0]),
                int(values[1]),
                int(values[2]),
                tuple(values[3:6]),
                tuple(values[6:9]),
                float(values[9]),
            )
        )
    return tuple(result)


def required_joint_indices(
    joints: tuple[Joint, ...],
    capsules: Iterable[HurtCapsule],
    part_layout: FighterPartLayout | None = None,
    extra_source_indices: Iterable[int] = (),
) -> tuple[int, ...]:
    """Return the parent-closed joint subset in source traversal order."""

    required: set[int] = set()
    requested = [
        (
            capsule.bone_index
            if part_layout is None
            else part_layout.source_joint_by_runtime_part[capsule.bone_index]
        )
        for capsule in capsules
    ]
    requested.extend(extra_source_indices)
    for index in requested:
        if not 0 <= index < len(joints):
            raise ValueError(f"pose output references invalid joint {index}")
        while index >= 0 and index not in required:
            required.add(index)
            index = joints[index].parent_index
    return tuple(index for index in range(len(joints)) if index in required)


def _srt_matrix(
    scale: tuple[float, float, float],
    rotation: tuple[float, float, float],
    translation: tuple[float, float, float],
    parent_cumulative_scale: tuple[float, float, float] | None,
) -> Matrix:
    sin_x, sin_y, sin_z = (math.sin(value) for value in rotation)
    cos_x, cos_y, cos_z = (math.cos(value) for value in rotation)
    scale_x_2 = scale_x_1 = scale_x = scale[0]
    scale_y_2 = scale_y_1 = scale_y = scale[1]
    scale_z_2 = scale_z_1 = scale_z = scale[2]
    if parent_cumulative_scale is not None:
        parent_x, parent_y, parent_z = parent_cumulative_scale
        scale_y_2 *= parent_y / parent_x
        scale_z_2 *= parent_z / parent_x
        scale_x_1 *= parent_x / parent_y
        scale_z_1 *= parent_z / parent_y
        scale_x *= parent_x / parent_z
        scale_y *= parent_y / parent_z
    temp_1 = sin_x * sin_y
    temp_2 = cos_x * sin_y
    return (
        (
            cos_z * (scale_x_2 * cos_y),
            scale_y_2 * ((cos_z * temp_1) - (cos_x * sin_z)),
            scale_z_2 * ((cos_z * temp_2) + (sin_x * sin_z)),
            translation[0],
        ),
        (
            sin_z * (scale_x_1 * cos_y),
            scale_y_1 * ((sin_z * temp_1) + (cos_x * cos_z)),
            scale_z_1 * ((sin_z * temp_2) - (sin_x * cos_z)),
            translation[1],
        ),
        (
            -scale_x * sin_y,
            cos_y * (scale_y * sin_x),
            cos_y * (scale_z * cos_x),
            translation[2],
        ),
    )


def _concat(left: Matrix, right: Matrix) -> Matrix:
    return tuple(
        tuple(
            sum(left[row][inner] * right[inner][column] for inner in range(3))
            + (left[row][3] if column == 3 else 0.0)
            for column in range(4)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _transform(matrix: Matrix, value: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(
        sum(matrix[row][column] * value[column] for column in range(3))
        + matrix[row][3]
        for row in range(3)
    )  # type: ignore[return-value]


def evaluate_joint_matrices(
    joints: tuple[Joint, ...],
    animation: FigaTree,
    frame: float,
) -> tuple[Matrix, ...]:
    """Evaluate an Euler fighter FigaTree using the pinned HSD SRT ordering."""

    if len(animation.nodes) != len(joints):
        raise ValueError("FigaTree and fighter joint counts disagree")
    matrices: list[Matrix] = []
    cumulative_scales: list[tuple[float, float, float] | None] = []
    for joint, tracks in zip(joints, animation.nodes, strict=True):
        rotation = list(joint.rotation)
        scale = list(joint.scale)
        translation = list(joint.translation)
        seen_types: set[int] = set()
        for track in tracks:
            if track.track_type not in SUPPORTED_TRACK_TYPES:
                continue
            if track.track_type in seen_types:
                raise ValueError(
                    f"joint {joint.source_index} repeats track {track.track_type}"
                )
            seen_types.add(track.track_type)
            value = sample_track(track, frame)
            if TRACK_ROTATE_X <= track.track_type <= TRACK_ROTATE_Z:
                rotation[track.track_type - TRACK_ROTATE_X] = value
            elif TRACK_TRANSLATE_X <= track.track_type <= TRACK_TRANSLATE_Z:
                translation[track.track_type - TRACK_TRANSLATE_X] = value
            elif TRACK_SCALE_X <= track.track_type <= TRACK_SCALE_Z:
                scale[track.track_type - TRACK_SCALE_X] = value
        parent = joint.parent_index
        parent_scale = cumulative_scales[parent] if parent >= 0 else None
        if joint.flags & JOBJ_CLASSICAL_SCALE:
            cumulative_scale = parent_scale
        elif parent_scale is None:
            cumulative_scale = tuple(scale)
        else:
            cumulative_scale = tuple(
                scale[axis] * parent_scale[axis] for axis in range(3)
            )
        local = _srt_matrix(
            tuple(scale), tuple(rotation), tuple(translation), parent_scale
        )
        matrices.append(_concat(matrices[parent], local) if parent >= 0 else local)
        cumulative_scales.append(cumulative_scale)
    return tuple(matrices)


def evaluate_hurt_capsules(
    joints: tuple[Joint, ...],
    animation: FigaTree,
    capsules: tuple[HurtCapsule, ...],
    frame: float,
    part_layout: FighterPartLayout | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Return endpoints/radius/metadata in fighter-local source coordinates."""

    matrices = evaluate_joint_matrices(joints, animation, frame)
    return tuple(
        (
            *_transform(
                matrices[
                    capsule.bone_index
                    if part_layout is None
                    else part_layout.source_joint_by_runtime_part[
                        capsule.bone_index
                    ]
                ],
                capsule.offset_a,
            ),
            *_transform(
                matrices[
                    capsule.bone_index
                    if part_layout is None
                    else part_layout.source_joint_by_runtime_part[
                        capsule.bone_index
                    ]
                ],
                capsule.offset_b,
            ),
            capsule.radius,
            capsule.height,
            capsule.grabbable,
        )
        for capsule in capsules
    )
