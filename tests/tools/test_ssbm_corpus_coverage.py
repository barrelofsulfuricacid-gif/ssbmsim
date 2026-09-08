#!/usr/bin/env python3
"""Unit tests for the acceptance-corpus admission and coverage audit."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ssbm_corpus_coverage as coverage  # noqa: E402


def base_manifest() -> dict:
    with open(ROOT / "tools" / "ssbm_acceptance_corpus.json", encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["qualified"] = []
    return manifest


def valid_entry(**overrides: object) -> dict:
    entry = {
        "sha256": "aa" * 32,
        "slippi_version": "3.4.0",
        "players": 2,
        "characters": [0, 19],
        "ports": [1, 2],
        "stage_id": 32,
        "frozen_pokemon_stadium": False,
        "items_off": True,
        "start_frame": -123,
        "end_frame": 5000,
        "complete": True,
        "ucf_evidence": "UCF 0.84 ports 1-2 default config",
        "source": "fixture",
        "result": "pending",
    }
    entry.update(overrides)
    return entry


class CorpusCoverageTests(unittest.TestCase):
    def test_pinned_tables_match_oracle_reference(self) -> None:
        manifest = base_manifest()
        # Pinned slippi-js external IDs: 17 is Yoshi, 14 is Ice Climbers.
        # The libmelee-internal-ID bucket trap must never conflate them.
        self.assertEqual(manifest["required_characters"]["17"], "Yoshi")
        self.assertEqual(manifest["required_characters"]["14"], "Ice Climbers")
        self.assertEqual(set(map(int, manifest["required_characters"])), set(range(26)))
        self.assertEqual(manifest["required_characters"]["18"], "Zelda")
        self.assertEqual(manifest["required_characters"]["19"], "Sheik")
        self.assertEqual(
            sorted(map(int, manifest["admission"]["stage_ids"])),
            [2, 3, 8, 28, 31, 32],
        )

    def test_valid_entry_is_admitted(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry()]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["admitted"], 1)
        self.assertIn("0", report["covered_characters"])
        self.assertIn("19", report["covered_characters"])
        self.assertIn("32", report["covered_stages"])

    def test_rejects_non_legal_stage(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry(stage_id=5)]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["admitted"], 0)
        self.assertTrue(any("stage_id" in v for v in report["violations"]))

    def test_rejects_items_on(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry(items_off=False)]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["admitted"], 0)
        self.assertTrue(any("items_off" in v for v in report["violations"]))

    def test_rejects_unfrozen_pokemon_stadium(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [
            valid_entry(stage_id=3, frozen_pokemon_stadium=False)
        ]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["admitted"], 0)
        self.assertTrue(any("frozen" in v for v in report["violations"]))

    def test_accepts_frozen_pokemon_stadium(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [
            valid_entry(stage_id=3, frozen_pokemon_stadium=True)
        ]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["violations"], [])
        self.assertIn("3", report["covered_stages"])

    def test_rejects_truncated_match(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry(complete=False)]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["admitted"], 0)

    def test_rejects_duplicate_content_hash(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry(), valid_entry()]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["admitted"], 1)
        self.assertTrue(any("duplicate" in v for v in report["violations"]))

    def test_coverage_matrix_reports_missing_roster(self) -> None:
        manifest = base_manifest()
        manifest["qualified"] = [valid_entry()]
        report = coverage.audit_manifest(manifest)
        self.assertIn("2", report["missing_characters"])  # Fox not yet covered
        self.assertIn("25", report["missing_characters"])  # Ganondorf
        self.assertIn("31", report["missing_stages"])  # Battlefield


if __name__ == "__main__":
    unittest.main()
