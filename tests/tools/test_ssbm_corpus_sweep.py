"""Unit tests for tools/ssbm_corpus_sweep.py (cached-report path only)."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SWEEP = ROOT / "tools" / "ssbm_corpus_sweep.py"
sys.path.insert(0, str(ROOT / "tools"))
import ssbm_corpus_sweep as sweep


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_parser(directory):
    prefix = directory / 'parser'
    package = prefix / 'node_modules/@slippi/slippi-js'
    package.mkdir(parents=True)
    (package / 'package.json').write_text('{"version":"fixture"}')
    return prefix


class CorpusSweepTest(unittest.TestCase):
    def test_duplicate_content_rejects_manifest_and_removes_old_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            prefix = make_parser(directory)
            replay, duplicate = directory / "a.slp", directory / "b.slp"
            replay.write_bytes(b"same replay")
            duplicate.write_bytes(replay.read_bytes())
            listing = directory / "list.txt"
            listing.write_text(f"{replay}\n{duplicate}\n")
            runner, pack = directory / "runner", directory / "pack"
            runner.write_bytes(b"runner")
            pack.write_bytes(b"pack")
            output = directory / "output"
            output.mkdir()
            summary = output / "summary.json"
            summary.write_text('{"passes": 200}')
            proc = subprocess.run(
                [sys.executable, str(SWEEP), "--replay-list", str(listing),
                 "--runner", str(runner), "--asset-pack", str(pack),
                 "--parser-prefix", str(prefix), "--out-dir", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("duplicate replay content", proc.stderr)
            self.assertFalse(summary.exists())

    def test_cached_reports_classified_without_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            prefix = make_parser(tmpdir)
            replay_a = tmpdir / "a.slp"
            replay_b = tmpdir / "b.slp"
            replay_a.write_bytes(b"fake-replay-a")
            replay_b.write_bytes(b"fake-replay-b")
            out_dir = tmpdir / "out"
            out_dir.mkdir()
            runner = tmpdir / "runner"
            runner.write_bytes(b"runner")
            pack = tmpdir / "pack"
            pack.write_bytes(b"pack")
            cache_dir = tmpdir / "cache"
            cache_dir.mkdir()
            identity = sweep.tool_identity(runner, pack, prefix)
            for replay in (replay_a, replay_b):
                (cache_dir / f"{digest(replay)}.endpoint.json").write_bytes(b"extracted")
            common = {
                "schema": 2,
                "comparison_scope": "final-state", "arithmetic_profile": 0,
                "runner_sha256": digest(runner),
                "asset_pack_sha256": digest(pack),
                "sweep_cache_identity": {
                    **identity,
                    "comparison_scope": "final-state", "arithmetic_profile": 0,
                    "extracted_replay_sha256": hashlib.sha256(b"extracted").hexdigest(),
                },
            }
            out_dir.joinpath(f"{digest(replay_a)}.json").write_text(
                json.dumps(
                    {
                        **common,
                        "replay_sha256": digest(replay_a),
                        "complete_exact": True,
                        "stage_id": 31,
                        "character_ids": [0, 9],
                    }
                ),
                encoding="utf-8",
            )
            out_dir.joinpath(f"{digest(replay_b)}.json").write_text(
                json.dumps(
                    {
                        **common,
                        "replay_sha256": digest(replay_b),
                        "complete_exact": False,
                        "stage_id": 31,
                        "character_ids": [0, 9],
                        "first_divergence": {"frame": 10, "field": "x"},
                    }
                ),
                encoding="utf-8",
            )
            replay_list = tmpdir / "list.txt"
            replay_list.write_text(
                f"{replay_a}\n{replay_b}\n", encoding="utf-8"
            )
            runner = tmpdir / "runner"
            runner.write_bytes(b"runner")
            pack = tmpdir / "pack"
            pack.write_bytes(b"pack")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SWEEP),
                    "--replay-list",
                    str(replay_list),
                    "--runner",
                    str(runner),
                    "--asset-pack",
                    str(pack),
                    "--parser-prefix",
                    str(prefix),
                    "--out-dir",
                    str(out_dir),
                    "--cache-dir",
                    str(cache_dir),
                    "--jobs",
                    "2",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
            summary = json.loads(
                (out_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["passes"], 1)
            self.assertEqual(summary["nonpasses"], 1)
            self.assertEqual(summary["first_divergence_fields"], {"x": 1})

    def test_stale_identity_cannot_survive_failed_rerun(self) -> None:
        for changed in ("runner_sha256", "asset_pack_sha256", "comparator_sha256",
                        "extractor_sha256", "sweep_sha256", "extracted_replay_sha256",
                        "comparison_scope",
                        "arithmetic_profile", "comparison_scope", "legacy"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                prefix = make_parser(directory)
                replay, runner, pack = [directory / name for name in ("r.slp", "runner", "pack")]
                for path in (replay, runner, pack):
                    path.write_bytes(path.name.encode())
                cache = directory / "cache"
                out = directory / "out"
                cache.mkdir()
                out.mkdir()
                extracted = cache / f"{digest(replay)}.endpoint.json"
                extracted.write_bytes(b"extracted")
                identity = sweep.tool_identity(runner, pack, prefix)
                cached_identity = {**identity, "extracted_replay_sha256": digest(extracted),
                                   "comparison_scope": "final-state", "arithmetic_profile": 0}
                cached_identity[changed] = "obsolete"
                report = {"schema": 2, "replay_sha256": digest(replay),
                          "comparison_scope": "final-state", "arithmetic_profile": 0,
                          "runner_sha256": digest(runner), "asset_pack_sha256": digest(pack),
                          "complete_exact": True, "sweep_cache_identity": cached_identity}
                if changed == "legacy":
                    del report["sweep_cache_identity"]
                report_path = out / f"{digest(replay)}.json"
                report_path.write_text(json.dumps(report))
                with patch.object(sweep.subprocess, "run", return_value=
                                  subprocess.CompletedProcess([], 1, "", "failed")) as child:
                    result = sweep.run_one(replay, runner, pack, str(prefix), "node", cache, out)
                child.assert_called_once()
                self.assertEqual(result["status"], "no-report")
                self.assertFalse(report_path.exists())


if __name__ == "__main__":
    unittest.main()
