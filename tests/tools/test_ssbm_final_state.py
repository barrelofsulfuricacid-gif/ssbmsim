"""Endpoint screening must ignore recovered errors and reject truncated execution."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from ssbm_native_full_match import final_state_divergence, first_divergence


class FinalStateTests(unittest.TestCase):
    def setUp(self):
        post = dict(actionStateId=14, positionX=1.0, positionY=0.0,
                    facingDirection=1.0, percent=0.0, shieldSize=60.0,
                    selfAirX=0.0, selfGroundX=0.0, selfY=0.0,
                    selfAttackX=0.0, selfAttackY=0.0, hitlagRemaining=0.0,
                    actionStateCounter=2.0, lastGroundId=0, stocksRemaining=4,
                    jumpsRemaining=2, isAirborne=False)
        self.replay = {"frames": [dict(frame=f, startSeed=123,
                         players=[{"post": copy.deepcopy(post)}], followers=[None])
                         for f in (-123, -122)]}
        self.players = [{"playerIndex": 0}]
        self.row = dict(source_frame="-122", executed_frames="2", rng="123",
                        p0_present="1", p0f_present="0", p0_action="14",
                        p0_x="1", p0_y="0", p0_facing="1", p0_damage="0",
                        p0_shield="60", p0_self_vx="0", p0_self_vy="0",
                        p0_attack_vx="0", p0_attack_vy="0", p0_hitlag="0",
                        p0_anim_frame="2", p0_ground_id="0", p0_stocks="4",
                        p0_jumps="2", p0_airborne="0")

    def test_recovered_intermediate_divergence_is_endpoint_pass(self):
        early = {**self.row, "source_frame": "-123", "p0_x": "2"}
        self.assertEqual(first_divergence(self.replay, self.players,
                                         [early, self.row])["field"], "x")
        self.assertIsNone(final_state_divergence(self.replay, self.players, [self.row]))

    def test_final_mismatch_is_failure(self):
        row = {**self.row, "p0_stocks": "3"}
        self.assertEqual(final_state_divergence(self.replay, self.players, [row])["field"],
                         "stocks")

    def test_last_frame_label_cannot_hide_skipped_inputs(self):
        row = {**self.row, "executed_frames": "1"}
        self.assertEqual(final_state_divergence(self.replay, self.players, [row])["field"],
                         "executed-frame-count")

    def test_requires_exactly_one_endpoint(self):
        for rows in ([], [self.row, self.row]):
            self.assertEqual(final_state_divergence(self.replay, self.players, rows)["field"],
                             "endpoint-row-count")

    def test_frame_start_rng_is_not_final_state(self):
        row = {**self.row, "rng": "456"}
        self.assertIsNone(final_state_divergence(self.replay, self.players, [row]))


if __name__ == "__main__":
    unittest.main()
