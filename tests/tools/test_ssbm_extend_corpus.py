import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from ssbm_extend_corpus import preserve_provenance, select_entries, verified_failure
from ssbm_native_full_match import ReplayError


class CorpusSelectionTests(unittest.TestCase):
    def test_revalidation_preserves_pinned_archive_provenance(self):
        previous = {"source": "pinned archive", "source_provenance": {"revision": "abc", "member": "a.slp"},
                    "end_frame": 100, "nonpassing_admission": {"runner_sha256": "admission-build"}}
        refreshed = {"source": "generic folder", "end_frame": 101}
        entry = preserve_provenance(refreshed, previous)
        self.assertEqual(entry["source_provenance"], previous["source_provenance"])
        self.assertEqual(entry["source"], "pinned archive")
        self.assertEqual(entry["nonpassing_admission"], previous["nonpassing_admission"])
        self.assertEqual(entry["end_frame"], 101)

    def test_missing_roster_is_prioritized_and_remaining_slots_reserved(self):
        manifest = {"required_match_count": 4, "required_characters": {"0": "a", "1": "b", "2": "c"},
                    "qualified": [{"sha256": "old", "characters": [0]}]}
        entries = {name: {"sha256": name, "characters": [char]} for name, char in
                   [("old", 0), ("common1", 0), ("common2", 0), ("rare", 1)]}
        with contextlib.redirect_stdout(io.StringIO()):
            selected, _ = select_entries(manifest, [(Path(n), n) for n in entries],
                                         lambda path, digest: entries[digest], allow_partial=True)
        self.assertEqual({e["sha256"] for e in selected}, {"old", "common1", "rare"})
        self.assertEqual(manifest["required_match_count"], 4)

    def test_partial_additions_keep_full_target(self):
        manifest = {"required_match_count": 200, "qualified": [{"sha256": "old"}]}
        with contextlib.redirect_stdout(io.StringIO()):
            entries, _ = select_entries(manifest, [(Path("old"), "old"), (Path("failure"), "failure")],
                                        lambda path, digest: {"sha256": digest}, allow_partial=True)
        self.assertEqual(len(entries), 2)
        self.assertEqual(manifest["required_match_count"], 200)

    def test_only_current_simulator_failure_is_eligible(self):
        identity = {k: k for k in ("runner_sha256", "asset_pack_sha256", "comparator_sha256", "extractor_sha256", "parser_sha256", "sweep_sha256")}
        report = {"schema": 2, "replay_sha256": "replay", "complete_exact": False,
                  "comparison_scope": "final-state",
                  "source_frames": 100, "runner_exit_code": 0,
                  "first_divergence": {"frame": 0, "field": "x"},
                  **identity, "sweep_cache_identity": {**identity, "comparison_scope": "final-state"}}
        self.assertTrue(verified_failure(report, "replay", identity))
        for key in ('parser_sha256', 'sweep_sha256'):
            stale = {**report, 'sweep_cache_identity': {**report['sweep_cache_identity'], key: 'old'}}
            self.assertFalse(verified_failure(stale, 'replay', identity))
        for replacement in ({"complete_exact": True}, {"runner_sha256": "old"},
                            {"comparison_scope": "all-frames"},
                            {"configuration_error": "items enabled"}, {"source_frames": 0},
                            {"first_divergence": None}, {"sweep_cache_identity": {}}):
            with self.subTest(replacement=replacement):
                self.assertFalse(verified_failure({**report, **replacement}, "replay", identity))

    def select(self, names, reject=()):
        manifest = {"required_match_count": 4,
                    "qualified": [{"sha256": "old-pass"}, {"sha256": "old-failure"}]}
        def admit(path, digest):
            if digest in reject:
                raise ReplayError("inadmissible settings")
            return {"sha256": digest}
        with contextlib.redirect_stdout(io.StringIO()):
            return select_entries(manifest, ((Path(n), n) for n in names), admit)

    def test_reserves_capacity_for_existing_failed_replay(self):
        entries, _ = self.select(["new1", "new1", "new2", "new3", "old-pass", "old-failure"])
        self.assertEqual({e["sha256"] for e in entries}, {"new1", "new2", "old-pass", "old-failure"})

    def test_admission_rejection_does_not_fill_capacity(self):
        entries, rejected = self.select(["bad", "new1", "new2", "old-pass", "old-failure"], ["bad"])
        self.assertEqual(len(entries), 4)
        self.assertEqual(rejected[0]["sha256"], "bad")

    def test_existing_replay_cannot_be_dropped_on_revalidation(self):
        with self.assertRaisesRegex(ValueError, "protected replay no longer admits"):
            self.select(["old-pass", "old-failure", "new1", "new2"], ["old-failure"])

    def test_missing_protected_hash_fails(self):
        with self.assertRaisesRegex(ValueError, "omitted protected"):
            self.select(["old-pass", "new1", "new2", "new3", "new4"])


if __name__ == "__main__":
    unittest.main()
