"""Unit tests for the complete-match Slippi differential lane."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ssbm_full_match_differential import (  # noqa: E402
    canonical_target_action,
    equivalent_collision_adjusted_displacement,
    expected_target_action,
    expected_target_position_f32,
    expected_target_self_velocity_f32,
    native_player_fields,
    validate_complete_match,
)
from ssbm_collision import binary32  # noqa: E402


def pre_frame(*, raw_c: bool = True) -> dict:
    return {
        "seed": 1234,
        "joystickX": 0.5,
        "joystickY": -0.25,
        "cStickX": -1.0,
        "cStickY": 1.0,
        "physicalButtons": 0,
        "physicalLTrigger": 0.25,
        "physicalRTrigger": 0.5,
        "rawJoystickX": 40,
        "rawJoystickY": -20,
        "rawCStickX": -80 if raw_c else None,
        "rawCStickY": 80 if raw_c else None,
    }


def complete_replay(*, raw_c: bool = True) -> dict:
    player_settings = [
        {
            "playerIndex": index,
            "characterId": 0,
            "type": 0,
            "startStocks": 4,
            "controllerFix": "UCF",
        }
        for index in (0, 1)
    ]
    sample = {
        "pre": pre_frame(raw_c=raw_c),
        "post": {
            "actionStateId": 322,
            "facingDirection": 1,
            "isAirborne": True,
            "stocksRemaining": 4,
            "percent": 0,
        },
    }
    return {
        "settings": {
            "players": player_settings,
            "isPAL": False,
            "isTeams": False,
            "timerType": 2,
            "startingTimerSeconds": 480,
            "itemSpawnBehavior": 255,
            "stageId": 31,
            "isFrozenPS": False,
        },
        "gameEnd": {"gameEndMethod": 2},
        "inputProvenance": {
            "framing": "slp-message-sizes-v1",
            "exactRawMainX": True,
            "exactRawMainY": True,
            "exactRawCX": raw_c,
            "exactRawCY": raw_c,
        },
        "frames": [
            {
                "frame": -123,
                "startSeed": 1234,
                "players": [sample, sample],
            }
        ],
    }


class CompleteMatchValidationTests(unittest.TestCase):
    def test_position_projection_uses_direct_float32_units(self) -> None:
        profile = {
            "source_to_target_x_scale": {
                "numerator": 12,
                "denominator": 115,
            },
            "source_to_target_y_scale": {
                "numerator": 11,
                "denominator": 62,
                "invert": True,
                "origin_f32": 20.0,
                "fighter_root_to_body_center_f32": 0.79998779296875,
            },
        }
        x, y = expected_target_position_f32(
            profile, {"positionX": 9.0, "positionY": 3.0}
        )
        self.assertAlmostEqual(x, 9.0 * 12.0 / 115.0, places=7)
        self.assertEqual(
            y,
            binary32(
                20.0
                + binary32(-3.0 * 11.0 / 62.0)
                - 0.79998779296875
            ),
        )
        self.assertLess(abs(x), 10.0)

    def test_self_velocity_projection_excludes_knockback_channel(self) -> None:
        profile = {
            "source_to_target_x_scale": {"numerator": 12, "denominator": 115},
            "source_to_target_y_scale": {
                "numerator": 11,
                "denominator": 62,
                "invert": True,
            },
        }
        x, y = expected_target_self_velocity_f32(
            profile,
            {
                "isAirborne": False,
                "selfGroundX": 3.0,
                "selfAirX": 9.0,
                "selfY": -2.0,
                "selfAttackX": 0.5,
                "selfAttackY": 0.25,
            },
        )
        self.assertEqual(x, binary32(3.0 * 12.0 / 115.0))
        self.assertEqual(y, binary32(2.0 * 11.0 / 62.0))

    def test_collision_clamp_requires_matching_endpoint_and_velocity(self) -> None:
        arguments = {
            "source_position": 7.1373913,
            "target_position": 7.1373916,
            "source_displacement": 0.26133394,
            "target_displacement": 0.26081562,
            "source_self_velocity": 0.35539758,
            "target_self_velocity": 0.35539761,
            "tolerance": 0.00048828125,
        }
        self.assertTrue(equivalent_collision_adjusted_displacement(**arguments))
        for field, value in (
            ("target_position", 7.138),
            ("target_self_velocity", 0.356),
            ("target_displacement", 0.3553),
        ):
            with self.subTest(field=field):
                changed = dict(arguments)
                changed[field] = value
                self.assertFalse(
                    equivalent_collision_adjusted_displacement(**changed)
                )

    def test_complete_exact_match_is_accepted(self) -> None:
        self.assertEqual(
            validate_complete_match(
                complete_replay(), allow_missing_raw_c=False
            ),
            [],
        )

    def test_missing_raw_c_is_fail_closed_for_qualification(self) -> None:
        self.assertIn(
            "exact-raw-c-unavailable",
            validate_complete_match(
                complete_replay(raw_c=False), allow_missing_raw_c=False
            ),
        )
        self.assertNotIn(
            "exact-raw-c-unavailable",
            validate_complete_match(
                complete_replay(raw_c=False), allow_missing_raw_c=True
            ),
        )

    def test_stadium_must_be_frozen(self) -> None:
        replay = complete_replay()
        replay["settings"]["stageId"] = 28
        self.assertIn(
            "pokemon-stadium-not-frozen",
            validate_complete_match(replay, allow_missing_raw_c=False),
        )

    def test_unsnapped_ucf084_cardinal_rejects_whole_match(self) -> None:
        replay = complete_replay()
        pre = replay["frames"][0]["players"][0]["pre"]
        pre.update(
            {
                "joystickX": -0.9875,
                "joystickY": 0.0,
                "rawJoystickX": -96,
                "rawJoystickY": 1,
            }
        )
        self.assertIn(
            "ucf084-cardinal-signature-mismatch:frame=-123:player=0",
            validate_complete_match(replay, allow_missing_raw_c=False),
        )

    def test_snapped_ucf084_cardinal_accepts_whole_match(self) -> None:
        replay = complete_replay()
        pre = replay["frames"][0]["players"][0]["pre"]
        pre.update(
            {
                "joystickX": -1.0,
                "joystickY": 0.0,
                "rawJoystickX": -96,
                "rawJoystickY": 1,
            }
        )
        self.assertNotIn(
            "ucf084-cardinal-signature-mismatch:frame=-123:player=0",
            validate_complete_match(replay, allow_missing_raw_c=False),
        )

    def test_player_fields_preserve_full_raw_pad(self) -> None:
        fields = native_player_fields(
            pre_frame(raw_c=True), allow_missing_raw_c=False
        )
        self.assertEqual(len(fields), 12)
        self.assertEqual(fields[-5:], [40, -20, -80, 80, 15])

    def test_diagnostic_missing_raw_c_uses_main_only_mask(self) -> None:
        fields = native_player_fields(
            pre_frame(raw_c=False), allow_missing_raw_c=True
        )
        self.assertEqual(fields[-5:], [40, -20, 0, 0, 3])

    def test_frame_start_seed_is_required_for_exact_playback(self) -> None:
        replay = complete_replay()
        replay["frames"][0]["startSeed"] = None
        self.assertIn(
            "missing-frame-start-seed:-123",
            validate_complete_match(replay, allow_missing_raw_c=False),
        )

    def test_every_falcon_aerial_maps_active_hitlag_to_public_hitlag(self) -> None:
        profile = json.loads(
            (ROOT / "tools" / "ssbm_falcon_replay_profile.json").read_text(
                encoding="utf-8"
            )
        )
        for source_action in range(65, 70):
            with self.subTest(source_action=source_action):
                self.assertEqual(
                    expected_target_action(
                        profile,
                        source_action,
                        {},
                        {"hitlagRemaining": 1},
                    ),
                    13,
                )

    def test_profile_level_hitlag_projection_covers_ledge_attacks(self) -> None:
        profile = json.loads(
            (ROOT / "tools" / "ssbm_falcon_replay_profile.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("hitlag_target_action", profile["source_actions"]["256"])
        self.assertEqual(
            expected_target_action(
                profile,
                256,
                {},
                {"hitlagRemaining": 5, "isAirborne": False},
            ),
            13,
        )

    def test_ground_damage_uses_level_specific_public_state(self) -> None:
        profile = json.loads(
            (ROOT / "tools" / "ssbm_falcon_replay_profile.json").read_text(
                encoding="utf-8"
            )
        )
        for source_action, grounded_action in (
            (75, 130),
            (76, 131),
            (77, 132),
            (78, 130),
            (79, 131),
            (80, 132),
            (81, 130),
            (82, 131),
            (83, 132),
        ):
            with self.subTest(source_action=source_action):
                self.assertEqual(
                    expected_target_action(
                        profile,
                        source_action,
                        {},
                        {"hitlagRemaining": 0, "isAirborne": False},
                    ),
                    grounded_action,
                )
                self.assertEqual(
                    expected_target_action(
                        profile,
                        source_action,
                        {},
                        {"hitlagRemaining": 0, "isAirborne": True},
                    ),
                    14,
                )
                self.assertEqual(
                    expected_target_action(
                        profile,
                        source_action,
                        {},
                        {"hitlagRemaining": 0, "isAirborne": False},
                        entered_grounded=False,
                    ),
                    14,
                )

    def test_fall_special_maps_to_public_fall_special(self) -> None:
        profile = json.loads(
            (ROOT / "tools" / "ssbm_falcon_replay_profile.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            expected_target_action(profile, 35, {}, {"hitlagRemaining": 0}),
            33,
        )
        for route_action in (113, 114, 121):
            with self.subTest(route_action=route_action):
                self.assertEqual(
                    canonical_target_action(profile, route_action),
                    33,
                )

    def test_every_falcon_character_action_has_a_public_mapping(self) -> None:
        profile = json.loads(
            (ROOT / "tools" / "ssbm_falcon_replay_profile.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            347: 107,
            348: 108,
            349: 109,
            350: 110,
            351: 111,
            352: 112,
            353: 117,
            354: 118,
            355: 119,
            356: 120,
            357: 123,
            358: 124,
            359: 125,
            360: 126,
            361: 128,
            362: 127,
            363: 129,
        }
        for source_action, target_action in expected.items():
            with self.subTest(source_action=source_action):
                self.assertEqual(
                    expected_target_action(
                        profile,
                        source_action,
                        {},
                        {"hitlagRemaining": 0},
                    ),
                    target_action,
                )


if __name__ == "__main__":
    unittest.main()
