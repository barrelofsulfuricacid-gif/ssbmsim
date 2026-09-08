"""Tests for deterministic native root-closure archive materialization."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from plan_native_root_closure import (  # noqa: E402
    CLAIM_BOUNDARY as PLAN_CLAIM_BOUNDARY,
    compute_rooted_provider_closure,
    load_section_graph,
    read_root_symbols,
)
from materialize_native_root_closure import (  # noqa: E402
    materialize_plan,
    parse_symbol_redefinitions,
    resolve_selected_objects,
    validate_plan,
)
from slice_native_object import resolve_executable, sha256  # noqa: E402


def full_plan(closure: dict[str, object]) -> dict[str, object]:
    closure.setdefault("external_provider_edge_count", 0)
    closure.setdefault("external_provider_edges", [])
    return {
        "schema": 1,
        "target": "fixture",
        "claim_boundary": PLAN_CLAIM_BOUNDARY,
        "decomp_revision": "0" * 40,
        "readiness_report_sha256": "1" * 64,
        "source_manifest_sha256": "2" * 64,
        "import_spec_sha256": "3" * 64,
        "provider_inventory_sha256": "4" * 64,
        "external_provider_object_count": 0,
        "external_provider_inventory_sha256": "7" * 64,
        **closure,
    }


class NativeRootClosureMaterializerTests(unittest.TestCase):
    def test_symbol_redefinitions_are_canonical_and_strict(self) -> None:
        self.assertEqual(
            parse_symbol_redefinitions(["memset=pf_memset", "memcpy=pf_memcpy"]),
            (("memcpy", "pf_memcpy"), ("memset", "pf_memset")),
        )
        with self.assertRaisesRegex(ValueError, "invalid symbol redefinition"):
            parse_symbol_redefinitions(["memcpy"])
        with self.assertRaisesRegex(ValueError, "duplicate symbol redefinition"):
            parse_symbol_redefinitions(["memcpy=one", "memcpy=two"])

    def test_resolves_provider_owned_initial_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root_object = root / "root.o"
            provider_object = root / "provider.c.o"
            root_object.write_bytes(b"root")
            provider_object.write_bytes(b"provider")
            plan = full_plan(
                {
                    "initial_roots": {
                        "provider.c": ["provider_default"],
                        "root.c": ["root"],
                    },
                    "selected_unit_count": 2,
                    "selected_section_count": 2,
                    "dependency_edge_count": 0,
                    "unresolved_symbol_count": 0,
                    "ambiguous_symbol_count": 0,
                    "weak_unresolved_symbol_count": 0,
                    "roots_by_source": {
                        "provider.c": ["provider_default"],
                        "root.c": ["root"],
                    },
                    "dependency_edges": [],
                    "unresolved_symbols": [],
                    "ambiguous_symbols": [],
                    "weak_unresolved_symbols": [],
                    "selected_units": [
                        {
                            "source_path": "provider.c",
                            "object_path": "provider.c.o",
                            "object_sha256": "5" * 64,
                            "object_format": "elf32-i386",
                            "slice_method": "elf-gc-sections-partial-link",
                            "roots": ["provider_default"],
                            "selected_section_count": 1,
                            "selected_sections": [".text.provider_default"],
                            "section_edges": [],
                            "external_frontier": [],
                        },
                        {
                            "source_path": "root.c",
                            "object_path": "root.o",
                            "object_sha256": "6" * 64,
                            "object_format": "elf32-i386",
                            "slice_method": "elf-gc-sections-partial-link",
                            "roots": ["root"],
                            "selected_section_count": 1,
                            "selected_sections": [".text.root"],
                            "section_edges": [],
                            "external_frontier": [],
                        },
                    ],
                }
            )

            objects = resolve_selected_objects(
                plan,
                provider_objects=[provider_object],
                root_source="root.c",
                root_object=root_object,
            )

            self.assertEqual(objects["root.c"], root_object.resolve())
            self.assertEqual(objects["provider.c"], provider_object.resolve())

    def test_rejects_ambiguous_provider_plan(self) -> None:
        plan = full_plan(
            {
                "initial_roots": {"root.c": ["root"]},
                "selected_unit_count": 1,
                "selected_section_count": 1,
                "dependency_edge_count": 0,
                "unresolved_symbol_count": 0,
                "ambiguous_symbol_count": 1,
                "weak_unresolved_symbol_count": 0,
                "roots_by_source": {"root.c": ["root"]},
                "dependency_edges": [],
                "unresolved_symbols": [],
                "ambiguous_symbols": [{"symbol": "shared"}],
                "weak_unresolved_symbols": [],
                "selected_units": [
                    {
                        "source_path": "root.c",
                        "object_path": "root.obj",
                        "object_sha256": "5" * 64,
                        "object_format": "pe-x86-64",
                        "slice_method": "coff-explicit-section-remove-strip",
                        "roots": ["root"],
                        "selected_section_count": 1,
                        "selected_sections": [".text$root"],
                        "section_edges": [],
                        "external_frontier": [],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "ambiguous providers"):
            validate_plan(plan)

    def test_real_archive_matches_planned_sections_and_is_deterministic(self) -> None:
        required = ("gcc", "nm", "objdump", "objcopy", "ld", "ar")
        if any(shutil.which(name) is None for name in required):
            self.skipTest("GNU native object tools are unavailable")
        nm = resolve_executable("nm", "nm")
        objdump = resolve_executable("objdump", "objdump")
        objcopy = resolve_executable("objcopy", "objcopy")
        linker = resolve_executable("ld", "linker")
        ar = resolve_executable("ar", "archiver")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root_source = root / "root.c"
            provider_source = root / "provider.c"
            root_source.write_text(
                "extern int provider(int value);\n"
                "int root_function(int value) { return provider(value); }\n"
                "int unrelated_root(int value) { return value + 11; }\n",
                encoding="utf-8",
                newline="\n",
            )
            provider_source.write_text(
                "int provider(int value) { return value + 3; }\n"
                "int unrelated_provider(int value) { return value + 19; }\n",
                encoding="utf-8",
                newline="\n",
            )
            objects: dict[str, Path] = {}
            for source_path, label in (
                (root_source, "root.c"),
                (provider_source, "provider.c"),
            ):
                object_path = source_path.with_suffix(".o")
                subprocess.run(
                    [
                        "gcc",
                        "-std=c17",
                        "-ffunction-sections",
                        "-fdata-sections",
                        "-c",
                        str(source_path),
                        "-o",
                        str(object_path),
                    ],
                    check=True,
                )
                objects[label] = object_path

            units = {
                label: read_root_symbols(
                    label, object_path=object_path, nm=nm
                )
                for label, object_path in objects.items()
            }
            graphs = {
                label: load_section_graph(
                    label,
                    object_path=object_path,
                    object_label=f"fixture/{object_path.name}",
                    objdump=objdump,
                )
                for label, object_path in objects.items()
            }
            closure = compute_rooted_provider_closure(
                initial_roots={"root.c": {"root_function"}},
                units=units,
                owners={},
                load_graph=graphs.__getitem__,
            )
            plan = full_plan(closure)
            archive = root / "closure.a"
            manifest_path = root / "closure.json"
            manifest = materialize_plan(
                plan=plan,
                plan_sha256=hashlib.sha256(b"fixture-plan").hexdigest(),
                objects=objects,
                output_archive=archive,
                output_manifest=manifest_path,
                objdump=objdump,
                objcopy=objcopy,
                linker=linker,
                symbol_redefinitions=(("provider", "pf_provider"),),
                ar=ar,
                nm=nm,
            )
            self.assertEqual(manifest["archive"]["member_count"], 2)
            self.assertEqual(manifest["archive"]["sha256"], sha256(archive))
            self.assertEqual(manifest["link_audit"]["selected_root_count"], 2)
            self.assertEqual(
                manifest["symbol_redefinitions"],
                [{"from": "provider", "to": "pf_provider"}],
            )
            self.assertEqual(
                manifest["link_audit"]["strong_unresolved_symbols"], []
            )
            symbols = subprocess.run(
                [str(nm), "-P", str(archive)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            self.assertIn("root_function", symbols)
            self.assertIn("pf_provider", symbols)
            self.assertNotIn("unrelated_root", symbols)
            self.assertNotIn("unrelated_provider", symbols)

            tampered = copy.deepcopy(plan)
            tampered["selected_units"][0]["object_sha256"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "planned object hash"):
                materialize_plan(
                    plan=tampered,
                    plan_sha256="0" * 64,
                    objects=objects,
                    output_archive=root / "tampered.a",
                    output_manifest=root / "tampered.json",
                    objdump=objdump,
                    objcopy=objcopy,
                    linker=linker,
                    ar=ar,
                    nm=nm,
                )


if __name__ == "__main__":
    unittest.main()
