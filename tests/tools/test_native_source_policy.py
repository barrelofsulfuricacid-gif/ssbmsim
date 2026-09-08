"""Tests for pinned native source compiler exceptions."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from native_source_policy import (  # noqa: E402
    CLAIM_BOUNDARY,
    options_by_path,
    source_compile_options,
)


class NativeSourcePolicyTests(unittest.TestCase):
    def test_policy_is_hash_pinned_and_source_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/melee/ft/example.c"
            source.parent.mkdir(parents=True)
            source.write_text("void example(void) {}\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            spec = {
                "source_compile_options": [
                    {
                        "path": "src/melee/ft/example.c",
                        "source_sha256": digest,
                        "options": ["-Wno-type-limits"],
                        "evidence": {"reason": "proved host-only diagnostic"},
                        "claim_boundary": CLAIM_BOUNDARY,
                    }
                ]
            }
            entries = source_compile_options(spec, decomp=root)
            self.assertEqual(
                options_by_path(entries),
                {"src/melee/ft/example.c": ("-Wno-type-limits",)},
            )

    def test_policy_rejects_semantic_compiler_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/melee/ft/example.c"
            source.parent.mkdir(parents=True)
            source.write_text("void example(void) {}\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            spec = {
                "source_compile_options": [
                    {
                        "path": "src/melee/ft/example.c",
                        "source_sha256": digest,
                        "options": ["-fno-strict-aliasing"],
                        "evidence": {"reason": "not sufficient"},
                        "claim_boundary": CLAIM_BOUNDARY,
                    }
                ]
            }
            with self.assertRaisesRegex(ValueError, "invalid source compile options"):
                source_compile_options(spec, decomp=root)

    def test_policy_accepts_pinned_dolphin_matrix_support_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "extern/dolphin/src/dolphin/mtx/mtx.c"
            source = root / relative
            source.parent.mkdir(parents=True)
            source.write_text("void matrix(void) {}\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            spec = {
                "source_compile_options": [
                    {
                        "path": relative,
                        "source_sha256": digest,
                        "options": ["-Wno-array-parameter"],
                        "evidence": {"reason": "pinned SDK header diagnostic"},
                        "claim_boundary": CLAIM_BOUNDARY,
                    }
                ]
            }
            self.assertEqual(
                options_by_path(source_compile_options(spec, decomp=root)),
                {relative: ("-Wno-array-parameter",)},
            )
