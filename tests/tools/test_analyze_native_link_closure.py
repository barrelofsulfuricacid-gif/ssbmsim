#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_native_link_closure as closure  # noqa: E402


def unit(
    path: str,
    *,
    definitions: tuple[str, ...] = (),
    undefined: tuple[str, ...] = (),
) -> object:
    return closure.UnitSymbols(
        path=path,
        object_path=path + ".obj",
        object_sha256="0" * 64,
        definitions=definitions,
        undefined=undefined,
        weak_undefined=(),
    )


class NativeLinkClosureTests(unittest.TestCase):
    def test_parse_nm_separates_synthetic_and_weak_symbols(self) -> None:
        definitions, undefined, weak = closure.parse_nm_posix(
            ".refptr.target R 0\n"
            "target U\n"
            "implemented T 10\n"
            "optional w\n"
        )
        self.assertEqual(definitions, {"implemented"})
        self.assertEqual(undefined, {"target"})
        self.assertEqual(weak, {"optional"})

    def test_closure_follows_unique_transitive_ready_definitions(self) -> None:
        units = {
            "a.c": unit("a.c", definitions=("root",), undefined=("middle",)),
            "b.c": unit("b.c", definitions=("middle",), undefined=("leaf",)),
            "c.c": unit("c.c", definitions=("leaf",)),
        }
        report = closure.compute_closure(["a.c"], units, {})
        self.assertEqual(report["closure_units"], ["a.c", "b.c", "c.c"])
        self.assertEqual(len(report["dependency_edges"]), 2)
        self.assertEqual(report["unresolved_symbols"], [])
        self.assertEqual(report["ambiguous_symbols"], [])

    def test_manifest_owner_resolves_duplicate_ready_definitions(self) -> None:
        units = {
            "root.c": unit("root.c", undefined=("shared",)),
            "owner.c": unit("owner.c", definitions=("shared",)),
            "other.c": unit("other.c", definitions=("shared",)),
        }
        owners = {
            "shared": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-ready",
                    "symbol_type": "object",
                },
            )
        }
        report = closure.compute_closure(["root.c"], units, owners)
        self.assertEqual(report["closure_units"], ["owner.c", "root.c"])
        self.assertEqual(
            report["dependency_edges"][0]["selection"], "decomp-symbol-owner"
        )

    def test_missing_symbol_reports_blocked_source_owner(self) -> None:
        units = {"root.c": unit("root.c", undefined=("blocked",))}
        owners = {
            "blocked": (
                {
                    "path": "blocked.c",
                    "port_status": "host-object-blocked",
                    "symbol_type": "function",
                },
            )
        }
        report = closure.compute_closure(["root.c"], units, owners)
        self.assertEqual(
            report["unresolved_symbols"][0]["classification"],
            "blocked-source-provider",
        )

    def test_missing_symbol_distinguishes_host_adapted_source_owner(self) -> None:
        units = {"root.c": unit("root.c", undefined=("adapted",))}
        owners = {
            "adapted": (
                {
                    "path": "adapted.c",
                    "port_status": "selected-rooted-native-import-host-adapted",
                    "symbol_type": "function",
                },
            )
        }
        report = closure.compute_closure(["root.c"], units, owners)
        self.assertEqual(
            report["unresolved_symbols"][0]["classification"],
            "host-adapted-source-provider-outside-ready-object-set",
        )

    def test_missing_symbol_distinguishes_noncompetitive_exclusion(self) -> None:
        units = {"root.c": unit("root.c", undefined=("movie",))}
        owners = {
            "movie": (
                {
                    "path": "movie.c",
                    "port_status": (
                        "host-object-excluded-from-native-provider-inventory"
                    ),
                    "symbol_type": "function",
                },
            )
        }
        report = closure.compute_closure(["root.c"], units, owners)
        self.assertEqual(
            report["unresolved_symbols"][0]["classification"],
            "excluded-noncompetitive-source-provider",
        )

    def test_object_mapping_uses_full_source_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "prefix" / "src" / "module" / "same.c.obj"
            second = root / "prefix" / "src" / "other" / "same.c.obj"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            mapping = closure.map_ready_objects(
                root, ["src/module/same.c", "src/other/same.c"]
            )
            self.assertEqual(mapping["src/module/same.c"], first)
            self.assertEqual(mapping["src/other/same.c"], second)

    def test_explicit_object_mapping_rejects_duplicate_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "src" / "module" / "same.c.obj"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"object")
            with self.assertRaisesRegex(ValueError, "contains duplicates"):
                closure.map_ready_object_files(
                    [path, path], ["src/module/same.c"]
                )


if __name__ == "__main__":
    unittest.main()
