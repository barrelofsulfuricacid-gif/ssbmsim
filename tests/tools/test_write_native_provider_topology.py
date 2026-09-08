"""Tests for timestamp-stable native host-provider topology fingerprints."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from write_native_provider_topology import (  # noqa: E402
    encode_topology,
    write_if_changed,
)


class NativeProviderTopologyTests(unittest.TestCase):
    def test_encoding_tracks_symbols_and_provider_labels_only(self) -> None:
        with mock.patch(
            "write_native_provider_topology.read_object_list",
            return_value=[Path("/tmp/b.o"), Path("/tmp/a.o")],
        ), mock.patch(
            "write_native_provider_topology.external_definition_index",
            return_value={"alpha": ("a.o",), "shared": ("a.o", "b.o")},
        ):
            payload = json.loads(
                encode_topology(Path("objects.txt"), nm=Path("nm"))
            )
        self.assertEqual(payload["objects"], ["a.o", "b.o"])
        self.assertEqual(
            payload["definitions"],
            [
                {"provider_objects": ["a.o"], "symbol": "alpha"},
                {
                    "provider_objects": ["a.o", "b.o"],
                    "symbol": "shared",
                },
            ],
        )

    def test_identical_content_preserves_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "topology.json"
            self.assertTrue(write_if_changed(output, b"first\n"))
            timestamp = output.stat().st_mtime_ns
            self.assertFalse(write_if_changed(output, b"first\n"))
            self.assertEqual(output.stat().st_mtime_ns, timestamp)
            self.assertTrue(write_if_changed(output, b"second\n"))
            self.assertEqual(output.read_bytes(), b"second\n")


if __name__ == "__main__":
    unittest.main()
