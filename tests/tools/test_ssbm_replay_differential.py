#!/usr/bin/env python3
"""Fast unit tests for the offline Slippi differential worker."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ssbm_replay_differential import (  # noqa: E402
    ConfigurationError,
    PHYSICAL_L,
    actual_row,
    classify_source_modifier,
    compare_rows,
    detect_ucf_dashback,
    detect_ucf084_cardinal_mismatch,
    diagnostic_execution_reference,
    first_semantic_difference,
    input_trigger,
    native_input,
    qualify_segment,
    reference_qualification,
    scale_f32,
)


EXACT_REFERENCE = {"status": "exact", "failures": []}


class Float32ProjectionTests(unittest.TestCase):
    def test_source_scale_returns_direct_float32_units(self) -> None:
        scaled = scale_f32(1.0, {"numerator": 12, "denominator": 115})
        self.assertAlmostEqual(scaled, 12.0 / 115.0, places=7)
        self.assertLess(scaled, 1.0)

    def test_native_csv_keeps_float_fields_as_floats(self) -> None:
        parsed = actual_row(
            {
                "tick": "1",
                "action_state": "2",
                "action_ticks": "3",
                "facing": "-1",
                "grounded": "1",
                "position_x_f32_from_origin": "0.125",
                "position_y_f32_from_origin": "-0.25",
                "velocity_x_f32": "0.03125",
                "velocity_y_f32": "-0.0625",
            }
        )
        self.assertEqual(parsed["action_state"], 2)
        self.assertEqual(parsed["position_x_f32_from_origin"], 0.125)
        self.assertEqual(parsed["velocity_y_f32"], -0.0625)

    def test_comparison_uses_direct_float_tolerances(self) -> None:
        expected = {
            "action_state": 2,
            "facing": 1,
            "grounded": 1,
            "position_x_f32_from_origin": 1.0,
            "position_y_f32_from_origin": 2.0,
            "velocity_x_f32": 0.5,
            "velocity_y_f32": -0.5,
        }
        actual = dict(expected)
        actual["position_x_f32_from_origin"] = 1.01
        actual["velocity_y_f32"] = -0.49975
        profile = {
            "comparison": {
                "position_tolerance_f32": 0.015625,
                "velocity_tolerance_f32": 0.00048828125,
            }
        }
        self.assertEqual(compare_rows(expected, actual, profile), [])
        actual["position_x_f32_from_origin"] = 1.02
        self.assertTrue(compare_rows(expected, actual, profile))


def replay_fixture(
    controller_fix: str | None = "UCF",
    raw_x: int = -79,
    raw_y: int | None = 0,
) -> dict:
    def source_frame(
        processed_x: float,
        source_raw_x: int,
        action: int,
        counter: float,
    ) -> dict:
        return {
            "players": [
                {
                    "pre": {
                        "joystickX": processed_x,
                        "joystickY": 0.0,
                        "rawJoystickX": source_raw_x,
                        "rawJoystickY": raw_y,
                    },
                    "post": {
                        "actionStateId": action,
                        "actionStateCounter": counter,
                    },
                }
            ]
        }

    return {
        "settings": {
            "players": [
                {
                    "playerIndex": 0,
                    "controllerFix": controller_fix,
                }
            ]
        },
        "frames": {
            0: source_frame(0.0, 0, 14, 8.0),
            1: source_frame(-0.4625, -37, 18, 1.0),
            2: source_frame(-0.9875, raw_x, 20, 1.0),
        },
    }


class SourceModifierClassifierTests(unittest.TestCase):
    def test_unsnapped_raw_cardinal_proves_non_target_ucf(self) -> None:
        replay = replay_fixture(raw_x=-80, raw_y=4)
        replay["frames"][2]["players"][0]["pre"]["joystickX"] = -0.9875
        evidence = detect_ucf084_cardinal_mismatch(
            replay, replay["frames"], 2, 0
        )
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(
            evidence["classification"], "ucf084-cardinal-signature-mismatch"
        )
        self.assertEqual(evidence["raw_main"], [-80, 4])
        self.assertEqual(evidence["ucf084_processed_main"], [-1.0, 0.0])
        self.assertEqual(
            classify_source_modifier(
                replay, replay["frames"], 2, 0, EXACT_REFERENCE
            )["classification"],
            "ucf084-cardinal-signature-mismatch",
        )

    def test_snapped_raw_cardinal_matches_target_ucf(self) -> None:
        replay = replay_fixture(raw_x=-80, raw_y=4)
        replay["frames"][2]["players"][0]["pre"].update(
            {"joystickX": -1.0, "joystickY": 0.0}
        )
        self.assertIsNone(
            detect_ucf084_cardinal_mismatch(replay, replay["frames"], 2, 0)
        )

    def test_exact_ucf_raw_history_signature_is_exercisable(self) -> None:
        replay = replay_fixture()
        evidence = detect_ucf_dashback(replay, replay["frames"], 2, 0)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence["classification"], "ucf-raw-history-dashback")
        self.assertEqual(evidence["raw_delta"], -79)
        self.assertEqual(evidence["source_action_transition"], [18, 20])
        self.assertIsNone(
            classify_source_modifier(
                replay, replay["frames"], 2, 0, EXACT_REFERENCE
            )
        )

    def test_exact_signature_without_raw_y_fails_closed(self) -> None:
        replay = replay_fixture(raw_y=None)
        evidence = classify_source_modifier(
            replay, replay["frames"], 2, 0, EXACT_REFERENCE
        )
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(
            evidence["classification"], "unsupported-ucf-raw-main-unavailable"
        )
        self.assertEqual(evidence["missing_source_frames"], [0, 1, 2])

    def test_exact_signature_without_reference_fails_closed(self) -> None:
        replay = replay_fixture()
        evidence = classify_source_modifier(replay, replay["frames"], 2, 0)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(
            evidence["classification"],
            "unsupported-ucf-reference-configuration",
        )

    def test_same_turn_dash_without_declared_ucf_is_not_classified(self) -> None:
        replay = replay_fixture(controller_fix=None)
        self.assertIsNone(
            classify_source_modifier(replay, replay["frames"], 2, 0)
        )

    def test_raw_delta_at_ucf_threshold_is_not_classified(self) -> None:
        replay = replay_fixture(raw_x=-75)
        self.assertIsNone(
            classify_source_modifier(replay, replay["frames"], 2, 0)
        )

    def test_exact_boundary_remains_inside_qualified_prefix(self) -> None:
        replay = replay_fixture()
        for frame in replay["frames"].values():
            source = frame["players"][0]
            source["post"].update(
                {
                    "percent": 0.0,
                    "stocksRemaining": 4,
                    "positionX": 0.0,
                    "positionY": 0.0,
                    "isAirborne": False,
                    "lastGroundId": 1,
                }
            )
            frame["players"].append(
                {
                    "pre": {},
                    "post": {
                        "positionX": 50.0,
                        "positionY": 0.0,
                    },
                }
            )
        profile = {
            "qualification": {
                "maximum_prefix_frames": 3,
                "maximum_abs_source_x": 55.0,
                "minimum_opponent_x_distance": 22.0,
                "minimum_opponent_y_distance": 18.0,
            },
            "source_main_floor_ground_ids": [1],
            "source_actions": {"18": {}, "20": {}},
        }
        result = qualify_segment(
            replay,
            replay["frames"],
            0,
            0,
            1,
            profile,
            EXACT_REFERENCE,
        )
        self.assertEqual(result["last_supported_frame"], 2)
        self.assertIsNone(result["modifier_boundary"])
        self.assertEqual(
            [
                value["classification"]
                for value in result["exercised_ucf_boundaries"]
            ],
            ["ucf-raw-history-dashback"],
        )


def complete_pre(raw_x: int | None = -76, raw_y: int | None = 4) -> dict:
    return {
        "joystickX": -0.95,
        "joystickY": 0.05,
        "cStickX": 0.0,
        "cStickY": 0.0,
        "trigger": 0.0,
        "physicalButtons": 0,
        "physicalLTrigger": 0.0,
        "physicalRTrigger": 0.0,
        "rawJoystickX": raw_x,
        "rawJoystickY": raw_y,
    }


class NativeInputContractTests(unittest.TestCase):
    def test_analog_endpoint_preserves_digital_trigger_click(self) -> None:
        self.assertEqual(input_trigger(1.0), 65534)
        pre = complete_pre()
        pre["physicalLTrigger"] = 1.0
        analog_fields = native_input(pre, 1, True).split(",")
        self.assertEqual(analog_fields[4], "65534")
        pre["physicalButtons"] = PHYSICAL_L
        digital_fields = native_input(pre, 1, True).split(",")
        self.assertEqual(digital_fields[4], "65535")

    def test_exact_raw_pair_uses_production_mask_three(self) -> None:
        fields = native_input(complete_pre(), 1, True).split(",")
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[-3:], ["-76", "4", "3"])

    def test_mirror_applies_to_processed_and_raw_x_only(self) -> None:
        fields = native_input(complete_pre(), -1, True).split(",")
        self.assertEqual(fields[-3:], ["76", "4", "3"])
        self.assertGreater(int(fields[0]), 0)

    def test_c_stick_axes_do_not_duplicate_a_digital_strong_button(self) -> None:
        pre = complete_pre()
        pre["cStickX"] = 0.03
        fields = native_input(pre, 1, True).split(",")
        self.assertNotEqual(int(fields[2]), 0)
        self.assertEqual(int(fields[6]), 0)

    def test_missing_raw_pair_never_claims_mask_three(self) -> None:
        pre = complete_pre(raw_y=None)
        self.assertEqual(len(native_input(pre, 1).split(",")), 9)
        with self.assertRaisesRegex(ConfigurationError, "raw main X/Y"):
            native_input(pre, 1, True)

    def test_unrepresentable_mirrored_negative_128_fails_closed(self) -> None:
        pre = complete_pre(raw_x=-128)
        with self.assertRaisesRegex(ConfigurationError, "raw main X/Y"):
            native_input(pre, -1, True)


class ReferenceQualificationTests(unittest.TestCase):
    TARGET = {
        "disc": {
            "game_id": "GALE01",
            "revision": 2,
            "sha256": "0" * 64,
        },
        "modifier": {
            "name": "UCF",
            "revision": "0.84",
            "official_release_tag": "ucf0.84_2024-06-27",
            "official_release_revision": "1" * 40,
        },
    }

    def source_replay(self, exact_raw_y: bool = True) -> dict:
        return {
            "settings": {
                "players": [
                    {
                        "characterId": 0,
                        "controllerFix": "UCF",
                    }
                ]
            },
            "inputProvenance": {
                "framing": "slp-message-sizes-v1",
                "preFramePayloadBytes": 66,
                "rawMainXOffset": 0x3B,
                "rawMainYOffset": 0x40,
                "exactRawMainX": True,
                "exactRawMainY": exact_raw_y,
            },
        }

    def test_exact_target_and_raw_pair_are_accepted(self) -> None:
        result = reference_qualification(
            self.source_replay(),
            {"source_reference": self.TARGET},
            {"reference_target": self.TARGET, "source_character_id": 0},
        )
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["failures"], [])

    def test_unknown_disc_version_and_missing_raw_y_are_fail_closed(self) -> None:
        result = reference_qualification(
            self.source_replay(exact_raw_y=False),
            {},
            {"reference_target": self.TARGET, "source_character_id": 0},
        )
        self.assertEqual(
            result["status"], "unsupported-reference-configuration"
        )
        self.assertEqual(
            result["failures"],
            [
                "disc-identity-unproven",
                "ucf-revision-unproven",
                "raw-main-y-unavailable",
            ],
        )

    def test_diagnostic_execution_allows_only_unknown_reference_provenance(self) -> None:
        unknown = {
            "status": "unsupported-reference-configuration",
            "failures": ["disc-identity-unproven", "ucf-revision-unproven"],
        }
        execution = diagnostic_execution_reference(unknown, True)
        self.assertIsNotNone(execution)
        assert execution is not None
        self.assertEqual(execution["status"], "exact")
        self.assertEqual(
            execution["execution_authority"],
            "diagnostic-unverified-reference",
        )
        self.assertIsNone(diagnostic_execution_reference(unknown, False))
        self.assertIsNone(
            diagnostic_execution_reference(
                {
                    **unknown,
                    "failures": ["disc-identity-mismatch"],
                },
                True,
            )
        )


class PrefixMinimizerTests(unittest.TestCase):
    @staticmethod
    def compare(expected: dict, actual: dict) -> list[str]:
        return [] if expected == actual else ["different"]

    def test_returns_earliest_mismatch_as_minimal_prefix(self) -> None:
        expected = [{"value": 1}, {"value": 2}, {"value": 3}]
        actual = [{"value": 1}, {"value": 9}, {"value": 8}]
        self.assertEqual(
            first_semantic_difference(expected, actual, self.compare),
            (1, ["different"]),
        )

    def test_returns_none_when_all_rows_match(self) -> None:
        rows = [{"value": 1}, {"value": 2}]
        self.assertIsNone(first_semantic_difference(rows, rows, self.compare))

    def test_rejects_unequal_row_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "row counts differ"):
            first_semantic_difference(
                [{"value": 1}],
                [],
                self.compare,
            )


if __name__ == "__main__":
    unittest.main()
