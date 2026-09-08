#!/usr/bin/env python3
"""Fast contracts for the reusable UCF full-PAD trace boundary."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

# The production capture environment pins libmelee 0.47.2, but these are pure
# trace-builder tests and CI must not need the external oracle environment.
# Supply only the import-time surface used by capture_ssbm_movement when the
# package is absent; no test executes a Dolphin/libmelee operation.
try:
    from melee import console as melee_console  # type: ignore[import-not-found]  # noqa: E402
except ModuleNotFoundError:
    melee_module = types.ModuleType("melee")
    melee_console = types.ModuleType("melee.console")
    melee_console.get_dolphin_version = lambda _path: "test-only"  # type: ignore[attr-defined]
    melee_module.console = melee_console  # type: ignore[attr-defined]
    melee_module.Action = type(  # type: ignore[attr-defined]
        "Action",
        (),
        {"__members__": {"TUMBLING": object(), "FALLING": object()}},
    )
    melee_module.Character = type("Character", (), {"FOX": object()})  # type: ignore[attr-defined]
    sys.modules["melee"] = melee_module
    sys.modules["melee.console"] = melee_console

if not hasattr(melee_console, "get_dolphin_version"):
    melee_console.get_dolphin_version = lambda _path: "test-only"  # type: ignore[attr-defined]

from capture_ssbm_checkpoint_shards import memory_probe_arguments  # noqa: E402
from capture_ssbm_movement import input_trace, parse_args  # noqa: E402
from compare_ssbm_movement import native_input_line, source_axis_q15  # noqa: E402
from generate_ssbm_stored_trace_oracle import native_csv_input_line  # noqa: E402
from ssbm_live_trace import source_axis_to_sim_q15  # noqa: E402


class FullPadNativeCsvTests(unittest.TestCase):
    def test_full_raw_pad_is_appended_without_reencoding_processed_axes(self) -> None:
        sample = {
            "lanes": [
                {
                    "main": [32767, 2458],
                    "c_stick": [-2867, -32767],
                    "raw_main": [80, 6],
                    "raw_c": [-7, -80],
                },
                {},
            ]
        }
        line = native_csv_input_line(
            sample,
            "full-pad",
            0,
            include_raw_main=True,
            include_raw_c=True,
        )
        self.assertEqual(
            line,
            "32767,-2458,-2867,32767,0,0,0,0,0,80,6,-7,-80,15",
        )

    def test_raw_c_without_raw_main_fails_closed(self) -> None:
        sample = {"lanes": [{"raw_c": [80, 0]}, {}]}
        with self.assertRaisesRegex(ValueError, "requires raw main"):
            native_csv_input_line(
                sample,
                "partial-pad",
                0,
                include_raw_c=True,
            )

    def test_live_line_uses_pre_ucf_pad_axes_and_full_raw_mask(self) -> None:
        row = {
            "observed_main_x": 1.0,
            "observed_main_y": 0.5,
            "observed_c_x": 0.5,
            "observed_c_y": 0.5,
            "observed_raw_main_x": 80,
            "observed_raw_main_y": 6,
            "observed_raw_c_x": -7,
            "observed_raw_c_y": -80,
            "input_memory": {
                "fighter_pre_ucf_main_x": 1.0,
                "fighter_pre_ucf_main_y": 0.075,
                "fighter_pre_ucf_c_x": -0.0875,
                "fighter_pre_ucf_c_y": -1.0,
            },
        }
        self.assertEqual(
            native_input_line(
                row,
                include_raw_main=True,
                include_raw_c=True,
            ),
            "32767,-2458,-2867,32767,0,0,0,0,0,80,6,-7,-80,15",
        )

    def test_live_line_preserves_independent_analog_triggers(self) -> None:
        row = {
            "observed_main_x": 0.5,
            "observed_main_y": 0.5,
            "observed_left_shoulder": 0.25,
            "observed_right_shoulder": 0.75,
            "requested_left_shoulder": 0.25,
            "requested_right_shoulder": 0.75,
        }
        self.assertEqual(
            native_input_line(row),
            "0,0,0,0,16384,49151,0,0,0",
        )


class UcfCheckpointCaptureTests(unittest.TestCase):
    def test_platform_guard_uses_natural_line2_route_and_trigger_phases(
        self,
    ) -> None:
        trace = input_trace(
            special_acquisition_only=True,
            checkpoint_isolated=True,
            checkpoint_capture_plan={
                "special_acquisition_cases": [
                    {
                        "id": "platform_guard",
                        "checkpoint_slot": 0,
                        "source_state": "platform_guard",
                        "pre_edge_phases": [
                            {
                                "ticks": 2,
                                "main": [19660, 0],
                                "left_trigger": 32768,
                                "digital_left": True,
                            }
                        ],
                        "edge_main": [19660, 25804],
                        "edge_action": "none",
                        "edge_right_trigger": 16384,
                        "edge_digital_right": True,
                        "observe_ticks": 1,
                    }
                ]
            },
        )
        self.assertEqual(len(trace), 200)
        self.assertTrue(trace[0]["restore_before"])
        self.assertEqual(trace[0]["checkpoint_slot"], 0)
        self.assertEqual(trace[0]["fighter_x_override"], -38.8)
        self.assertEqual(trace[0]["fighter_y_override"], 27.2001)
        self.assertTrue(trace[0]["fighter_position_state_reset"])
        self.assertTrue(all(not row.get("record", True) for row in trace[:196]))
        self.assertTrue(all(row["main_x"] == 0.5 for row in trace[:196]))
        self.assertEqual(trace[60]["label"], "special_acquisition_platform_guard_platform_jump")
        self.assertTrue(trace[60]["jump"])
        self.assertEqual(
            [row["label"] for row in trace[61:66]],
            ["special_acquisition_platform_guard_platform_jump_squat"] * 5,
        )
        self.assertEqual(
            [row["label"] for row in trace[66:166]],
            ["special_acquisition_platform_guard_platform_landing_setup"] * 100,
        )
        self.assertEqual(
            [row["label"] for row in trace[166:196]],
            ["special_acquisition_platform_guard_platform_landing_settle"] * 30,
        )
        self.assertEqual(trace[196]["left_shoulder"], 32768 / 65535.0)
        self.assertTrue(trace[196]["digital_left"])
        self.assertEqual(trace[198]["right_shoulder"], 16384 / 65535.0)
        self.assertTrue(trace[198]["digital_right"])

    def test_platform_guard_rejects_a_triggerless_pre_edge(self) -> None:
        with self.assertRaisesRegex(ValueError, "trigger-valued pre-edge"):
            input_trace(
                special_acquisition_only=True,
                checkpoint_isolated=True,
                checkpoint_capture_plan={
                    "special_acquisition_cases": [
                        {
                            "id": "triggerless",
                            "source_state": "platform_guard",
                            "pre_edge_phases": [{"ticks": 1}],
                            "edge_main": [0, 0],
                        }
                    ]
                },
            )

    def test_input_surface_probe_composes_only_for_checkpoint_acquisition(
        self,
    ) -> None:
        self.assertEqual(
            memory_probe_arguments("input-surface"),
            ("--memory-probe-input", "--memory-probe-surface"),
        )
        args = parse_args(
            [
                "--dolphin",
                "dolphin",
                "--iso",
                "game.iso",
                "--output",
                "capture.json",
                "--special-acquisition-only",
                "--oracle-exiai",
                "--oracle-release-artifact",
                "release.AppImage",
                "--oracle-checkpoint-pack",
                "--oracle-coverage-manifest",
                "coverage.json",
                "--memory-probe-input",
                "--memory-probe-surface",
            ]
        )
        self.assertTrue(args.memory_probe_input)
        self.assertTrue(args.memory_probe_surface)

    def test_shield_input_manifest_records_exact_declared_row_count(self) -> None:
        coverage = json.loads(
            (ROOT / "tools" / "ssbm_ucf084_shield_input_coverage.json")
            .read_text(encoding="utf-8")
        )
        trace = input_trace(
            special_acquisition_only=True,
            checkpoint_isolated=True,
            checkpoint_capture_plan=coverage["checkpoint_pack"]["capture_plan"],
        )
        recorded = [row for row in trace if row.get("record", True)]
        self.assertEqual(
            len(recorded),
            coverage["checkpoint_pack"]["expected_rows"],
        )

    def test_hitlag_input_manifest_records_two_frame_history_and_boundary(
        self,
    ) -> None:
        coverage = json.loads(
            (ROOT / "tools" / "ssbm_ucf084_hitlag_input_coverage.json")
            .read_text(encoding="utf-8")
        )
        trace = input_trace(
            damage_hit_only=True,
            checkpoint_isolated=True,
            checkpoint_capture_plan=coverage["checkpoint_pack"]["capture_plan"],
        )
        recorded = [row for row in trace if row.get("record", True)]
        self.assertEqual(
            len(recorded),
            coverage["checkpoint_pack"]["expected_rows"],
        )
        for case_index in range(4):
            rows = recorded[case_index * 4 : case_index * 4 + 4]
            prefix = coverage["checkpoint_pack"]["capture_plan"][
                "damage_response_cases"
            ][case_index]["id"]
            self.assertEqual(
                [row["label"] for row in rows],
                [
                    f"damage_response_{prefix}_pre_hit_1",
                    f"damage_response_{prefix}_pre_hit_2",
                    f"damage_response_{prefix}_hitlag_1",
                    f"damage_response_{prefix}_hitlag_2",
                ],
            )
            shield = prefix.startswith("shield_")
            self.assertTrue(
                all(row["digital_left"] is shield for row in rows)
            )
            self.assertTrue(
                all(row["left_shoulder"] == (1.0 if shield else 0.0)
                    for row in rows)
            )

    def test_tumble_input_manifest_keeps_only_the_causal_three_row_tail(
        self,
    ) -> None:
        coverage = json.loads(
            (ROOT / "tools" / "ssbm_ucf084_tumble_input_coverage.json")
            .read_text(encoding="utf-8")
        )
        trace = input_trace(
            damage_hit_only=True,
            checkpoint_isolated=True,
            checkpoint_capture_plan=coverage["checkpoint_pack"]["capture_plan"],
        )
        cases = coverage["checkpoint_pack"]["capture_plan"][
            "surface_response_cases"
        ]
        for case in cases:
            prefix = f"surface_response_{case['id']}_observe_"
            retained = [
                row for row in trace if str(row["label"]).startswith(prefix)
            ]
            causal = [
                row
                for row in retained
                if row["label"].endswith(("_t2", "_precursor", "_edge"))
            ]
            self.assertEqual(len(causal), 3)
            self.assertEqual(
                [row["label"].removeprefix(prefix) for row in causal],
                ["t2", "precursor", "edge"],
            )
            self.assertTrue(
                all(row["record_actions"] == ("TUMBLING", "FALLING")
                    for row in causal)
            )


class SourceAxisTests(unittest.TestCase):
    def test_pre_ucf_and_post_ucf_negative_endpoints_are_distinct(self) -> None:
        self.assertEqual(source_axis_q15(-1.0), -32767)
        self.assertEqual(source_axis_to_sim_q15(-1.0), -32768)
        self.assertEqual(source_axis_to_sim_q15(1.0, invert=True), -32768)
        self.assertEqual(source_axis_to_sim_q15(-1.0, invert=True), 32767)


if __name__ == "__main__":
    unittest.main()
