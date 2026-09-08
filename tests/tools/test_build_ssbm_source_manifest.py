"""Tests for native source-manifest port-evidence boundaries."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build_ssbm_source_manifest import (  # noqa: E402
    candidate,
    module_for,
    port_evidence,
    record_source_hash,
    source_relative,
)


class SourceManifestPortEvidenceTests(unittest.TestCase):
    def test_dolphin_matrix_support_source_uses_real_checkout_path(self) -> None:
        self.assertEqual(module_for("dolphin/mtx/mtx.c"), "dolphin/mtx")
        self.assertTrue(candidate("dolphin/mtx"))
        self.assertEqual(
            source_relative("dolphin/mtx/mtx.c"),
            "extern/dolphin/src/dolphin/mtx/mtx.c",
        )

    def test_source_file_is_hashed_once_across_repeated_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.c"
            path.write_bytes(b"source")
            hashes: dict[str, str] = {}
            with mock.patch(
                "build_ssbm_source_manifest.sha256", return_value="digest"
            ) as hash_file:
                record_source_hash(hashes, "src/source.c", path)
                record_source_hash(hashes, "src/source.c", path)
            self.assertEqual(hashes, {"src/source.c": "digest"})
            hash_file.assert_called_once_with(path)

    def test_blocked_selected_source_requires_host_adaptation(self) -> None:
        readiness = {
            "src/example.c": {
                "compile_status": "blocked",
                "sha256": "0" * 64,
                "blocker": "strict-warning",
            }
        }
        with self.assertRaisesRegex(ValueError, "not compile-ready"):
            port_evidence(
                "src/example.c",
                "gm",
                readiness,
                {"src/example.c": {"path": "src/example.c"}},
                {},
                "1" * 64,
            )

    def test_host_adapted_selection_remains_distinct_from_ready_source(self) -> None:
        adaptation = {
            "path": "host_adaptations/example.json",
            "sha256": "2" * 64,
        }
        readiness = {
            "src/example.c": {
                "compile_status": "blocked",
                "sha256": "0" * 64,
                "blocker": "strict-warning",
            }
        }
        status, evidence = port_evidence(
            "src/example.c",
            "gm",
            readiness,
            {
                "src/example.c": {
                    "path": "src/example.c",
                    "host_adaptation": adaptation,
                }
            },
            {},
            "1" * 64,
        )
        self.assertEqual(status, "selected-native-import-host-adapted")
        self.assertEqual(evidence["compile_status"], "blocked")
        self.assertEqual(evidence["host_adaptation"], adaptation)

    def test_rooted_host_adaptation_records_function_scope(self) -> None:
        adaptation = {
            "path": "host_adaptations/example.json",
            "sha256": "2" * 64,
        }
        readiness = {
            "src/example.c": {
                "compile_status": "blocked",
                "sha256": "0" * 64,
                "blocker": "strict-warning",
            }
        }
        status, evidence = port_evidence(
            "src/example.c",
            "gm",
            readiness,
            {
                "src/example.c": {
                    "path": "src/example.c",
                    "roots": ["source_root"],
                    "host_adaptation": adaptation,
                }
            },
            {},
            "1" * 64,
        )
        self.assertEqual(
            status, "selected-rooted-native-import-host-adapted"
        )
        self.assertEqual(evidence["native_import_roots"], ["source_root"])

    def test_provider_exclusion_is_explicit_manifest_evidence(self) -> None:
        exclusion = {
            "path": "src/movie.c",
            "sha256": "0" * 64,
            "scope": "noncompetitive-presentation",
            "reason": "THP movie output",
        }
        readiness = {
            "src/movie.c": {
                "compile_status": "ready",
                "sha256": "0" * 64,
                "blocker": None,
            }
        }
        status, evidence = port_evidence(
            "src/movie.c",
            "lb",
            readiness,
            {},
            {"src/movie.c": exclusion},
            "1" * 64,
        )
        self.assertEqual(
            status, "host-object-excluded-from-native-provider-inventory"
        )
        self.assertEqual(evidence["provider_exclusion"], exclusion)


if __name__ == "__main__":
    unittest.main()
