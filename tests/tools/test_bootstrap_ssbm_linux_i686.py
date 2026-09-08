"""Tests for the pinned permission-free Linux i686 sysroot bootstrap."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from bootstrap_ssbm_linux_i686 import load_lock  # noqa: E402


class LinuxI686BootstrapTests(unittest.TestCase):
    def test_lock_parser_preserves_pinned_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "lock.tsv"
            lock.write_text(
                "name\turl\tbytes\tsha256\n"
                "package.deb\thttps://example.invalid/package.deb\t1\t"
                + "ab" * 32
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_lock(lock),
                [
                    {
                        "name": "package.deb",
                        "url": "https://example.invalid/package.deb",
                        "bytes": 1,
                        "sha256": "ab" * 32,
                    }
                ],
            )

    def test_lock_parser_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "lock.tsv"
            lock.write_text(
                "name\turl\tbytes\tsha256\n"
                "../package.deb\thttps://example.invalid/package.deb\t1\t"
                + "ab" * 32
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsafe or duplicate"):
                load_lock(lock)


if __name__ == "__main__":
    unittest.main()
