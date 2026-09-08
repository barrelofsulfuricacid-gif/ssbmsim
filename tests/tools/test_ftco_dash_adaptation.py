"""Focused checks for the GALE01 dash-exit fused-arithmetic adaptation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from apply_source_adaptation import apply_adaptation  # noqa: E402


class FtCoDashAdaptationTests(unittest.TestCase):
    def test_dol_instruction_boundary_is_pinned(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_Dash.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(adaptation["evidence"]["dol_sha1"],
                         "08e0bf20134dfcb260699671004527b2d6bb1a45")
        self.assertIn("0x800CA508", adaptation["evidence"]["instructions"])
        self.assertIn("0x800CA518", adaptation["evidence"]["instructions"])

    def test_pinned_source_preserves_first_rounding_then_fuses(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_Dash.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root:
            self.skipTest("requires PF_SSBM_DECOMP_SOURCE_DIR")
        source = Path(source_root) / adaptation["source_path"]
        adapted = apply_adaptation(source.read_bytes(), adaptation).decode("utf-8")

        self.assertIn(
            "float temp_f0 = fp->gr_vel * p_ftCommonData->x54;", adapted)
        self.assertIn(
            "fp->gr_vel = PF_SlippiMulAddF32(-temp_f0, friction, fp->gr_vel);", adapted)
        self.assertNotIn("fp->gr_vel += -temp_f0 * friction;", adapted)


if __name__ == "__main__":
    unittest.main()
