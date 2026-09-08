"""Focused checks for the GALE01 CPU switch-predicate adaptation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from apply_source_adaptation import apply_adaptation  # noqa: E402


class FtCoCpuSwitchAdaptationTests(unittest.TestCase):
    def test_call_site_values_are_explicit_and_complete(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_0A01.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))
        replacements = adaptation["replacements"]

        self.assertEqual(adaptation["evidence"]["dol_sha1"],
                         "08e0bf20134dfcb260699671004527b2d6bb1a45")
        switch_replacements = [entry for entry in replacements
                               if "ftCo_800ADE48(" in entry["old"]]
        self.assertEqual([entry["count"] for entry in switch_replacements],
                         [1, 1, 1, 33])
        self.assertIn("s32 switch_cmd", switch_replacements[0]["new"])
        self.assertIn("arg2", switch_replacements[1]["new"])
        self.assertIn("false", switch_replacements[2]["new"])
        self.assertIn("true", switch_replacements[3]["new"])
        self.assertTrue(any('#include "native_numeric.h"' in entry["new"]
                            for entry in replacements))
        self.assertEqual(sum(entry["new"].count("(float) PF_SlippiMulAddF64(")
                             for entry in replacements), 2)
        self.assertTrue(any("static inline s32 ftCo_800A3908_inline1" in entry["new"]
                            for entry in replacements))

    def test_pinned_decomp_source_materializes_expected_calls(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_0A01.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root:
            self.skipTest("requires PF_SSBM_DECOMP_SOURCE_DIR")
        source = Path(source_root) / adaptation["source_path"]
        adapted = apply_adaptation(source.read_bytes(), adaptation).decode("utf-8")

        self.assertNotIn("s32 switch_cmd;", adapted)
        self.assertEqual(adapted.count("ftCo_800ADE48(fp, true);"), 33)
        self.assertEqual(adapted.count("ftCo_800ADE48(fp, false);"), 1)
        self.assertEqual(adapted.count("ftCo_800ADE48(fp, arg2);"), 1)
        self.assertNotIn("ftCo_800ADE48(fp);", adapted)


if __name__ == "__main__":
    unittest.main()
