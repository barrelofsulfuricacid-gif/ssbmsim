#!/usr/bin/env python3
"""Unit tests for the headless frame-exact collision/pose probe."""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
from contextlib import ExitStack


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ssbm_headless_collision_probe as probe  # noqa: E402


def relative_branch_target(address: int, word: int, bits: int) -> int:
    mask = (1 << bits) - 4
    delta = word & mask
    if delta & (1 << (bits - 1)):
        delta -= 1 << bits
    return address + delta


class FakeDME:
    def __init__(self) -> None:
        self.memory: dict[int, int] = {}

    def write(self, address: int, data: bytes) -> None:
        for offset, value in enumerate(data):
            self.memory[address + offset] = value

    def write_word(self, address: int, value: int) -> None:
        self.write(address, struct.pack(">I", value))

    def read_bytes(self, address: int, size: int) -> bytes:
        return bytes(self.memory.get(address + offset, 0) for offset in range(size))

    def read_word(self, address: int) -> int:
        return struct.unpack(">I", self.read_bytes(address, 4))[0]


class HeadlessCollisionProbeTests(unittest.TestCase):
    def test_polled_sample_checks_every_read_phase(self) -> None:
        phases = ("discover_active_player_slots", "read_fighter",
                  "read_fighter_list", "read_stale_table")
        for changed in (*phases, None):
            with self.subTest(changed=changed), ExitStack() as stack:
                dme = FakeDME()
                dme.write_word(probe.MATCH_INFO + 0x24, 100)
                for phase in phases:
                    def read(*args, phase=phase):
                        if phase == changed:
                            dme.write_word(probe.MATCH_INFO + 0x24, 101)
                        return [0, 1] if phase == phases[0] else {"phase": phase}
                    stack.enter_context(patch.object(probe, phase, side_effect=read))
                sample = probe.read_polled_sample(dme, 100)
                if changed is None:
                    self.assertEqual(sample["frame_count"], 100)
                    self.assertEqual(len(sample["stale_tables"]), 2)
                else:
                    self.assertIsNone(sample)

    def test_polled_sample_rejects_stale_initial_counter(self) -> None:
        dme = FakeDME()
        dme.write_word(probe.MATCH_INFO + 0x24, 101)
        with patch.object(probe, "discover_active_player_slots") as discover:
            self.assertIsNone(probe.read_polled_sample(dme, 100))
            discover.assert_not_called()

    def test_lb_copy_trampoline_preserves_control_flow_and_filter(self) -> None:
        frame = 5977
        player_slot = 2
        part_index = 2
        trampoline = probe.build_lb_copy_capture_trampoline(
            frame, player_slot, part_index, freeze_after_calls=3
        )
        words = list(struct.unpack(">72I", trampoline))
        base = probe.FTCOLL_CAPTURE_TRAMPOLINE

        self.assertEqual(len(trampoline), probe.LB_COPY_CAPTURE_TRAMPOLINE_SIZE)
        self.assertEqual(words[3] & 0xFFFF, frame)
        self.assertEqual(words[20] & 0xFFFF, part_index * 0x10)
        self.assertEqual(
            relative_branch_target(base + 4 * 4, words[4], 16), base + 65 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 5 * 4, words[5], 16), base + 12 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 8 * 4, words[8], 16), base + 65 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 11 * 4, words[11], 26), base + 11 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 22 * 4, words[22], 16), base + 65 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 25 * 4, words[25], 16), base + 62 * 4
        )
        self.assertEqual(
            words[57] & 0xFFFF, 3
        )
        self.assertEqual(
            relative_branch_target(base + 58 * 4, words[58], 16), base + 65 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 61 * 4, words[61], 26), base + 11 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 64 * 4, words[64], 26), base + 11 * 4
        )
        self.assertEqual(
            relative_branch_target(base + 71 * 4, words[71], 26),
            probe.LB_COPY_ENTRY + len(probe.LB_COPY_ENTRY_ORIGINAL),
        )

        static_player = (
            probe.STATIC_PLAYERS + player_slot * probe.STATIC_PLAYER_STRIDE
        )
        high_adjusted = words[12] & 0xFFFF
        low_signed = struct.unpack(">h", struct.pack(">H", words[13] & 0xFFFF))[0]
        self.assertEqual((high_adjusted << 16) + low_signed, static_player)
        self.assertEqual(
            words[31:35],
            [0x81610000, 0x816B0000, 0x816B0004, 0x91660008],
        )
        self.assertEqual(words[37:39], [0x816A0010, 0x9166000C])

    def test_lb_copy_trampoline_rejects_unencodable_filters(self) -> None:
        invalid_arguments = (
            (-1, 2, 2),
            (0x8000, 2, 2),
            (5977, -1, 2),
            (5977, 6, 2),
            (5977, 2, -1),
            (5977, 2, 0x800),
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    probe.build_lb_copy_capture_trampoline(*arguments)
        with self.assertRaises(ValueError):
            probe.build_lb_copy_capture_trampoline(5977, 2, 2, 0)
        with self.assertRaises(ValueError):
            probe.build_lb_copy_capture_trampoline(
                5977, 2, 2, probe.LB_COPY_CAPTURE_MAX_RECORDS + 1
            )

    def test_entry_branch_targets_pinned_corneria_cave(self) -> None:
        word = probe.encode_ppc_branch(
            probe.LB_COPY_ENTRY, probe.FTCOLL_CAPTURE_TRAMPOLINE
        )
        self.assertEqual(
            relative_branch_target(probe.LB_COPY_ENTRY, word, 26),
            probe.FTCOLL_CAPTURE_TRAMPOLINE,
        )

    def test_active_slot_discovery_handles_noncontiguous_ports(self) -> None:
        dme = FakeDME()
        for player_slot, gobj, fighter in (
            (0, 0x81000000, 0x81001000),
            (2, 0x81002000, 0x81003000),
        ):
            static_player = (
                probe.STATIC_PLAYERS
                + player_slot * probe.STATIC_PLAYER_STRIDE
            )
            dme.write(static_player + 0x0C, b"\x00")
            dme.write_word(static_player + 0xB0, gobj)
            dme.write_word(gobj + 0x2C, fighter)

        self.assertEqual(probe.discover_active_player_slots(dme), [0, 2])


if __name__ == "__main__":
    unittest.main()
