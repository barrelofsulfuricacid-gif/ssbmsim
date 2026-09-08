#!/usr/bin/env python3
"""Capture a bounded collision-state window from headless Slippi Dolphin."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


MATCH_INFO = 0x8046B6A0
STATIC_PLAYERS = 0x80453080
GOBJ_ENTITIES = 0x804D782C
STATIC_PLAYER_STRIDE = 0xE90
MEM1_START = 0x80000000
MEM1_END = 0x81800000
FTCOLL_DAMAGE_ENTRY = 0x80076ED8
FTCOLL_CAPTURE_SCRATCH = 0x817F0000
FTCOLL_CAPTURE_TRAMPOLINE = 0x801DCCFC
FTCOLL_DAMAGE_ENTRY_ORIGINAL = bytes.fromhex(
    "7c0802a6 90010004 9421ff68 dbe10090 dbc10088 bee10064"
)
FTCOLL_DAMAGE_ENTRY_CAPTURE = bytes.fromhex("48165e24")
FTCOLL_CAPTURE_TRAMPOLINE_ORIGINAL = bytes.fromhex(
    "7c0802a6 3c60803e 90010004 38631d38 38000000 9421ffc0 "
    "93e1003c 93c10038 90030030 9003003c 90030048 90030034 "
    "90030040 9003004c 90030038 90030044 90030050 48048455"
)
LB_COPY_ENTRY = 0x8000C490
LB_COPY_ENTRY_ORIGINAL = bytes.fromhex(
    "7c0802a6 90010004 9421ff70 dbe10088 ffe01090 bf610074"
)
LB_COPY_CAPTURE_TRAMPOLINE_SIZE = 0x120
LB_COPY_CAPTURE_TRAMPOLINE_SHA256 = (
    "79bb82eefc5ea70c605c64a5a79f95d09dcab8bca98747cf57f80314f77da9f5"
)
LB_COPY_CAPTURE_RECORD_SIZE = 0x40
LB_COPY_CAPTURE_RECORDS_OFFSET = 0x20
LB_COPY_CAPTURE_MAX_RECORDS = 8
LB_COPY_CAPTURE_SCRATCH_SIZE = (
    LB_COPY_CAPTURE_RECORDS_OFFSET
    + LB_COPY_CAPTURE_MAX_RECORDS * LB_COPY_CAPTURE_RECORD_SIZE
)


def encode_ppc_branch(source: int, target: int) -> int:
    delta = target - source
    if delta % 4 != 0 or not -0x2000000 <= delta <= 0x1FFFFFC:
        raise ValueError(
            f"PowerPC branch out of range: 0x{source:08x} -> 0x{target:08x}"
        )
    return 0x48000000 | (delta & 0x03FFFFFC)


def encode_ppc_conditional_branch(source: int, target: int, opcode: int) -> int:
    delta = target - source
    if delta % 4 != 0 or not -0x8000 <= delta <= 0x7FFC:
        raise ValueError(
            "PowerPC conditional branch out of range: "
            f"0x{source:08x} -> 0x{target:08x}"
        )
    return opcode | (delta & 0xFFFC)


def build_lb_copy_capture_trampoline(
    frame_count: int,
    player_slot: int,
    part_index: int,
    freeze_after_calls: int = LB_COPY_CAPTURE_MAX_RECORDS,
) -> bytes:
    if not 0 <= frame_count <= 0x7FFF:
        raise ValueError("lb_8000C490 capture frame exceeds signed immediate")
    if not 0 <= player_slot < 6:
        raise ValueError("lb_8000C490 capture player slot must be in [0, 5]")
    if not 0 <= part_index <= 0x7FF:
        raise ValueError("lb_8000C490 capture part index exceeds signed offset")
    if not 1 <= freeze_after_calls <= LB_COPY_CAPTURE_MAX_RECORDS:
        raise ValueError(
            "lb_8000C490 freeze call count must be within capture capacity"
        )

    static_player = STATIC_PLAYERS + player_slot * STATIC_PLAYER_STRIDE
    static_player_ha = ((static_player + 0x8000) >> 16) & 0xFFFF
    static_player_lo = static_player & 0xFFFF
    part_offset = part_index * 0x10
    words = [
        0x3CE08047,  # lis r7, 0x8047
        0x80E7B6C4,  # lwz r7, -0x493c(r7): MatchInfo.frame_count
        0x3D00817F,  # lis r8, 0x817f: capture scratch
        0x2C070000 | frame_count,  # cmpwi r7, frame_count
        0,  # blt resume
        0,  # beq target
        0x80C80000,  # lwz r6, 0(r8): captured call count
        0x2C060000,  # cmpwi r6, 0
        0,  # beq resume
        0x38C00001,  # li r6, 1
        0x90C8000C,  # stw r6, 12(r8): stopped after target frame
        0,  # stop: b stop
        0x3D200000 | static_player_ha,  # target: lis r9, player@ha
        0x39290000 | static_player_lo,  # addi r9, r9, player@l
        0x8949000C,  # lbz r10, 12(r9): transformed fighter index
        0x554A103A,  # slwi r10, r10, 2
        0x396900B0,  # addi r11, r9, 0xb0: fighter GObj array
        0x7D4B502E,  # lwzx r10, r11, r10
        0x814A002C,  # lwz r10, 0x2c(r10): Fighter
        0x816A05E8,  # lwz r11, 0x5e8(r10): Fighter parts; retain Fighter
        0x816B0000 | part_offset,  # lwz r11, part_offset(r11): joint
        0x7C055800,  # cmpw r5, r11: output must be selected part joint
        0,  # bne resume
        0x80E80000,  # lwz r7, 0(r8): capture count
        0x2C070000 | LB_COPY_CAPTURE_MAX_RECORDS,
        0,  # bge overflow
        0x54E63032,  # slwi r6, r7, 6: record index * 0x40
        0x7CC83214,  # add r6, r8, r6
        0x38C60020,  # addi r6, r6, 0x20: record base
        0x90660000,  # stw r3, 0(r6): interpolation target
        0x90860004,  # stw r4, 4(r6): current joint
        0x81610000,  # lwz r11, 0(r1): ftAnim_8006FE9C caller stack
        0x816B0000,  # lwz r11, 0(r11): ftAnim_8006E9B4 caller stack
        0x816B0004,  # lwz r11, 4(r11): ftAnim_8006E9B4 return address
        0x91660008,  # stw r11, 8(r6)
        0x81640014,  # lwz r11, 0x14(r4): current flags
        0x91660010,
        0x816A0010,  # lwz r11, 0x10(r10): motion/action state at this call
        0x9166000C,  # stw r11, 0xc(r6); retain r7 capture count
        0xC0030020,  # target rotation y
        0xD0060018,
        0xC0030024,  # target rotation z
        0xD006001C,
        0xC0030028,  # target rotation w
        0xD0060020,
        0xC004001C,  # current rotation x
        0xD0060024,
        0xC0040020,  # current rotation y
        0xD0060028,
        0xC0040024,  # current rotation z
        0xD006002C,
        0xC0040028,  # current rotation w
        0xD0060030,
        0xD0260034,  # stfs f1, 0x34(r6): target weight
        0xD0460038,  # stfs f2, 0x38(r6): current weight
        0x38E70001,  # addi r7, r7, 1
        0x90E80000,  # stw r7, 0(r8)
        0x2C070000 | freeze_after_calls,  # cmpwi r7, freeze_after_calls
        0,  # blt resume
        0x38C00001,  # li r6, 1
        0x90C8000C,  # stw r6, 0xc(r8): stopped at requested count
        0,  # b stop
        0x38C00001,  # overflow: li r6, 1
        0x90C80010,  # stw r6, 0x10(r8): overflow
        0,  # b stop
        0x7C0802A6,  # resume: original lb_8000C490 prologue
        0x90010004,
        0x9421FF70,
        0xDBE10088,
        0xFFE01090,
        0xBF610074,
        0,  # b LB_COPY_ENTRY + len(original prologue)
    ]

    def address(index: int) -> int:
        return FTCOLL_CAPTURE_TRAMPOLINE + index * 4

    resume = 65
    target = 12
    overflow = 62
    stop = 11
    words[4] = encode_ppc_conditional_branch(
        address(4), address(resume), 0x41800000
    )
    words[5] = encode_ppc_conditional_branch(
        address(5), address(target), 0x41820000
    )
    words[8] = encode_ppc_conditional_branch(
        address(8), address(resume), 0x41820000
    )
    words[11] = encode_ppc_branch(address(stop), address(stop))
    words[22] = encode_ppc_conditional_branch(
        address(22), address(resume), 0x40820000
    )
    words[25] = encode_ppc_conditional_branch(
        address(25), address(overflow), 0x40800000
    )
    words[58] = encode_ppc_conditional_branch(
        address(58), address(resume), 0x41800000
    )
    words[61] = encode_ppc_branch(address(61), address(stop))
    words[64] = encode_ppc_branch(address(64), address(stop))
    words[71] = encode_ppc_branch(
        address(71), LB_COPY_ENTRY + len(LB_COPY_ENTRY_ORIGINAL)
    )
    result = b"".join(struct.pack(">I", word) for word in words)
    if len(result) != LB_COPY_CAPTURE_TRAMPOLINE_SIZE:
        raise AssertionError("lb_8000C490 capture trampoline size changed")
    return result


def build_ftcoll_capture_trampoline(frame_count: int) -> bytes:
    if not 0 <= frame_count <= 0x7FFF:
        raise ValueError("ftColl capture frame counter exceeds signed immediate")
    words = [
        0x3CE08047,  # lis r7, 0x8047
        0x80E7B6C4,  # lwz r7, -0x493c(r7): MatchInfo.frame_count
        0x3D00817F,  # lis r8, 0x817f
        0x90E80010,  # stw r7, 0x10(r8): last collision frame
        0x2C070000 | frame_count,  # cmpwi r7, frame_count
        0x40800020,  # bge capture
        0x7C0802A6,  # original ftColl_80076ED8 prologue
        0x90010004,
        0x9421FF68,
        0xDBE10090,
        0xDBC10088,
        0xBEE10064,
        0x4BE9A1C4,  # b 0x80076ef0
        0x90680000,  # capture: stw r3, 0(r8)
        0x90880004,  # stw r4, 4(r8)
        0x90A80008,  # stw r5, 8(r8)
        0x90C8000C,  # stw r6, 12(r8)
        0x48000000,  # b .
    ]
    return b"".join(struct.pack(">I", word) for word in words)


class Snapshot:
    def __init__(self, base: int, data: bytes) -> None:
        self.base = base
        self.data = data

    @classmethod
    def read(cls, dme: Any, base: int, size: int) -> Snapshot:
        return cls(base, bytes(dme.read_bytes(base, size)))

    def _offset(self, address: int, size: int) -> int:
        offset = address - self.base
        if offset < 0 or offset + size > len(self.data):
            raise ValueError(f"snapshot read outside 0x{self.base:08x}")
        return offset

    def u8(self, address: int) -> int:
        return self.data[self._offset(address, 1)]

    def u32(self, address: int) -> int:
        return struct.unpack_from(">I", self.data, self._offset(address, 4))[0]

    def u16(self, address: int) -> int:
        return struct.unpack_from(">H", self.data, self._offset(address, 2))[0]

    def i32(self, address: int) -> int:
        return struct.unpack_from(">i", self.data, self._offset(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack_from(">f", self.data, self._offset(address, 4))[0]

    def vec3(self, address: int) -> list[float]:
        return list(
            struct.unpack_from(">3f", self.data, self._offset(address, 12))
        )

    def hex_bytes(self, address: int, size: int) -> str:
        offset = self._offset(address, size)
        return self.data[offset : offset + size].hex()


def require_pointer(value: int, label: str) -> int:
    if not MEM1_START <= value < MEM1_END:
        raise RuntimeError(f"invalid {label} MEM1 pointer: 0x{value:08x}")
    return value


def read_fighter_address(dme: Any, player_index: int) -> int:
    slot = STATIC_PLAYERS + player_index * STATIC_PLAYER_STRIDE
    player = Snapshot.read(dme, slot, 0xC0)
    transformed = player.u8(slot + 0x0C)
    gobj = require_pointer(
        player.u32(slot + 0xB0 + transformed * 4), "fighter GObj"
    )
    return require_pointer(int(dme.read_word(gobj + 0x2C)), "fighter data")


def discover_active_player_slots(dme: Any) -> list[int]:
    slots: list[int] = []
    for player_index in range(6):
        try:
            read_fighter_address(dme, player_index)
        except RuntimeError:
            continue
        slots.append(player_index)
    if not slots:
        raise RuntimeError("no active static-player fighter slots found")
    return slots


def read_stale_table(dme: Any, player_index: int) -> dict[str, object]:
    base = STATIC_PLAYERS + player_index * STATIC_PLAYER_STRIDE + 0xBC
    snapshot = Snapshot.read(dme, base, 0x2C)
    return {
        "current_index": snapshot.u32(base),
        "entries": [
            {
                "move_id": snapshot.u16(base + 4 + index * 4),
                "attack_instance": snapshot.u16(base + 6 + index * 4),
            }
            for index in range(10)
        ],
    }


def read_matrix(dme: Any, jobj: int) -> list[float] | None:
    if not MEM1_START <= jobj < MEM1_END:
        return None
    matrix = Snapshot.read(dme, jobj + 0x44, 48)
    return [matrix.f32(jobj + 0x44 + index * 4) for index in range(12)]


def read_joint_ancestry(dme: Any, jobj: int) -> list[dict[str, object]]:
    ancestry: list[dict[str, object]] = []
    seen: set[int] = set()
    while jobj:
        require_pointer(jobj, "HSD_JObj ancestry")
        if jobj in seen:
            raise RuntimeError(f"cyclic HSD_JObj ancestry at 0x{jobj:08x}")
        if len(ancestry) >= 128:
            raise RuntimeError("HSD_JObj ancestry exceeds expected bound")
        seen.add(jobj)
        snapshot = Snapshot.read(dme, jobj, 0x88)
        ancestry.append(
            {
                "address": f"0x{jobj:08x}",
                "flags": snapshot.u32(jobj + 0x14),
                "quaternion": [
                    snapshot.f32(jobj + 0x1C + component * 4)
                    for component in range(4)
                ],
                "scale": snapshot.vec3(jobj + 0x2C),
                "translation": snapshot.vec3(jobj + 0x38),
                "matrix": read_matrix(dme, jobj),
            }
        )
        jobj = snapshot.u32(jobj + 0x0C)
    return ancestry


def read_root_parts(dme: Any, fighter: int, snapshot: Snapshot) -> list[dict[str, object]]:
    parts = require_pointer(snapshot.u32(fighter + 0x5E8), "fighter parts")
    result: list[dict[str, object]] = []
    for index in range(4):
        part = Snapshot.read(dme, parts + index * 0x10, 0x10)
        joint = require_pointer(part.u32(parts + index * 0x10), "fighter part joint")
        interpolation_joint = require_pointer(
            part.u32(parts + index * 0x10 + 4),
            "fighter part interpolation joint",
        )
        result.append(
            {
                "index": index,
                "flags8": part.u16(parts + index * 0x10 + 8),
                "flagsC": part.u32(parts + index * 0x10 + 0xC),
                "joint": read_joint_ancestry(dme, joint)[0],
                "interpolation_joint": read_joint_ancestry(
                    dme, interpolation_joint
                )[0],
            }
        )
    return result


def transform_point(matrix: list[float], value: list[float]) -> list[float]:
    return [
        matrix[row * 4] * value[0]
        + matrix[row * 4 + 1] * value[1]
        + matrix[row * 4 + 2] * value[2]
        + matrix[row * 4 + 3]
        for row in range(3)
    ]


def read_hurtboxes(
    dme: Any, fighter: int, snapshot: Snapshot
) -> list[dict[str, object]]:
    hurtbox_count = snapshot.u8(fighter + 0x119E)
    if hurtbox_count > 15:
        raise RuntimeError(f"invalid Fighter hurt-capsule count: {hurtbox_count}")
    bone_matrices: dict[int, list[float]] = {}
    hurtboxes: list[dict[str, object]] = []
    parts = require_pointer(snapshot.u32(fighter + 0x5E8), "fighter parts")
    for index in range(hurtbox_count):
        hurtbox = fighter + 0x11A0 + index * 0x4C
        bone = snapshot.u32(hurtbox + 0x20)
        bone_index = snapshot.u32(hurtbox + 0x40)
        part = Snapshot.read(dme, parts + bone_index * 0x10, 0x10)
        offset_a = snapshot.vec3(hurtbox + 0x04)
        offset_b = snapshot.vec3(hurtbox + 0x10)
        matrix = bone_matrices.get(bone)
        if matrix is None:
            matrix = read_matrix(dme, bone)
            if matrix is None:
                raise RuntimeError(f"invalid hurtbox bone pointer: 0x{bone:08x}")
            bone_matrices[bone] = matrix
        bone_snapshot = Snapshot.read(dme, bone, 0x88)
        hurtboxes.append(
            {
                "index": index,
                "state": snapshot.u32(hurtbox),
                "state_bytes": snapshot.hex_bytes(hurtbox, 4),
                "radius": snapshot.f32(hurtbox + 0x1C),
                "bone": f"0x{bone:08x}",
                "part_joint": f"0x{part.u32(parts + bone_index * 0x10):08x}",
                "part_interpolation_joint": (
                    f"0x{part.u32(parts + bone_index * 0x10 + 4):08x}"
                ),
                "bone_state": {
                    "flags": bone_snapshot.u32(bone + 0x14),
                    "quaternion": [
                        bone_snapshot.f32(bone + 0x1C + component * 4)
                        for component in range(4)
                    ],
                    "scale": bone_snapshot.vec3(bone + 0x2C),
                    "translation": bone_snapshot.vec3(bone + 0x38),
                    "matrix": matrix,
                },
                "offset_a": offset_a,
                "offset_b": offset_b,
                "transformed_position_a": transform_point(matrix, offset_a),
                "transformed_position_b": transform_point(matrix, offset_b),
                "collision_position_a": snapshot.vec3(hurtbox + 0x28),
                "collision_position_b": snapshot.vec3(hurtbox + 0x34),
                "bone_index": bone_index,
                "height": snapshot.u32(hurtbox + 0x44),
                "grabbable": snapshot.u32(hurtbox + 0x48),
            }
        )
    return hurtboxes


def read_cpu_ring_entry(dme: Any, address: int) -> dict[str, object] | None:
    if not MEM1_START <= address < MEM1_END:
        return None
    entry = Snapshot.read(dme, address, 0x1C)
    return {
        "address": f"0x{address:08x}",
        "held_inputs": entry.u32(address),
        "lstick_x": struct.unpack("b", bytes([entry.u8(address + 4)]))[0],
        "lstick_y": struct.unpack("b", bytes([entry.u8(address + 5)]))[0],
        "cstick_x": struct.unpack("b", bytes([entry.u8(address + 6)]))[0],
        "cstick_y": struct.unpack("b", bytes([entry.u8(address + 7)]))[0],
        "position": entry.vec3(address + 0x0C),
        "facing": entry.f32(address + 0x18),
    }


def read_fighter(dme: Any, player_index: int) -> dict[str, object]:
    fighter = read_fighter_address(dme, player_index)
    snapshot = Snapshot.read(dme, fighter, 0x2350)
    hitboxes: list[dict[str, object]] = []
    for index in range(4):
        hitbox = fighter + 0x914 + index * 0x138
        jobj = snapshot.u32(hitbox + 0x48)
        hitboxes.append(
            {
                "index": index,
                "state": snapshot.u32(hitbox),
                "hit_id": snapshot.u32(hitbox + 0x04),
                "damage_count": snapshot.u32(hitbox + 0x08),
                "damage": snapshot.f32(hitbox + 0x0C),
                "bone_offset": snapshot.vec3(hitbox + 0x10),
                "radius": snapshot.f32(hitbox + 0x1C),
                "angle": snapshot.u32(hitbox + 0x20),
                "knockback_growth": snapshot.u32(hitbox + 0x24),
                "weight_set_knockback": snapshot.u32(hitbox + 0x28),
                "base_knockback": snapshot.u32(hitbox + 0x2C),
                "element": snapshot.u32(hitbox + 0x30),
                "shield_damage": snapshot.i32(hitbox + 0x34),
                "victims_1_count": snapshot.u8(hitbox + 0x44),
                "victims_2_count": snapshot.u8(hitbox + 0x45),
                "flags_40_47": snapshot.hex_bytes(hitbox + 0x40, 8),
                "joint": f"0x{jobj:08x}",
                "joint_matrix": read_matrix(dme, jobj),
                "position": snapshot.vec3(hitbox + 0x4C),
                "previous_position": snapshot.vec3(hitbox + 0x58),
                "hurt_collision_position": snapshot.vec3(hitbox + 0x64),
                "collision_distance": snapshot.f32(hitbox + 0x70),
            }
        )
    shield_joint = snapshot.u32(fighter + 0x19C0)
    return {
        "address": f"0x{fighter:08x}",
        "fighter_kind": snapshot.u32(fighter + 0x04),
        "player_slot": snapshot.u8(fighter + 0x0C),
        "action_state": snapshot.u32(fighter + 0x10),
        "animation_id": snapshot.u32(fighter + 0x14),
        "facing": snapshot.f32(fighter + 0x2C),
        "scale": snapshot.vec3(fighter + 0x34),
        "animation_velocity": snapshot.vec3(fighter + 0x74),
        "self_velocity": snapshot.vec3(fighter + 0x80),
        "knockback_velocity": snapshot.vec3(fighter + 0x8C),
        "attack_shield_knockback_velocity": snapshot.vec3(fighter + 0x98),
        "position": snapshot.vec3(fighter + 0xB0),
        "ground_velocity": snapshot.f32(fighter + 0xEC),
        "player_nudge_velocity": [
            snapshot.f32(fighter + 0xF8),
            snapshot.f32(fighter + 0xFC),
        ],
        "floor": {
            "index": snapshot.i32(fighter + 0x83C),
            "flags": snapshot.u32(fighter + 0x840),
            "normal": snapshot.vec3(fighter + 0x844),
        },
        "animation_frame": snapshot.f32(fighter + 0x894),
        "animation_rate": snapshot.f32(fighter + 0x89C),
        "animation_blend_frames": snapshot.f32(fighter + 0x8A4),
        "animation_blend_frame": snapshot.f32(fighter + 0x8A8),
        "animation_flags_594_597": snapshot.hex_bytes(fighter + 0x594, 4),
        "root_parts": read_root_parts(dme, fighter, snapshot),
        "hitboxes": hitboxes,
        "hurtboxes": read_hurtboxes(dme, fighter, snapshot),
        "shield": {
            "health": snapshot.f32(fighter + 0x1998),
            "lightshield_amount": snapshot.f32(fighter + 0x199C),
            "damage_taken": snapshot.i32(fighter + 0x19A0),
            "maximum_damage": snapshot.i32(fighter + 0x19A4),
            "joint": f"0x{shield_joint:08x}",
            "flags_19c4_19c7": snapshot.hex_bytes(fighter + 0x19C4, 4),
            "position": snapshot.vec3(fighter + 0x19C8),
            "offset": snapshot.vec3(fighter + 0x19D4),
            "radius": snapshot.f32(fighter + 0x19E0),
            "joint_matrix": read_matrix(dme, shield_joint),
        },
    }


def read_fighter_list(dme: Any) -> list[dict[str, object]]:
    entities = require_pointer(int(dme.read_word(GOBJ_ENTITIES)), "GObj list")
    gobj = int(dme.read_word(entities + 0x20))
    fighters: list[dict[str, object]] = []
    while gobj:
        require_pointer(gobj, "fighter-list GObj")
        gobj_snapshot = Snapshot.read(dme, gobj, 0x30)
        fighter = require_pointer(gobj_snapshot.u32(gobj + 0x2C), "fighter data")
        snapshot = Snapshot.read(dme, fighter, 0x2350)
        cpu_ring_write = snapshot.u32(fighter + 0x1ECC)
        cpu_ring_read = snapshot.u32(fighter + 0x1ED0)
        cpu_script = snapshot.u32(fighter + 0x1ED8)
        cpu_script_write = snapshot.u32(fighter + 0x1FDC)
        fighters.append(
            {
                "gobj": f"0x{gobj:08x}",
                "fighter": f"0x{fighter:08x}",
                "kind": snapshot.u32(fighter + 0x04),
                "player_slot": snapshot.u8(fighter + 0x0C),
                "action_state": snapshot.u32(fighter + 0x10),
                "animation_velocity": snapshot.vec3(fighter + 0x74),
                "self_velocity": snapshot.vec3(fighter + 0x80),
                "knockback_velocity": snapshot.vec3(fighter + 0x8C),
                "attack_shield_knockback_velocity": snapshot.vec3(
                    fighter + 0x98
                ),
                "position": snapshot.vec3(fighter + 0xB0),
                "previous_position": snapshot.vec3(fighter + 0xBC),
                "position_delta": snapshot.vec3(fighter + 0xC8),
                "ground_velocity": snapshot.f32(fighter + 0xEC),
                "player_nudge_velocity": [
                    snapshot.f32(fighter + 0xF8),
                    snapshot.f32(fighter + 0xFC),
                ],
                "floor": {
                    "index": snapshot.i32(fighter + 0x83C),
                    "flags": snapshot.u32(fighter + 0x840),
                    "normal": snapshot.vec3(fighter + 0x844),
                },
                "input": {
                    "lstick": [
                        snapshot.f32(fighter + 0x620),
                        snapshot.f32(fighter + 0x624),
                    ],
                    "previous_lstick": [
                        snapshot.f32(fighter + 0x628),
                        snapshot.f32(fighter + 0x62C),
                    ],
                    "timers": list(snapshot.data[0x670:0x675]),
                },
                "damage": snapshot.f32(fighter + 0x1830),
                "hitlag": snapshot.f32(fighter + 0x195C),
                "cpu_input_bytes": snapshot.hex_bytes(fighter + 0x1A88, 10),
                "cpu_flags": snapshot.hex_bytes(fighter + 0x1B80, 4),
                "cpu_destination": [
                    snapshot.f32(fighter + 0x1ADC),
                    snapshot.f32(fighter + 0x1AE0),
                ],
                "cpu_mode": snapshot.u32(fighter + 0x1A94),
                "cpu_level": snapshot.u32(fighter + 0x1A98),
                "cpu_behavior": snapshot.u32(fighter + 0x1AA0),
                "cpu_previous_behavior": snapshot.u32(fighter + 0x1AA4),
                "cpu_fallback_behavior": snapshot.u32(fighter + 0x1AA8),
                "cpu_frame": snapshot.u32(fighter + 0x1B04),
                "cpu_script": {
                    "duration": snapshot.u32(fighter + 0x1ED4),
                    "read": (
                        f"0x{cpu_script:08x}"
                        if MEM1_START <= cpu_script < MEM1_END
                        else None
                    ),
                    "write": (
                        f"0x{cpu_script_write:08x}"
                        if MEM1_START <= cpu_script_write < MEM1_END
                        else None
                    ),
                    "buffer": snapshot.hex_bytes(fighter + 0x1EDC, 0x100),
                },
                "cpu_ring_write": read_cpu_ring_entry(dme, cpu_ring_write),
                "cpu_ring_read": read_cpu_ring_entry(dme, cpu_ring_read),
                "attack_id": snapshot.i32(fighter + 0x2068),
                "attack_instance": snapshot.u16(fighter + 0x206C),
                "flags_221a_221f": snapshot.hex_bytes(fighter + 0x221A, 6),
            }
        )
        if len(fighters) > 8:
            raise RuntimeError("fighter GObj list exceeds expected bound")
        gobj = gobj_snapshot.u32(gobj + 0x08)
    return fighters


def read_frozen_collision_call(
    dme: Any, frame_count: int
) -> dict[str, object] | None:
    scratch = Snapshot.read(dme, FTCOLL_CAPTURE_SCRATCH, 0x14)
    attacker = scratch.u32(FTCOLL_CAPTURE_SCRATCH)
    if not MEM1_START <= attacker < MEM1_END:
        return None
    hit = require_pointer(
        scratch.u32(FTCOLL_CAPTURE_SCRATCH + 4), "captured hitbox"
    )
    victim = require_pointer(
        scratch.u32(FTCOLL_CAPTURE_SCRATCH + 8), "captured victim"
    )
    hurt = require_pointer(
        scratch.u32(FTCOLL_CAPTURE_SCRATCH + 12), "captured hurtbox"
    )
    attacker_snapshot = Snapshot.read(dme, attacker, 0x2350)
    victim_snapshot = Snapshot.read(dme, victim, 0x2350)
    attacker_slot = attacker_snapshot.u8(attacker + 0x0C)
    victim_slot = victim_snapshot.u8(victim + 0x0C)
    hit_delta = hit - (attacker + 0x914)
    hurt_delta = hurt - (victim + 0x11A0)
    if hit_delta < 0 or hit_delta % 0x138 != 0 or hit_delta // 0x138 >= 4:
        raise RuntimeError(f"captured hitbox is outside Fighter: 0x{hit:08x}")
    hurtbox_count = victim_snapshot.u8(victim + 0x119E)
    if (
        hurt_delta < 0
        or hurt_delta % 0x4C != 0
        or hurt_delta // 0x4C >= hurtbox_count
    ):
        raise RuntimeError(f"captured hurtbox is outside Fighter: 0x{hurt:08x}")
    slots = discover_active_player_slots(dme)
    captured_frame_count = scratch.u32(FTCOLL_CAPTURE_SCRATCH + 0x10)
    hit_snapshot = Snapshot.read(dme, hit, 0x4C)
    hurt_snapshot = Snapshot.read(dme, hurt, 0x24)
    return {
        "frame_count": captured_frame_count,
        "poll_frame_count": frame_count,
        "slippi_frame": captured_frame_count,
        "attacker": f"0x{attacker:08x}",
        "attacker_slot": attacker_slot,
        "hitbox": f"0x{hit:08x}",
        "hitbox_index": hit_delta // 0x138,
        "victim": f"0x{victim:08x}",
        "victim_slot": victim_slot,
        "hurtbox": f"0x{hurt:08x}",
        "hurtbox_index": hurt_delta // 0x4C,
        "selected_hit_joint_ancestry": read_joint_ancestry(
            dme, hit_snapshot.u32(hit + 0x48)
        ),
        "selected_hurt_joint_ancestry": read_joint_ancestry(
            dme, hurt_snapshot.u32(hurt + 0x20)
        ),
        "player_slots": slots,
        "fighters": [read_fighter(dme, slot) for slot in slots],
        "fighter_list": read_fighter_list(dme),
        "stale_tables": [read_stale_table(dme, slot) for slot in slots],
    }


def read_frozen_lb_copy_calls(
    dme: Any,
    frame_count: int,
    capture_frame: int,
    player_slot: int,
    part_index: int,
) -> dict[str, object] | None:
    scratch = Snapshot.read(
        dme, FTCOLL_CAPTURE_SCRATCH, LB_COPY_CAPTURE_SCRATCH_SIZE
    )
    stopped = scratch.u32(FTCOLL_CAPTURE_SCRATCH + 0x0C)
    overflow = scratch.u32(FTCOLL_CAPTURE_SCRATCH + 0x10)
    count = scratch.u32(FTCOLL_CAPTURE_SCRATCH)
    if overflow:
        raise RuntimeError("lb_8000C490 capture record capacity exceeded")
    if count > LB_COPY_CAPTURE_MAX_RECORDS:
        raise RuntimeError(f"invalid lb_8000C490 capture count: {count}")
    if not stopped:
        return None

    calls: list[dict[str, object]] = []
    for index in range(count):
        record = (
            FTCOLL_CAPTURE_SCRATCH
            + LB_COPY_CAPTURE_RECORDS_OFFSET
            + index * LB_COPY_CAPTURE_RECORD_SIZE
        )
        calls.append(
            {
                "index": index,
                "target_joint": f"0x{scratch.u32(record):08x}",
                "current_joint": f"0x{scratch.u32(record + 4):08x}",
                "output_joint": f"0x{scratch.u32(record + 4):08x}",
                "animation_driver_return_address": (
                    f"0x{scratch.u32(record + 8):08x}"
                ),
                "action_state": scratch.u32(record + 0x0C),
                "current_flags": scratch.u32(record + 0x10),
                "target_rotation": [
                    0.0,
                    *[
                        scratch.f32(record + 0x18 + component * 4)
                        for component in range(3)
                    ],
                ],
                "current_rotation": [
                    scratch.f32(record + 0x24 + component * 4)
                    for component in range(4)
                ],
                "target_weight": scratch.f32(record + 0x34),
                "current_weight": scratch.f32(record + 0x38),
            }
        )

    slots = discover_active_player_slots(dme)
    target_fighter = read_fighter_address(dme, player_slot)
    fighter_snapshot = Snapshot.read(dme, target_fighter, 0x2350)
    return {
        "capture_count": count,
        "capture_frame": capture_frame,
        "poll_frame_count": frame_count,
        "player_slot": player_slot,
        "part_index": part_index,
        "calls": calls,
        "target_root_parts": read_root_parts(
            dme, target_fighter, fighter_snapshot
        ),
        "player_slots": slots,
        "fighters": [read_fighter(dme, slot) for slot in slots],
        "fighter_list": read_fighter_list(dme),
        "stale_tables": [read_stale_table(dme, slot) for slot in slots],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dme-site", type=Path, required=True)
    parser.add_argument("--dolphin", type=Path, required=True)
    parser.add_argument("--user", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first-frame", type=int, required=True)
    parser.add_argument("--last-frame", type=int, required=True)
    parser.add_argument("--emulation-speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=45.0)
    capture_group = parser.add_mutually_exclusive_group()
    capture_group.add_argument(
        "--freeze-ftcoll-frame",
        type=int,
        help=(
            "install a validated ftColl_80076ED8 argument-capture trampoline "
            "in the temporary oracle and snapshot the first collision call at "
            "or after this frame"
        ),
    )
    capture_group.add_argument(
        "--freeze-lb-copy-frame",
        type=int,
        help=(
            "capture every lb_8000C490 call that writes the selected fighter "
            "part on this frame, then freeze at the next blend call"
        ),
    )
    parser.add_argument(
        "--lb-copy-player-slot",
        type=int,
        default=2,
        help="static-player slot filtered by --freeze-lb-copy-frame",
    )
    parser.add_argument(
        "--lb-copy-part-index",
        type=int,
        default=2,
        help="Fighter parts index filtered by --freeze-lb-copy-frame",
    )
    parser.add_argument(
        "--lb-copy-freeze-after-calls",
        type=int,
        default=LB_COPY_CAPTURE_MAX_RECORDS,
        help=(
            "freeze after this many selected lb_8000C490 calls; use the "
            "capture capacity when the call count is unknown"
        ),
    )
    return parser.parse_args()


def read_polled_sample(dme: Any, counter: int) -> dict[str, object] | None:
    """Reject counter changes across *all* reads, including trailing tables.

    A stable counter does not prove a finalized frame: the game can mutate
    state inside that counter epoch. Only an instrumented boundary can do so.
    """
    if int(dme.read_word(MATCH_INFO + 0x24)) != counter:
        return None
    player_slots = discover_active_player_slots(dme)
    sample = {
        "frame_count": counter,
        "slippi_frame": counter - 1,
        "player_slots": player_slots,
        "fighters": [read_fighter(dme, index) for index in player_slots],
        "fighter_list": read_fighter_list(dme),
        "stale_tables": [read_stale_table(dme, index) for index in player_slots],
    }
    return sample if int(dme.read_word(MATCH_INFO + 0x24)) == counter else None


def main() -> None:
    args = parse_args()
    if args.first_frame > args.last_frame:
        raise ValueError("first frame must not exceed last frame")
    for label, capture_frame in (
        ("ftColl", args.freeze_ftcoll_frame),
        ("lb_8000C490", args.freeze_lb_copy_frame),
    ):
        if (
            capture_frame is not None
            and not args.first_frame <= capture_frame <= args.last_frame
        ):
            raise ValueError(
                f"frozen {label} frame must be inside the requested window"
            )
    if args.freeze_lb_copy_frame is not None:
        build_lb_copy_capture_trampoline(
            args.freeze_lb_copy_frame,
            args.lb_copy_player_slot,
            args.lb_copy_part_index,
            args.lb_copy_freeze_after_calls,
        )
    if args.dolphin.name != "dolphin-emu-nogui":
        raise RuntimeError("refusing to launch a non-NoGUI oracle")
    for required in (args.dme_site, args.dolphin, args.user, args.replay, args.iso):
        if not required.exists():
            raise FileNotFoundError(required)

    sys.path.insert(0, str(args.dme_site))
    dme = importlib.import_module("dolphin_memory_engine")
    for variable in ("DISPLAY", "WAYLAND_DISPLAY"):
        os.environ.pop(variable, None)

    temporary_user = Path(tempfile.mkdtemp(prefix="pf-headless-collision-"))
    process: subprocess.Popen[bytes] | None = None
    log_path = args.output.with_suffix(args.output.suffix + ".log")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("wb")
    try:
        shutil.copytree(args.user, temporary_user, dirs_exist_ok=True)
        # DME discovers the process by Dolphin's historical executable name.
        # The symlink target was already required to be the NoGUI binary.
        launcher = temporary_user / "dolphin-emu"
        launcher.symlink_to(args.dolphin.resolve())
        playback = temporary_user / "playback.json"
        playback.write_text(
            json.dumps(
                {
                    "mode": "normal",
                    "replay": str(args.replay.resolve()),
                    "startFrame": -123,
                    "endFrame": args.last_frame
                    + (60 if args.freeze_lb_copy_frame is not None else 2),
                    "commandId": "native-collision-probe",
                    "isRealTimeMode": False,
                    "shouldResync": True,
                    "rollbackDisplayMethod": "off",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        ini = temporary_user / "Config/Dolphin.ini"
        ini_text = ini.read_text(encoding="utf-8")
        ini_text, replacements = re.subn(
            r"(?m)^EmulationSpeed = .*$",
            f"EmulationSpeed = {args.emulation_speed:.8f}",
            ini_text,
        )
        if replacements != 1:
            raise RuntimeError("expected one Dolphin EmulationSpeed setting")
        ini_text = re.sub(r"(?m)^LoopReplay = .*$", "LoopReplay = False", ini_text)
        ini.write_text(ini_text, encoding="utf-8", newline="\n")

        process = subprocess.Popen(
            [
                str(launcher),
                "-c",
                "-u",
                str(temporary_user),
                "-i",
                str(playback),
                "-e",
                str(args.iso),
            ],
            cwd=args.output.parent,
            env=os.environ.copy(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and not dme.is_hooked():
            dme.hook()
            if not dme.is_hooked():
                if process.poll() is not None:
                    raise RuntimeError(f"Dolphin exited during boot: {process.returncode}")
                time.sleep(0.02)
        if not dme.is_hooked():
            raise RuntimeError(f"DME hook failed: {dme.get_status()}")

        capture_trampoline: bytes | None = None
        capture_patch_installed = False
        lb_copy_trampoline: bytes | None = None
        lb_copy_patch_installed = False
        if args.freeze_ftcoll_frame is not None:
            original = b""
            install_deadline = time.monotonic() + args.timeout
            while time.monotonic() < install_deadline:
                original = bytes(
                    dme.read_bytes(
                        FTCOLL_DAMAGE_ENTRY, len(FTCOLL_DAMAGE_ENTRY_ORIGINAL)
                    )
                )
                if original == FTCOLL_DAMAGE_ENTRY_ORIGINAL:
                    break
                if any(original):
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Dolphin exited before DOL load: {process.returncode}"
                    )
                time.sleep(0.002)
            if original != FTCOLL_DAMAGE_ENTRY_ORIGINAL:
                raise RuntimeError(
                    "ftColl_80076ED8 prologue does not match pinned GALE01: "
                    f"{original.hex()}"
                )
            capture_trampoline = build_ftcoll_capture_trampoline(
                args.freeze_ftcoll_frame
            )
            trampoline_before = b""
            trampoline_deadline = time.monotonic() + args.timeout
            while time.monotonic() < trampoline_deadline:
                trampoline_before = bytes(
                    dme.read_bytes(
                        FTCOLL_CAPTURE_TRAMPOLINE, len(capture_trampoline)
                    )
                )
                if trampoline_before == FTCOLL_CAPTURE_TRAMPOLINE_ORIGINAL:
                    break
                if any(trampoline_before):
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        "Dolphin exited before capture region load: "
                        f"{process.returncode}"
                    )
                time.sleep(0.002)
            if trampoline_before != FTCOLL_CAPTURE_TRAMPOLINE_ORIGINAL:
                raise RuntimeError(
                    "grCorneria_801DCCFC capture region does not match pinned "
                    "GALE01: "
                    f"{trampoline_before.hex()}"
                )
            dme.write_bytes(FTCOLL_CAPTURE_SCRATCH, bytes(0x14))
            dme.write_bytes(FTCOLL_CAPTURE_TRAMPOLINE, capture_trampoline)
            dme.write_bytes(FTCOLL_DAMAGE_ENTRY, FTCOLL_DAMAGE_ENTRY_CAPTURE)
            installed_entry = bytes(
                dme.read_bytes(
                    FTCOLL_DAMAGE_ENTRY, len(FTCOLL_DAMAGE_ENTRY_CAPTURE)
                )
            )
            installed_trampoline = bytes(
                dme.read_bytes(
                    FTCOLL_CAPTURE_TRAMPOLINE, len(capture_trampoline)
                )
            )
            if (
                installed_entry != FTCOLL_DAMAGE_ENTRY_CAPTURE
                or installed_trampoline != capture_trampoline
            ):
                raise RuntimeError("ftColl capture trampoline did not retain")
            capture_patch_installed = True
        elif args.freeze_lb_copy_frame is not None:
            original = b""
            install_deadline = time.monotonic() + args.timeout
            while time.monotonic() < install_deadline:
                original = bytes(
                    dme.read_bytes(LB_COPY_ENTRY, len(LB_COPY_ENTRY_ORIGINAL))
                )
                if original == LB_COPY_ENTRY_ORIGINAL:
                    break
                if any(original):
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Dolphin exited before DOL load: {process.returncode}"
                    )
                time.sleep(0.002)
            if original != LB_COPY_ENTRY_ORIGINAL:
                raise RuntimeError(
                    "lb_8000C490 prologue does not match pinned GALE01: "
                    f"{original.hex()}"
                )

            lb_copy_trampoline = build_lb_copy_capture_trampoline(
                args.freeze_lb_copy_frame,
                args.lb_copy_player_slot,
                args.lb_copy_part_index,
                args.lb_copy_freeze_after_calls,
            )
            trampoline_before = b""
            trampoline_deadline = time.monotonic() + args.timeout
            while time.monotonic() < trampoline_deadline:
                trampoline_before = bytes(
                    dme.read_bytes(
                        FTCOLL_CAPTURE_TRAMPOLINE,
                        LB_COPY_CAPTURE_TRAMPOLINE_SIZE,
                    )
                )
                trampoline_hash = hashlib.sha256(
                    trampoline_before
                ).hexdigest()
                if trampoline_hash == LB_COPY_CAPTURE_TRAMPOLINE_SHA256:
                    break
                if any(trampoline_before):
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        "Dolphin exited before capture region load: "
                        f"{process.returncode}"
                    )
                time.sleep(0.002)
            trampoline_hash = hashlib.sha256(trampoline_before).hexdigest()
            if trampoline_hash != LB_COPY_CAPTURE_TRAMPOLINE_SHA256:
                raise RuntimeError(
                    "grCorneria_801DCCFC capture region does not match pinned "
                    f"GALE01: sha256={trampoline_hash}"
                )

            entry_capture = struct.pack(
                ">I", encode_ppc_branch(LB_COPY_ENTRY, FTCOLL_CAPTURE_TRAMPOLINE)
            )
            dme.write_bytes(
                FTCOLL_CAPTURE_SCRATCH, bytes(LB_COPY_CAPTURE_SCRATCH_SIZE)
            )
            dme.write_bytes(FTCOLL_CAPTURE_TRAMPOLINE, lb_copy_trampoline)
            dme.write_bytes(LB_COPY_ENTRY, entry_capture)
            installed_entry = bytes(dme.read_bytes(LB_COPY_ENTRY, 4))
            installed_trampoline = bytes(
                dme.read_bytes(
                    FTCOLL_CAPTURE_TRAMPOLINE, len(lb_copy_trampoline)
                )
            )
            if (
                installed_entry != entry_capture
                or installed_trampoline != lb_copy_trampoline
            ):
                raise RuntimeError("lb_8000C490 capture trampoline did not retain")
            lb_copy_patch_installed = True

        samples: list[dict[str, object]] = []
        observed: set[int] = set()
        last_counter = -1
        frozen_collision_call: dict[str, object] | None = None
        frozen_lb_copy_calls: dict[str, object] | None = None
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            counter = int(dme.read_word(MATCH_INFO + 0x24))
            last_counter = counter
            slippi_frame = counter - 1
            if capture_patch_installed:
                frozen_collision_call = read_frozen_collision_call(dme, counter)
                if frozen_collision_call is not None:
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.0002)
                continue
            if lb_copy_patch_installed:
                frozen_lb_copy_calls = read_frozen_lb_copy_calls(
                    dme,
                    counter,
                    args.freeze_lb_copy_frame,
                    args.lb_copy_player_slot,
                    args.lb_copy_part_index,
                )
                if frozen_lb_copy_calls is not None:
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.0002)
                continue
            if args.first_frame <= slippi_frame <= args.last_frame:
                if slippi_frame not in observed:
                    sample = read_polled_sample(dme, counter)
                    if sample is not None:
                        samples.append(sample)
                        observed.add(slippi_frame)
            if slippi_frame > args.last_frame:
                break
            if process.poll() is not None:
                break
            time.sleep(0.0002)
        if args.freeze_ftcoll_frame is not None and frozen_collision_call is None:
            last_collision_counter = int(
                dme.read_word(FTCOLL_CAPTURE_SCRATCH + 0x10)
            )
            raise RuntimeError(
                "frozen ftColl call was not captured; "
                f"last_counter={last_counter} "
                f"last_collision_counter={last_collision_counter} "
                f"patch={capture_patch_installed}"
            )
        if args.freeze_lb_copy_frame is not None and frozen_lb_copy_calls is None:
            scratch = Snapshot.read(dme, FTCOLL_CAPTURE_SCRATCH, 0x14)
            raise RuntimeError(
                "frozen lb_8000C490 calls were not captured; "
                f"last_counter={last_counter} "
                f"capture_count={scratch.u32(FTCOLL_CAPTURE_SCRATCH)} "
                f"patch={lb_copy_patch_installed}"
            )
        if (
            args.freeze_ftcoll_frame is None
            and args.freeze_lb_copy_frame is None
            and args.last_frame not in observed
        ):
            raise RuntimeError(
                f"last requested frame was not captured; last_counter={last_counter} "
                f"observed={sorted(observed)}"
            )
        args.output.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "polling_claim_boundary": "counter-stable-diagnostic-not-finalized-frame",
                    "playback_should_resync": True,
                    "replay": str(args.replay),
                    "dolphin": str(args.dolphin),
                    "emulation_speed": args.emulation_speed,
                    "ftcoll_damage_entry": {
                        "address": f"0x{FTCOLL_DAMAGE_ENTRY:08x}",
                        "original": FTCOLL_DAMAGE_ENTRY_ORIGINAL.hex(),
                        "entry_capture": FTCOLL_DAMAGE_ENTRY_CAPTURE.hex(),
                        "trampoline_address": (
                            f"0x{FTCOLL_CAPTURE_TRAMPOLINE:08x}"
                        ),
                        "trampoline_owner": "grCorneria_801DCCFC",
                        "trampoline_original": (
                            FTCOLL_CAPTURE_TRAMPOLINE_ORIGINAL.hex()
                        ),
                        "trampoline": (
                            capture_trampoline.hex()
                            if capture_trampoline is not None
                            else None
                        ),
                    }
                    if args.freeze_ftcoll_frame is not None
                    else None,
                    "frozen_collision_call": frozen_collision_call,
                    "lb_copy_entry": {
                        "address": f"0x{LB_COPY_ENTRY:08x}",
                        "original": LB_COPY_ENTRY_ORIGINAL.hex(),
                        "entry_capture": struct.pack(
                            ">I",
                            encode_ppc_branch(
                                LB_COPY_ENTRY, FTCOLL_CAPTURE_TRAMPOLINE
                            ),
                        ).hex(),
                        "trampoline_address": (
                            f"0x{FTCOLL_CAPTURE_TRAMPOLINE:08x}"
                        ),
                        "trampoline_owner": "grCorneria_801DCCFC",
                        "trampoline_original_sha256": (
                            LB_COPY_CAPTURE_TRAMPOLINE_SHA256
                        ),
                        "trampoline": (
                            lb_copy_trampoline.hex()
                            if lb_copy_trampoline is not None
                            else None
                        ),
                        "player_slot": args.lb_copy_player_slot,
                        "part_index": args.lb_copy_part_index,
                        "freeze_after_calls": args.lb_copy_freeze_after_calls,
                    }
                    if args.freeze_lb_copy_frame is not None
                    else None,
                    "frozen_lb_copy_calls": frozen_lb_copy_calls,
                    "samples": samples,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "samples": len(samples),
                    "frames": sorted(observed),
                    "frozen_collision_frame": (
                        frozen_collision_call["slippi_frame"]
                        if frozen_collision_call is not None
                        else None
                    ),
                    "frozen_lb_copy_frame": (
                        frozen_lb_copy_calls["capture_frame"]
                        if frozen_lb_copy_calls is not None
                        else None
                    ),
                    "frozen_lb_copy_calls": (
                        frozen_lb_copy_calls["capture_count"]
                        if frozen_lb_copy_calls is not None
                        else None
                    ),
                    "output": str(args.output),
                }
            )
        )
    finally:
        if dme.is_hooked():
            dme.un_hook()
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5.0)
        log_file.close()
        shutil.rmtree(temporary_user)


if __name__ == "__main__":
    main()
