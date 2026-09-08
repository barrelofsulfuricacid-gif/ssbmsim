"""Audit multiplied ground-velocity accumulations across the pinned gameplay source."""

import json
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from apply_source_adaptation import apply_adaptation

ACCUMULATION = re.compile(r"\bgr_vel\s*\+=\s*[^;]*\*[^;]*;")


class GroundMomentumAdaptationTests(unittest.TestCase):
    def test_no_implicit_multiplied_accumulations_remain(self):
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root:
            self.skipTest("requires PF_SSBM_DECOMP_SOURCE_DIR")
        decomp = Path(source_root)
        adaptations = {}
        for path in (ROOT / "tools/host_adaptations").glob("*.json"):
            spec = json.loads(path.read_text())
            adaptations[spec["source_path"]] = spec
        residual = []
        original_sites = 0
        repaired_sources = set()
        for source in (decomp / "src/melee").rglob("*.c"):
            raw = source.read_bytes()
            matches = list(ACCUMULATION.finditer(raw.decode()))
            if not matches:
                continue
            original_sites += len(matches)
            relative = source.relative_to(decomp).as_posix()
            spec = adaptations.get(relative)
            if spec is None:
                residual.append(relative + ": no adaptation")
                continue
            adapted = apply_adaptation(raw, spec).decode()
            if ACCUMULATION.search(adapted):
                residual.append(relative + ": implicit accumulation remains")
            else:
                repaired_sources.add(relative)
        # Detect missing source trees or a scan that silently stops exercising
        # the existing class. New occurrences must also receive an audit.
        self.assertGreaterEqual(original_sites, 12)
        self.assertEqual(residual, [])
        self.assertGreaterEqual(len(repaired_sources), 5)


if __name__ == "__main__":
    unittest.main()
