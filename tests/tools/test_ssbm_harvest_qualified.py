#!/usr/bin/env python3
"""Unit tests for the qualified-replay harvest tool."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ssbm_harvest_qualified as harvest  # noqa: E402


def pass_report(**overrides: object) -> dict:
    report = {
        "schema": 2,
        "replay_sha256": "ab" * 32,
        "asset_pack_sha256": "cd" * 32,
        "runner_sha256": "ef" * 32,
        "stage_id": 31,
        "character_ids": [0, 9],
        "source_frames": 1000,
        "native_frames": 1000,
        "runner_exit_code": 0,
        "first_divergence": None,
        "complete_exact": True,
    }
    report.update(overrides)
    return report


class HarvestTests(unittest.TestCase):
    def run_harvest(self, files: dict[str, object]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "build" / "ssbm-native").mkdir(parents=True)
            for name, payload in files.items():
                path = root / "build" / "ssbm-native" / name
                if isinstance(payload, str):
                    path.write_text(payload, encoding="utf-8")
                else:
                    path.write_text(json.dumps(payload), encoding="utf-8")
            return harvest.harvest(("build/ssbm-native/*.json",), root)

    def test_groups_repeat_passes_by_content_hash(self) -> None:
        result = self.run_harvest(
            {"a.json": pass_report(), "b.json": pass_report(runner_sha256="12" * 32)}
        )
        self.assertEqual(result["distinct_replays"], 1)
        entry = result["qualified"][0]
        self.assertEqual(entry["report_count"], 2)
        self.assertEqual(len(entry["runner_sha256"]), 2)

    def test_ignores_non_pass_and_non_dict_reports(self) -> None:
        failing = pass_report(complete_exact=False)
        result = self.run_harvest(
            {
                "pass.json": pass_report(),
                "fail.json": failing,
                "list.json": [1, 2, 3],
                "broken.json": "{not json",
            }
        )
        self.assertEqual(result["distinct_replays"], 1)
        self.assertEqual(result["reports_scanned"], 2)

    def test_frame_mismatch_is_hard_failure(self) -> None:
        with self.assertRaises(ValueError):
            self.run_harvest(
                {"a.json": pass_report(native_frames=999)},
            )

    def test_conflicting_identity_is_hard_failure(self) -> None:
        with self.assertRaises(ValueError):
            self.run_harvest(
                {
                    "a.json": pass_report(),
                    "b.json": pass_report(stage_id=32),
                }
            )

    def test_missing_hash_is_hard_failure(self) -> None:
        report = pass_report()
        del report["replay_sha256"]
        with self.assertRaises(ValueError):
            self.run_harvest({"a.json": report})


if __name__ == "__main__":
    unittest.main()
