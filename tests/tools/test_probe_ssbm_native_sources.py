"""Tests for the native Melee source readiness classifier."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from probe_ssbm_native_sources import (  # noqa: E402
    classify_blocker,
    compiler_arguments,
    discover_sources,
    normalized_diagnostic,
    recorded_target_arguments,
    source_module,
    write_text_if_different,
)


class NativeSourceProbeTests(unittest.TestCase):
    def test_readiness_output_is_not_rewritten_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness.json"
            self.assertTrue(write_text_if_different(output, "{}\n"))
            initial_mtime = output.stat().st_mtime_ns
            self.assertFalse(write_text_if_different(output, "{}\n"))
            self.assertEqual(output.stat().st_mtime_ns, initial_mtime)
            self.assertTrue(write_text_if_different(output, "{\"schema\": 1}\n"))

    def test_recorded_target_arguments_hide_machine_specific_sysroot(self) -> None:
        actual = ("-m32", "-I/opt/ssbmsim-test/root/usr/include")
        recorded = ("-m32", "-I<ssbm-i686-sysroot>/usr/include")
        self.assertEqual(
            recorded_target_arguments(actual, recorded), list(recorded)
        )
        self.assertEqual(recorded_target_arguments(actual, ()), list(actual))
        with self.assertRaisesRegex(ValueError, "match the actual argument count"):
            recorded_target_arguments(actual, ("-m32",))

    def test_blocker_categories_are_causal(self) -> None:
        cases = {
            "fatal error: generated/foo.inc: No such file or directory":
                "missing-generated-include",
            "fatal error: dolphin/foo.h: No such file or directory":
                "missing-header",
            "error: unknown register name 'r3' in 'asm'": "powerpc-assembly",
            "error: static assertion failed: layout": "host-layout-assertion",
            "error: conflicting types for 'OSFoo'": "sdk-or-source-type-conflict",
            "error: implicit declaration of function 'OSFoo'":
                "missing-host-declaration",
            "error: passing argument 1 from incompatible pointer type":
                "host-type-incompatibility",
            "error: unused variable 'x' [-Werror=unused-variable]":
                "strict-warning",
            "error: expected expression before '__asm'":
                "unsupported-source-syntax",
        }
        for diagnostic, expected in cases.items():
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(classify_blocker(diagnostic), expected)
        self.assertEqual(
            classify_blocker("compiler timeout", timed_out=True),
            "compiler-timeout",
        )

    def test_diagnostic_normalization_removes_machine_paths(self) -> None:
        diagnostic = (
            "In file included from C:\\repo\\decomp\\src\\x.h:2:\n"
            "C:\\repo\\decomp\\src\\x.c:3:1: error: broken\n"
            "C:\\repo\\aurora\\include\\dolphin\\x.h:4: note: detail\n"
            "C:\\temp\\adapted\\melee\\ft\\types.h:5: note: adapted\n"
        )
        result = normalized_diagnostic(
            diagnostic,
            replacements=(
                (Path("C:/repo/decomp"), "<decomp>"),
                (Path("C:/repo/aurora"), "<aurora>"),
                (Path("C:/temp/adapted"), "<adapted-headers>"),
            ),
        )
        self.assertIn("<decomp>/src/x.c", result)
        self.assertIn("<aurora>/include/dolphin/x.h", result)
        self.assertIn("<adapted-headers>/melee/ft/types.h", result)
        self.assertNotIn("C:/repo", result)
        self.assertNotIn("C:/temp", result)

    def test_module_classification_is_stable(self) -> None:
        self.assertEqual(source_module("src/MSL/float.c"), "MSL")
        self.assertEqual(source_module("src/melee/ft/fighter.c"), "ft")
        self.assertEqual(
            source_module("src/sysdolphin/baselib/random.c"),
            "sysdolphin/baselib",
        )
        self.assertEqual(
            source_module("extern/dolphin/src/dolphin/mtx/mtx.c"),
            "dolphin/mtx",
        )
        self.assertEqual(source_module("src/Runtime/foo.c"), "Runtime")

    def test_complete_gameplay_and_support_trees_are_in_source_inventory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "src/MSL/float.c",
                "src/MSL/trigf.c",
                "src/melee/cm/camera.c",
                "src/melee/ef/efasync.c",
                "extern/dolphin/src/dolphin/mtx/mtx.c",
                "extern/dolphin/src/dolphin/vi/vi.c",
                "src/Runtime/not_gameplay.c",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("void source(void) {}\n", encoding="utf-8")
            self.assertEqual(
                [
                    path.relative_to(root).as_posix()
                    for path in discover_sources(root)
                ],
                [
                    "extern/dolphin/src/dolphin/mtx/mtx.c",
                    "src/MSL/float.c",
                    "src/MSL/trigf.c",
                    "src/Runtime/not_gameplay.c",
                    "src/melee/cm/camera.c",
                    "src/melee/ef/efasync.c",
                ],
            )

    def test_declared_provider_outside_default_trees_is_not_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "extern/dolphin/src/dolphin/gx/GXLight.c"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text("void light(void) {}\n")
            self.assertEqual(discover_sources(root, [relative, relative]), [path])
            with self.assertRaises(ValueError):
                discover_sources(root, ["extern/dolphin/missing.c"])
            with self.assertRaises(ValueError):
                discover_sources(root, ["../outside.c"])

    def test_address_diagnostics_are_suppressed_without_weakening_abi_checks(
        self,
    ) -> None:
        arguments = compiler_arguments(
            Path("gcc"),
            source=Path("decomp/src/melee/it/it_2725.c"),
            decomp=Path("decomp"),
            aurora=Path("aurora"),
            compat=Path("compat"),
            adapted_header_root=Path("adapted"),
            forced_headers=(Path("adapted/melee/ft/types.h"),),
            target_arguments=("-m32", "-msse2", "-mfpmath=sse"),
            system_headers=("math.h", "stdarg.h", "sys/types.h"),
        )
        self.assertEqual(
            arguments[1:4], ["-m32", "-msse2", "-mfpmath=sse"]
        )
        self.assertIn("-Wno-address", arguments)
        self.assertIn("-Werror", arguments)
        self.assertIn("-Wundef", arguments)
        include_index = arguments.index("-include")
        self.assertEqual(
            arguments[include_index + 1], str(Path("compat") / "platform.h")
        )
        self.assertIn("-Iadapted", arguments)
        math_index = arguments.index("-include", include_index + 1)
        self.assertEqual(arguments[math_index + 1], "math.h")
        forced_index = arguments.index("-include", math_index + 1)
        forced_index = arguments.index("-include", forced_index + 1)
        forced_index = arguments.index("-include", forced_index + 1)
        self.assertEqual(
            arguments[forced_index + 1], str(Path("adapted/melee/ft/types.h"))
        )
        self.assertNotIn("-Wno-undef", arguments)
        self.assertNotIn("-DMUST_MATCH=0", arguments)
        self.assertFalse(
            any(argument.startswith("-DMUST_MATCH") for argument in arguments)
        )
        self.assertNotIn("-Wno-pointer-to-int-cast", arguments)
        self.assertNotIn("-Wno-sequence-point", arguments)
        self.assertNotIn("-Wno-return-type", arguments)
        self.assertIn("-Wno-strict-prototypes", arguments)

    def test_nonmatching_macro_exception_is_source_scoped(self) -> None:
        arguments = compiler_arguments(
            Path("gcc"),
            source=Path("decomp/src/melee/it/it_26B1.c"),
            decomp=Path("decomp"),
            aurora=Path("aurora"),
            compat=Path("compat"),
            source_options=("-Wno-undef",),
        )
        self.assertIn("-Wundef", arguments)
        self.assertIn("-Wno-undef", arguments)
        self.assertFalse(
            any(argument.startswith("-DMUST_MATCH") for argument in arguments)
        )

    def test_release_inventory_exceptions_are_passed_explicitly(self) -> None:
        common = {
            "decomp": Path("decomp"),
            "aurora": Path("aurora"),
            "compat": Path("compat"),
        }
        main_arguments = compiler_arguments(
            Path("gcc"),
            source=Path("decomp/src/melee/gm/gmmain_lib.c"),
            source_options=("-Wno-stringop-overflow",),
            **common,
        )
        collision_arguments = compiler_arguments(
            Path("gcc"),
            source=Path("decomp/src/melee/mp/mpcoll.c"),
            source_options=("-Wno-uninitialized",),
            **common,
        )
        ordinary_arguments = compiler_arguments(
            Path("gcc"),
            source=Path("decomp/src/melee/ft/fighter.c"),
            **common,
        )
        self.assertIn("-Wno-stringop-overflow", main_arguments)
        self.assertIn("-Wno-uninitialized", collision_arguments)
        self.assertNotIn("-Wno-stringop-overflow", ordinary_arguments)
        self.assertNotIn("-Wno-uninitialized", ordinary_arguments)


if __name__ == "__main__":
    unittest.main()
