"""Tests for deterministic cross-object native root-closure planning."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_native_link_closure import UnitSymbols  # noqa: E402
from plan_native_root_closure import (  # noqa: E402
    ObjectSectionGraph,
    available_provider_paths,
    choose_rooted_provider,
    compute_rooted_provider_closure,
    validate_root_ownership,
)


def unit(
    path: str,
    definitions: tuple[str, ...],
    *,
    undefined: tuple[str, ...] = (),
    weak_undefined: tuple[str, ...] = (),
) -> UnitSymbols:
    return UnitSymbols(
        path=path,
        object_path=path + ".obj",
        object_sha256="0" * 64,
        definitions=definitions,
        undefined=undefined,
        weak_undefined=weak_undefined,
    )


def graph(
    path: str,
    symbol_sections: dict[str, str],
    relocations: dict[str, tuple[str, ...]],
) -> ObjectSectionGraph:
    sections = sorted(set(symbol_sections.values()))
    return ObjectSectionGraph(
        source_path=path,
        object_path=path + ".obj",
        object_sha256="0" * 64,
        object_format="pe-x86-64",
        slice_method="coff-explicit-section-remove-strip",
        sections=tuple(sections),
        symbol_sections={
            symbol: (section,) for symbol, section in symbol_sections.items()
        },
        relocations=relocations,
    )


class NativeRootClosurePlanTests(unittest.TestCase):
    def test_provider_paths_include_only_explicit_adapted_providers(self) -> None:
        readiness = {
            "ready_count": 1,
            "translation_units": [
                {"path": "src/ready.c", "compile_status": "ready"},
                {"path": "src/adapted.c", "compile_status": "blocked"},
            ],
        }
        import_spec = {
            "translation_units": [
                {
                    "path": "src/adapted.c",
                    "provider_only": True,
                    "host_adaptation": {"path": "adapted.json"},
                },
                {
                    "path": "src/root.c",
                    "roots": ["root"],
                    "host_adaptation": {"path": "root.json"},
                },
            ]
        }
        self.assertEqual(
            available_provider_paths(readiness, import_spec),
            ["src/adapted.c", "src/ready.c"],
        )
        self.assertEqual(
            available_provider_paths(
                readiness,
                import_spec,
                excluded_paths=frozenset(("src/ready.c",)),
            ),
            ["src/adapted.c"],
        )

    def test_provider_paths_reject_ready_adapted_provider(self) -> None:
        readiness = {
            "ready_count": 1,
            "translation_units": [
                {"path": "src/adapted.c", "compile_status": "ready"},
            ],
        }
        import_spec = {
            "translation_units": [
                {
                    "path": "src/adapted.c",
                    "provider_only": True,
                    "host_adaptation": {"path": "adapted.json"},
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "expected blocked"):
            available_provider_paths(readiness, import_spec)

    def test_provider_paths_remove_hash_pinned_noncompetitive_units(self) -> None:
        readiness = {
            "ready_count": 2,
            "translation_units": [
                {"path": "src/gameplay.c", "compile_status": "ready"},
                {"path": "src/movie.c", "compile_status": "ready"},
            ],
        }
        import_spec = {
            "translation_units": [],
            "provider_exclusions": [
                {
                    "path": "src/movie.c",
                    "sha256": "0" * 64,
                    "scope": "noncompetitive-presentation",
                    "reason": "movie output is outside the headless match root",
                }
            ],
        }
        self.assertEqual(
            available_provider_paths(readiness, import_spec),
            ["src/gameplay.c"],
        )

    def test_provider_paths_accept_explicit_ready_provider_replacement(self) -> None:
        readiness = {
            "ready_count": 1,
            "translation_units": [
                {"path": "src/adapted.c", "compile_status": "ready"},
            ],
        }
        import_spec = {
            "translation_units": [
                {
                    "path": "src/adapted.c",
                    "provider_only": True,
                    "replaces_ready_provider": True,
                    "host_adaptation": {"path": "adapted.json"},
                },
            ]
        }
        self.assertEqual(
            available_provider_paths(readiness, import_spec),
            ["src/adapted.c"],
        )

    def test_provider_replacement_requires_provider_only(self) -> None:
        readiness = {
            "ready_count": 1,
            "translation_units": [
                {"path": "src/adapted.c", "compile_status": "ready"},
            ],
        }
        import_spec = {
            "translation_units": [
                {
                    "path": "src/adapted.c",
                    "replaces_ready_provider": True,
                    "host_adaptation": {"path": "adapted.json"},
                },
            ]
        }
        with self.assertRaisesRegex(ValueError, "requires provider_only"):
            available_provider_paths(readiness, import_spec)

    def test_fixed_point_revisits_root_object_for_callback_cycle(self) -> None:
        units = {
            "root.c": unit(
                "root.c",
                ("root", "callback"),
                undefined=("middle", "leaf"),
            ),
            "middle.c": unit(
                "middle.c", ("middle",), undefined=("callback",)
            ),
            "leaf.c": unit("leaf.c", ("leaf",)),
        }
        graphs = {
            "root.c": graph(
                "root.c",
                {"root": ".text$root", "callback": ".text$callback"},
                {".text$root": ("middle",), ".text$callback": ("leaf",)},
            ),
            "middle.c": graph(
                "middle.c",
                {"middle": ".text$middle"},
                {".text$middle": ("callback",)},
            ),
            "leaf.c": graph(
                "leaf.c", {"leaf": ".text$leaf"}, {}
            ),
        }
        report = compute_rooted_provider_closure(
            initial_roots={"root.c": {"root"}},
            units=units,
            owners={},
            load_graph=graphs.__getitem__,
        )
        self.assertEqual(report["selected_unit_count"], 3)
        self.assertEqual(
            report["roots_by_source"]["root.c"], ["callback", "root"]
        )
        self.assertEqual(report["unresolved_symbols"], [])

    def test_source_owner_disambiguates_duplicate_definitions(self) -> None:
        owners = {
            "shared": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-ready",
                    "symbol_type": "function",
                },
            )
        }
        self.assertEqual(
            choose_rooted_provider(
                "shared", ("other.c", "owner.c"), owners
            ),
            ("owner.c", "decomp-symbol-owner"),
        )

    def test_unique_provider_can_expose_split_owner_mismatch(self) -> None:
        owners = {
            "shared": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-blocked",
                    "symbol_type": "function",
                },
            )
        }
        self.assertEqual(
            choose_rooted_provider("shared", ("other.c",), owners),
            ("other.c", "unique-ready-definition-owner-mismatch"),
        )

    def test_multiple_providers_with_owner_mismatch_fail_closed(self) -> None:
        owners = {
            "shared": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-blocked",
                    "symbol_type": "function",
                },
            )
        }
        self.assertEqual(
            choose_rooted_provider(
                "shared", ("other.c", "duplicate.c"), owners
            ),
            (None, "ready-definitions-do-not-match-source-owner"),
        )

    def test_weak_undefined_does_not_select_provider(self) -> None:
        units = {
            "root.c": unit(
                "root.c",
                ("root",),
                weak_undefined=("optional",),
            ),
            "optional.c": unit("optional.c", ("optional",)),
        }
        graphs = {
            "root.c": graph(
                "root.c",
                {"root": ".text$root"},
                {".text$root": ("optional",)},
            ),
            "optional.c": graph(
                "optional.c", {"optional": ".text$optional"}, {}
            ),
        }
        report = compute_rooted_provider_closure(
            initial_roots={"root.c": {"root"}},
            units=units,
            owners={},
            load_graph=graphs.__getitem__,
        )
        self.assertEqual(report["selected_unit_count"], 1)
        self.assertEqual(report["weak_unresolved_symbol_count"], 1)

    def test_external_host_provider_overrides_decomp_provider(self) -> None:
        units = {
            "root.c": unit("root.c", ("root",), undefined=("host_call",)),
            "decomp.c": unit("decomp.c", ("host_call",)),
        }
        graphs = {
            "root.c": graph(
                "root.c",
                {"root": ".text$root"},
                {".text$root": ("host_call",)},
            ),
            "decomp.c": graph(
                "decomp.c", {"host_call": ".text$host_call"}, {}
            ),
        }
        report = compute_rooted_provider_closure(
            initial_roots={"root.c": {"root"}},
            units=units,
            owners={},
            load_graph=graphs.__getitem__,
            external_definitions={"host_call": ("native_host.c.o",)},
        )
        self.assertEqual(report["selected_unit_count"], 1)
        self.assertEqual(report["dependency_edge_count"], 0)
        self.assertEqual(report["external_provider_edge_count"], 1)
        self.assertEqual(
            report["external_provider_edges"][0]["provider_objects"],
            ["native_host.c.o"],
        )

    def test_initial_root_must_match_pinned_source_owner(self) -> None:
        owners = {
            "root": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-ready",
                    "symbol_type": "function",
                },
            )
        }
        with self.assertRaisesRegex(ValueError, "ownership mismatch"):
            validate_root_ownership({"wrong.c": {"root"}}, owners)

    def test_host_adaptation_may_add_a_verified_root_symbol(self) -> None:
        units = {"adapted.c": unit("adapted.c", ("native_bridge",))}
        validate_root_ownership(
            {"adapted.c": {"native_bridge"}},
            {},
            units=units,
            host_adapted_paths=frozenset(("adapted.c",)),
        )

    def test_host_adaptation_cannot_claim_an_original_symbol_owner(self) -> None:
        owners = {
            "root": (
                {
                    "path": "owner.c",
                    "port_status": "host-object-ready",
                    "symbol_type": "function",
                },
            )
        }
        units = {"adapted.c": unit("adapted.c", ("root",))}
        with self.assertRaisesRegex(ValueError, "ownership mismatch"):
            validate_root_ownership(
                {"adapted.c": {"root"}},
                owners,
                units=units,
                host_adapted_paths=frozenset(("adapted.c",)),
            )


if __name__ == "__main__":
    unittest.main()
