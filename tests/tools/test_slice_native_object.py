"""Tests for deterministic native object section-closure slicing."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from slice_native_object import (  # noqa: E402
    compute_section_closure,
    parse_relocations,
    parse_object_format,
    parse_sections,
    parse_symbols,
    resolve_executable,
    slice_method_for_format,
    slice_object,
)


class NativeObjectSliceTests(unittest.TestCase):
    def test_rejects_unsupported_object_format(self) -> None:
        self.assertEqual(
            slice_method_for_format("elf64-x86-64"),
            "elf-relocatable-link-gc",
        )
        self.assertEqual(
            slice_method_for_format("pe-x86-64"),
            "coff-explicit-section-remove-strip",
        )
        with self.assertRaisesRegex(ValueError, "unsupported native object"):
            slice_method_for_format("mach-o-x86-64")

    def test_parses_coff_sections_symbols_and_relocations(self) -> None:
        self.assertEqual(
            parse_object_format("fixture.o: file format pe-x86-64\n"),
            "pe-x86-64",
        )
        sections = parse_sections(
            "Sections:\n"
            "Idx Name Size VMA LMA File off Algn\n"
            "  0 .text$root 00000010 0 0 0000003c 2**4\n"
            "  1 .data$value 00000004 0 0 0000004c 2**2\n"
        )
        self.assertEqual(sections, (".text$root", ".data$value"))
        symbols = parse_symbols(
            "[  1](sec  1)(fl 0x00)(ty 20)(scl 2) (nx 0) "
            "0x0000000000000000 root\n"
            "[  2](sec  2)(fl 0x00)(ty 0)(scl 3) (nx 0) "
            "0x0000000000000000 value\n",
            sections,
        )
        self.assertEqual(symbols["root"], (".text$root",))
        self.assertEqual(symbols["value"], (".data$value",))
        relocations = parse_relocations(
            "RELOCATION RECORDS FOR [.text$root]:\n"
            "OFFSET TYPE VALUE\n"
            "0000000000000004 IMAGE_REL_AMD64_REL32 value-0x4\n"
            "0000000000000008 IMAGE_REL_AMD64_REL32 external\n"
        )
        self.assertEqual(relocations[".text$root"], ("external", "value"))

    def test_allows_elf_comdat_group_metadata_duplicates(self) -> None:
        sections = parse_sections(
            "Sections:\n"
            "  0 .group 00000008 0 0 00000034 2**2\n"
            "  1 .group 00000008 0 0 0000003c 2**2\n"
            "  2 .text.root 00000010 0 0 00000044 2**4\n"
        )
        self.assertEqual(sections, (".group", ".group", ".text.root"))

    def test_rejects_ambiguous_duplicate_payload_sections(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported duplicate"):
            parse_sections(
                "Sections:\n"
                "  0 .text.root 00000010 0 0 00000034 2**4\n"
                "  1 .text.root 00000010 0 0 00000044 2**4\n"
            )

    def test_closure_follows_internal_relocations_and_unwind_companions(self) -> None:
        sections = (
            ".text$root",
            ".xdata$root",
            ".pdata$root",
            ".text$helper",
            ".data$value",
            ".text$unrelated",
        )
        report = compute_section_closure(
            roots=("root",),
            sections=sections,
            symbol_sections={
                "root": (".text$root",),
                "helper": (".text$helper",),
                "value": (".data$value",),
            },
            relocations={
                ".text$root": ("helper", "external"),
                ".text$helper": ("value",),
                ".pdata$root": (".text$root", ".xdata$root"),
            },
        )
        self.assertEqual(
            report["selected_sections"],
            [
                ".data$value",
                ".pdata$root",
                ".text$helper",
                ".text$root",
                ".xdata$root",
            ],
        )
        self.assertEqual(
            report["external_frontier"],
            [{"symbol": "external", "consumers": [".text$root"]}],
        )

    def test_ambiguous_root_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one defining section"):
            compute_section_closure(
                roots=("root",),
                sections=(".text.a", ".text.b"),
                symbol_sections={"root": (".text.a", ".text.b")},
                relocations={},
            )

    def test_external_provider_overrides_same_object_definition(self) -> None:
        report = compute_section_closure(
            roots=("root",),
            sections=(".text.root", ".text.host_call"),
            symbol_sections={
                "root": (".text.root",),
                "host_call": (".text.host_call",),
            },
            relocations={".text.root": ("host_call",)},
            external_symbols=("host_call",),
        )
        self.assertEqual(report["selected_sections"], [".text.root"])
        self.assertEqual(
            report["external_frontier"],
            [{"symbol": "host_call", "consumers": [".text.root"]}],
        )

    def test_real_object_slice_drops_unrelated_function(self) -> None:
        compiler_name = "gcc"
        if shutil.which(compiler_name) is None:
            self.skipTest("gcc is unavailable")
        objdump = resolve_executable("objdump", "objdump")
        objcopy = resolve_executable("objcopy", "objcopy")
        linker = resolve_executable("ld", "linker")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.c"
            object_path = root / "fixture.o"
            sliced_path = root / "fixture.root.o"
            source.write_text(
                "extern int external_value(int value);\n"
                "static int helper(int value)\n"
                "{\n"
                "    return external_value(value) + 3;\n"
                "}\n"
                "int root_function(int value)\n"
                "{\n"
                "    return helper(value);\n"
                "}\n"
                "int unrelated_function(int value)\n"
                "{\n"
                "    return external_value(value) + 9;\n"
                "}\n",
                encoding="utf-8",
                newline="\n",
            )
            subprocess.run(
                [
                    compiler_name,
                    "-std=c17",
                    "-ffunction-sections",
                    "-fdata-sections",
                    "-c",
                    str(source),
                    "-o",
                    str(object_path),
                ],
                check=True,
            )
            report = slice_object(
                objdump=objdump,
                objcopy=objcopy,
                linker=linker,
                input_path=object_path,
                output_path=sliced_path,
                roots=("root_function",),
            )
            self.assertIn("external_value", {
                row["symbol"] for row in report["external_frontier"]
            })
            symbols = subprocess.run(
                ["nm", "-P", str(sliced_path)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            self.assertIn("root_function", symbols)
            self.assertIn("external_value", symbols)
            self.assertNotIn("unrelated_function", symbols)

if __name__ == "__main__":
    unittest.main()
