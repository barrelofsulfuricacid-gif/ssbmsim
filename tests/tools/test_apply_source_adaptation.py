"""Tests for deterministic native source adaptations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from apply_source_adaptation import (  # noqa: E402
    CLAIM_BOUNDARY,
    apply_adaptation,
    prepare_header_adaptations,
    verify_native_dependencies,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spec(source: bytes, adapted: bytes, count: int = 1) -> dict[str, object]:
    return {
        "schema": 1,
        "claim_boundary": CLAIM_BOUNDARY,
        "source_path": "src/example.c",
        "source_sha256": digest(source),
        "adapted_sha256": digest(adapted),
        "replacements": [
            {
                "old": "guest_word",
                "new": "host_word",
                "count": count,
                "reason": "preserve the value on the native host",
            }
        ],
    }


class SourceAdaptationTests(unittest.TestCase):
    def test_exact_replacement_is_byte_deterministic(self) -> None:
        source = b"guest_word + guest_word\n"
        adapted = b"host_word + host_word\n"
        self.assertEqual(apply_adaptation(source, spec(source, adapted, 2)), adapted)

    def test_source_drift_fails_closed(self) -> None:
        source = b"guest_word\n"
        adapted = b"host_word\n"
        with self.assertRaisesRegex(ValueError, "input hash mismatch"):
            apply_adaptation(b"guest_word changed\n", spec(source, adapted))

    def test_replacement_count_drift_fails_closed(self) -> None:
        source = b"guest_word + guest_word\n"
        adapted = b"host_word + host_word\n"
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            apply_adaptation(source, spec(source, adapted, 1))

    def test_output_hash_drift_fails_closed(self) -> None:
        source = b"guest_word\n"
        adaptation = spec(source, b"wrong\n")
        with self.assertRaisesRegex(ValueError, "output hash mismatch"):
            apply_adaptation(source, adaptation)

    def test_native_dependency_is_hash_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "src/native_numeric.h"
            dependency.parent.mkdir(parents=True)
            dependency.write_bytes(b"native helper\n")
            adaptation = {
                "native_dependencies": [
                    {
                        "path": "src/native_numeric.h",
                        "sha256": digest(dependency.read_bytes()),
                    }
                ]
            }
            self.assertEqual(
                verify_native_dependencies(adaptation, root),
                [
                    {
                        "path": "src/native_numeric.h",
                        "sha256": digest(dependency.read_bytes()),
                    }
                ],
            )

    def test_native_dependency_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "src/native_numeric.h"
            dependency.parent.mkdir(parents=True)
            dependency.write_bytes(b"changed\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_native_dependencies(
                    {
                        "native_dependencies": [
                            {
                                "path": "src/native_numeric.h",
                                "sha256": digest(b"expected\n"),
                            }
                        ]
                    },
                    root,
                )

    def test_native_dependency_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsafe native dependency"):
                verify_native_dependencies(
                    {
                        "native_dependencies": [
                            {"path": "../outside.h", "sha256": "0" * 64}
                        ]
                    },
                    Path(directory),
                )

    def test_header_adaptation_materializes_a_pinned_include(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            decomp = root / "decomp"
            spec_dir = root / "spec"
            output = root / "output"
            source_path = decomp / "src/melee/ft/types.h"
            consumer_path = decomp / "src/melee/ft/consumer.c"
            adaptation_path = spec_dir / "host_adaptations/ft_types.json"
            source_path.parent.mkdir(parents=True)
            adaptation_path.parent.mkdir(parents=True)
            source = b"guest_word\n"
            adapted = b"host_word\n"
            source_path.write_bytes(source)
            consumer_path.write_bytes(b'#include "types.h"\n')
            adaptation = spec(source, adapted)
            adaptation["source_path"] = "src/melee/ft/types.h"
            adaptation_bytes = (
                json.dumps(adaptation, indent=2).encode("utf-8") + b"\n"
            )
            adaptation_path.write_bytes(adaptation_bytes)
            import_spec = {
                "header_adaptations": [
                    {
                        "path": "src/melee/ft/types.h",
                        "force_include_sources": [
                            "src/melee/ft/consumer.c"
                        ],
                        "host_adaptation": {
                            "path": "host_adaptations/ft_types.json",
                            "sha256": digest(adaptation_bytes),
                        },
                    }
                ]
            }

            manifest = prepare_header_adaptations(
                import_spec,
                decomp=decomp,
                spec_dir=spec_dir,
                output_root=output,
            )

            self.assertEqual((output / "melee/ft/types.h").read_bytes(), adapted)
            self.assertEqual(manifest[0]["include_path"], "melee/ft/types.h")
            self.assertEqual(manifest[0]["adapted_sha256"], digest(adapted))
            self.assertEqual(
                manifest[0]["force_include_sources"],
                ["src/melee/ft/consumer.c"],
            )
            output_path = output / "melee/ft/types.h"
            initial_mtime = output_path.stat().st_mtime_ns
            prepare_header_adaptations(
                import_spec,
                decomp=decomp,
                spec_dir=spec_dir,
                output_root=output,
            )
            self.assertEqual(output_path.stat().st_mtime_ns, initial_mtime)

    def test_header_adaptation_rejects_a_path_outside_src(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "unsafe adapted header"):
                prepare_header_adaptations(
                    {
                        "header_adaptations": [
                            {
                                "path": "../types.h",
                                "host_adaptation": {},
                            }
                        ]
                    },
                    decomp=root,
                    spec_dir=root,
                    output_root=root / "output",
                )


if __name__ == "__main__":
    unittest.main()
