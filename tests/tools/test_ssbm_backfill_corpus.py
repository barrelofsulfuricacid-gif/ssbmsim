#!/usr/bin/env python3
"""Unit tests for the acceptance-corpus backfill from parser evidence."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ssbm_backfill_corpus as backfill  # noqa: E402
import ssbm_corpus_coverage as coverage  # noqa: E402


def cached_replay(**overrides: object) -> dict:
    settings: dict = {
        "slpVersion": "3.17.0",
        "stageId": 31,
        "isFrozenPS": False,
        "isPAL": False,
        "isTeams": False,
        "itemSpawnBehavior": 255,
        "randomSeed": 42,
        "players": [
            {
                "playerIndex": 0,
                "characterId": 2,
                "characterColor": 0,
                "type": 0,
                "controllerFix": "UCF",
                "startStocks": 4,
            },
            {
                "playerIndex": 1,
                "characterId": 0,
                "characterColor": 0,
                "type": 0,
                "controllerFix": "UCF",
                "startStocks": 4,
            },
        ],
    }
    settings.update(overrides.pop("settings", {}))
    frames = [
        {"frame": number, "startSeed": 1, "players": [{}, {}], "followers": [{}, {}]}
        for number in range(-123, 10)
    ]
    replay = {
        "settings": settings,
        "frames": frames,
        "gameEnd": {"gameEndMethod": 2},
        "inputProvenance": {
            "exactRawMainX": True,
            "exactRawMainY": True,
            "exactRawCX": True,
            "exactRawCY": True,
        },
    }
    replay.update(overrides)
    return {"schema": 2, "replay_sha256": "ab" * 32, "replay": replay}


def write_cache(tmp: Path, digest: str, blob: dict) -> Path:
    cache = tmp / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{digest}.json"
    path.write_text(json.dumps(blob), encoding="utf-8")
    return cache


class BackfillTest(unittest.TestCase):
    def test_frozen_corpus_cannot_be_replaced_by_pass_harvest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            original = '{"selection": {"frozen": true}, "qualified": []}'
            manifest.write_text(original)
            with self.assertRaisesRegex(backfill.BackfillError, "frozen acceptance corpus"):
                backfill.main(["--manifest", str(manifest), "--write"])
            self.assertEqual(manifest.read_text(), original)

    def test_builds_pending_entry(self) -> None:
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            cache = write_cache(tmp, digest, cached_replay())
            entry = backfill.build_entry(digest, cache, {}, bucket="ranked-a6-raw-c")
            self.assertEqual(entry["sha256"], digest)
            self.assertEqual(entry["characters"], [2, 0])
            self.assertEqual(entry["stage_id"], 31)
            self.assertEqual(entry["start_frame"], -123)
            self.assertEqual(entry["result"], "pending")
            self.assertTrue(entry["items_off"])
            self.assertTrue(entry["complete"])

    def test_backfilled_entries_pass_fail_closed_audit(self) -> None:
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            cache = write_cache(tmp, digest, cached_replay())
            entry = backfill.build_entry(digest, cache, {}, bucket="ranked-a6-raw-c")
        with open(ROOT / "tools" / "ssbm_acceptance_corpus.json",
                  encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest = copy.deepcopy(manifest)
        manifest["qualified"] = [entry]
        report = coverage.audit_manifest(manifest)
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["admitted"], 1)

    def test_rejects_items_enabled(self) -> None:
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            cache = write_cache(
                tmp, digest, cached_replay(settings={"itemSpawnBehavior": 3})
            )
            with self.assertRaises(backfill.BackfillError):
                backfill.build_entry(digest, cache, {}, bucket="ranked-a6-raw-c")

    def test_rejects_unfrozen_stadium(self) -> None:
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            cache = write_cache(
                tmp,
                digest,
                cached_replay(settings={"stageId": 3, "isFrozenPS": False}),
            )
            with self.assertRaises(backfill.BackfillError):
                backfill.build_entry(digest, cache, {}, bucket="ranked-a6-raw-c")

    def test_rejects_non_ucf(self) -> None:
        blob = cached_replay()
        blob["replay"]["settings"]["players"][0]["controllerFix"] = "None"
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            cache = write_cache(tmp, digest, blob)
            with self.assertRaises(backfill.BackfillError):
                backfill.build_entry(digest, cache, {}, bucket="ranked-a6-raw-c")


if __name__ == "__main__":
    unittest.main()
