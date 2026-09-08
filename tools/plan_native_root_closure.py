#!/usr/bin/env python3
"""Plan an exact cross-object native section closure from source roots.

This analyzes host-compiled source objects. It does not execute the selected
code or establish runtime, gameplay, or Dolphin-equivalence coverage.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Callable, Iterable

from analyze_native_link_closure import (
    UnitSymbols,
    definition_index,
    executable_version,
    map_ready_objects,
    map_ready_object_files,
    missing_classification,
    parse_nm_posix,
    ready_paths,
    read_unit_symbols,
    resolve_executable,
    sha256,
    source_owner_index,
    validate_inputs,
)
from slice_native_object import (
    compute_section_closure,
    parse_object_format,
    parse_relocations,
    parse_sections,
    parse_symbols,
    run_text,
    slice_method_for_format,
)


CLAIM_BOUNDARY = (
    "native-root-provider-section-plan-not-runtime-or-behavioral-coverage"
)


@dataclass(frozen=True)
class ObjectSectionGraph:
    source_path: str
    object_path: str
    object_sha256: str
    object_format: str
    slice_method: str
    sections: tuple[str, ...]
    symbol_sections: dict[str, tuple[str, ...]]
    relocations: dict[str, tuple[str, ...]]

    def closure(
        self, roots: Iterable[str], external_symbols: Iterable[str] = ()
    ) -> dict[str, object]:
        result = compute_section_closure(
            roots=roots,
            sections=self.sections,
            symbol_sections=self.symbol_sections,
            relocations=self.relocations,
            external_symbols=external_symbols,
        )
        result["object_format"] = self.object_format
        result["slice_method"] = self.slice_method
        return result


def read_root_symbols(
    source_path: str, *, object_path: Path, nm: Path
) -> UnitSymbols:
    process = subprocess.run(
        [str(nm), "-g", "-P", str(object_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    definitions, undefined, weak_undefined = parse_nm_posix(process.stdout)
    return UnitSymbols(
        path=source_path,
        object_path=f"root-object/{object_path.name}",
        object_sha256=sha256(object_path),
        definitions=tuple(sorted(definitions)),
        undefined=tuple(sorted(undefined)),
        weak_undefined=tuple(sorted(weak_undefined)),
    )


def load_section_graph(
    source_path: str,
    *,
    object_path: Path,
    object_label: str,
    objdump: Path,
) -> ObjectSectionGraph:
    headers = run_text(objdump, "-h", str(object_path))
    object_format = parse_object_format(headers)
    try:
        sections = parse_sections(headers)
    except ValueError as error:
        raise ValueError(
            f"{source_path} ({object_label}): {error}"
        ) from error
    return ObjectSectionGraph(
        source_path=source_path,
        object_path=object_label,
        object_sha256=sha256(object_path),
        object_format=object_format,
        slice_method=slice_method_for_format(object_format),
        sections=sections,
        symbol_sections=parse_symbols(
            run_text(objdump, "-t", str(object_path)), sections
        ),
        relocations=parse_relocations(
            run_text(objdump, "-r", str(object_path))
        ),
    )


def choose_rooted_provider(
    symbol: str,
    providers: tuple[str, ...],
    owners: dict[str, tuple[dict[str, object], ...]],
) -> tuple[str | None, str]:
    owner_paths = {str(row["path"]) for row in owners.get(symbol, ())}
    if owner_paths:
        matching = sorted(owner_paths.intersection(providers))
        if len(matching) == 1:
            return matching[0], "decomp-symbol-owner"
        if not matching:
            if len(providers) == 1:
                return providers[0], "unique-ready-definition-owner-mismatch"
            return None, "ready-definitions-do-not-match-source-owner"
        return None, "multiple-ready-source-owners"
    if len(providers) == 1:
        return providers[0], "unique-ready-definition"
    return None, "ambiguous-ready-definitions"


def compute_rooted_provider_closure(
    *,
    initial_roots: dict[str, set[str]],
    units: dict[str, UnitSymbols],
    owners: dict[str, tuple[dict[str, object], ...]],
    load_graph: Callable[[str], ObjectSectionGraph],
    external_definitions: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, object]:
    if not initial_roots or any(not roots for roots in initial_roots.values()):
        raise ValueError("every initial source requires at least one root symbol")
    unknown_units = sorted(set(initial_roots).difference(units))
    if unknown_units:
        raise ValueError("initial source object is unavailable: " + ", ".join(unknown_units))

    definitions = definition_index(units)
    if external_definitions is None:
        external_definitions = {}
    roots_by_unit = {
        path: set(roots) for path, roots in sorted(initial_roots.items())
    }
    queue = deque(sorted(roots_by_unit))
    queued = set(queue)
    closures: dict[str, dict[str, object]] = {}
    graphs: dict[str, ObjectSectionGraph] = {}
    edge_consumers: dict[
        tuple[str, str, str], dict[str, set[str]]
    ] = {}
    unresolved_consumers: dict[str, dict[str, set[str]]] = {}
    ambiguous_consumers: dict[
        tuple[str, tuple[str, ...], str], dict[str, set[str]]
    ] = {}
    weak_consumers: dict[str, dict[str, set[str]]] = {}
    external_consumers: dict[
        tuple[str, tuple[str, ...]], dict[str, set[str]]
    ] = {}

    while queue:
        consumer = queue.popleft()
        queued.remove(consumer)
        if consumer not in graphs:
            graphs[consumer] = load_graph(consumer)
        graph = graphs[consumer]
        closure = graph.closure(
            roots_by_unit[consumer], external_definitions
        )
        closures[consumer] = closure

        for frontier in closure["external_frontier"]:
            symbol = str(frontier["symbol"])
            sections = {str(section) for section in frontier["consumers"]}
            weak_only = (
                symbol in units[consumer].weak_undefined
                and symbol not in units[consumer].undefined
            )
            if weak_only:
                weak_consumers.setdefault(symbol, {}).setdefault(
                    consumer, set()
                ).update(sections)
                continue

            external_providers = external_definitions.get(symbol, ())
            if external_providers:
                external_consumers.setdefault(
                    (symbol, external_providers), {}
                ).setdefault(consumer, set()).update(sections)
                continue

            providers = definitions.get(symbol, ())
            provider, selection = choose_rooted_provider(
                symbol, providers, owners
            )
            if provider is None:
                if providers:
                    key = (symbol, providers, selection)
                    ambiguous_consumers.setdefault(key, {}).setdefault(
                        consumer, set()
                    ).update(sections)
                else:
                    unresolved_consumers.setdefault(symbol, {}).setdefault(
                        consumer, set()
                    ).update(sections)
                continue

            edge_consumers.setdefault(
                (provider, symbol, selection), {}
            ).setdefault(consumer, set()).update(sections)
            provider_roots = roots_by_unit.setdefault(provider, set())
            if symbol not in provider_roots:
                provider_roots.add(symbol)
                if provider not in queued:
                    queue.append(provider)
                    queued.add(provider)

    selected_units = []
    for path in sorted(closures):
        graph = graphs[path]
        closure = closures[path]
        selected_units.append(
            {
                "source_path": path,
                "object_path": graph.object_path,
                "object_sha256": graph.object_sha256,
                "object_format": graph.object_format,
                "slice_method": graph.slice_method,
                "roots": sorted(roots_by_unit[path]),
                "selected_section_count": len(closure["selected_sections"]),
                "selected_sections": closure["selected_sections"],
                "section_edges": closure["section_edges"],
                "external_frontier": closure["external_frontier"],
            }
        )

    dependency_edges = [
        {
            "consumers": [
                {"source_path": path, "sections": sorted(sections)}
                for path, sections in sorted(consumers.items())
            ],
            "provider": provider,
            "symbol": symbol,
            "selection": selection,
        }
        for (provider, symbol, selection), consumers in sorted(
            edge_consumers.items()
        )
    ]
    unresolved = [
        {
            "symbol": symbol,
            "consumers": [
                {"source_path": path, "sections": sorted(sections)}
                for path, sections in sorted(consumers.items())
            ],
            "classification": missing_classification(symbol, owners),
            "source_owners": list(owners.get(symbol, ())),
        }
        for symbol, consumers in sorted(unresolved_consumers.items())
    ]
    ambiguous = [
        {
            "symbol": symbol,
            "consumers": [
                {"source_path": path, "sections": sorted(sections)}
                for path, sections in sorted(consumers.items())
            ],
            "ready_providers": list(providers),
            "selection_failure": selection,
            "source_owners": list(owners.get(symbol, ())),
        }
        for (symbol, providers, selection), consumers in sorted(
            ambiguous_consumers.items()
        )
    ]
    weak = [
        {
            "symbol": symbol,
            "consumers": [
                {"source_path": path, "sections": sorted(sections)}
                for path, sections in sorted(consumers.items())
            ],
        }
        for symbol, consumers in sorted(weak_consumers.items())
    ]
    external = [
        {
            "symbol": symbol,
            "provider_objects": list(providers),
            "consumers": [
                {"source_path": path, "sections": sorted(sections)}
                for path, sections in sorted(consumers.items())
            ],
        }
        for (symbol, providers), consumers in sorted(
            external_consumers.items()
        )
    ]
    return {
        "initial_roots": {
            path: sorted(roots) for path, roots in sorted(initial_roots.items())
        },
        "selected_unit_count": len(selected_units),
        "selected_section_count": sum(
            int(unit["selected_section_count"]) for unit in selected_units
        ),
        "dependency_edge_count": len(dependency_edges),
        "unresolved_symbol_count": len(unresolved),
        "ambiguous_symbol_count": len(ambiguous),
        "weak_unresolved_symbol_count": len(weak),
        "external_provider_edge_count": len(external),
        "roots_by_source": {
            path: sorted(roots) for path, roots in sorted(roots_by_unit.items())
        },
        "dependency_edges": dependency_edges,
        "unresolved_symbols": unresolved,
        "ambiguous_symbols": ambiguous,
        "weak_unresolved_symbols": weak,
        "external_provider_edges": external,
        "selected_units": selected_units,
    }


def external_definition_index(
    object_files: Iterable[Path], *, nm: Path
) -> dict[str, tuple[str, ...]]:
    providers: dict[str, set[str]] = {}
    labels: set[str] = set()
    for object_path in sorted(
        (path.resolve() for path in object_files),
        key=lambda path: path.as_posix().casefold(),
    ):
        if not object_path.is_file():
            raise ValueError(f"external provider object not found: {object_path}")
        label = object_path.name
        if label in labels:
            raise ValueError(f"duplicate external provider object label: {label}")
        labels.add(label)
        process = subprocess.run(
            [str(nm), "-g", "-P", str(object_path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        definitions, _, _ = parse_nm_posix(process.stdout)
        for symbol in definitions:
            if symbol.startswith("__x86.get_pc_thunk."):
                continue
            providers.setdefault(symbol, set()).add(label)
    return {
        symbol: tuple(sorted(object_labels))
        for symbol, object_labels in sorted(providers.items())
    }


def external_provider_inventory_sha256(
    object_files: Iterable[Path],
) -> str:
    rows = [
        {"object": path.resolve().name, "sha256": sha256(path.resolve())}
        for path in sorted(
            object_files, key=lambda value: value.resolve().as_posix().casefold()
        )
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_root_ownership(
    initial_roots: dict[str, set[str]],
    owners: dict[str, tuple[dict[str, object], ...]],
    units: dict[str, UnitSymbols] | None = None,
    host_adapted_paths: frozenset[str] = frozenset(),
) -> None:
    for source_path, roots in initial_roots.items():
        for root in roots:
            root_owners = {str(row["path"]) for row in owners.get(root, ())}
            if source_path in root_owners:
                continue
            unit = units.get(source_path) if units is not None else None
            is_verified_host_added = (
                not root_owners
                and source_path in host_adapted_paths
                and unit is not None
                and root in unit.definitions
            )
            if is_verified_host_added:
                continue
            raise ValueError(
                f"root source ownership mismatch: {root} is not owned by "
                f"{source_path}"
            )


def provider_inventory_sha256(units: dict[str, UnitSymbols]) -> str:
    rows = [
        {
            "source_path": path,
            "object_sha256": unit.object_sha256,
            "definitions": list(unit.definitions),
            "undefined": list(unit.undefined),
            "weak_undefined": list(unit.weak_undefined),
        }
        for path, unit in sorted(units.items())
    ]
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_object_list(path: Path) -> list[Path]:
    if not path.is_file():
        raise ValueError(f"provider object list not found: {path}")
    entries = [
        Path(line).resolve()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not entries:
        raise ValueError("provider object list is empty")
    return entries


def available_provider_paths(
    readiness: dict[str, object],
    import_spec: dict[str, object],
    *,
    excluded_paths: frozenset[str] = frozenset(),
) -> list[str]:
    provider_exclusions = import_spec.get("provider_exclusions", [])
    if not isinstance(provider_exclusions, list):
        raise ValueError("provider_exclusions is not a list")
    configured_exclusions: set[str] = set()
    for entry in provider_exclusions:
        if not isinstance(entry, dict) or "path" not in entry:
            raise ValueError("invalid provider exclusion")
        path = str(entry["path"])
        if path in configured_exclusions:
            raise ValueError(f"duplicate provider exclusion: {path}")
        configured_exclusions.add(path)
    readiness_paths = {
        str(unit["path"]) for unit in readiness["translation_units"]
    }
    unknown_exclusions = configured_exclusions - readiness_paths
    if unknown_exclusions:
        raise ValueError(
            "provider exclusion is absent from readiness inventory: "
            + ", ".join(sorted(unknown_exclusions))
        )
    ready = set(ready_paths(readiness))
    paths = ready - excluded_paths - configured_exclusions
    readiness_status = {
        str(unit["path"]): str(unit["compile_status"])
        for unit in readiness["translation_units"]
    }
    seen_imports: set[str] = set()
    for unit in import_spec["translation_units"]:
        path = str(unit["path"])
        if path in seen_imports:
            raise ValueError(f"duplicate selected import source: {path}")
        seen_imports.add(path)
        provider_only = unit.get("provider_only", False)
        replaces_ready_provider = unit.get("replaces_ready_provider", False)
        if not isinstance(replaces_ready_provider, bool):
            raise ValueError(
                f"replaces_ready_provider is not boolean: {path}"
            )
        if replaces_ready_provider and not provider_only:
            raise ValueError(
                f"replaces_ready_provider requires provider_only: {path}"
            )
        if not provider_only:
            continue
        if path not in readiness_status:
            raise ValueError(f"provider-only source is absent from readiness: {path}")
        expected_status = "ready" if replaces_ready_provider else "blocked"
        if readiness_status[path] != expected_status:
            raise ValueError(
                "provider-only source has incompatible readiness status: "
                f"{path}; expected {expected_status}"
            )
        if "host_adaptation" not in unit:
            raise ValueError(
                f"provider-only source lacks a host adaptation: {path}"
            )
        if unit.get("roots"):
            raise ValueError(f"provider-only source also declares roots: {path}")
        paths.add(path)
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--import-spec", required=True, type=Path)
    object_input = parser.add_mutually_exclusive_group(required=True)
    object_input.add_argument("--object-root", type=Path)
    object_input.add_argument("--object-list", type=Path)
    parser.add_argument("--root-object", required=True, type=Path)
    parser.add_argument("--root-source", required=True)
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--provider-root", action="append", default=[])
    parser.add_argument("--external-provider-object-list", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nm", default="nm")
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument(
        "--workers", type=int, default=min(16, max(1, os.cpu_count() or 1))
    )
    parser.add_argument("--fail-on-unresolved", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.workers <= 64:
        raise SystemExit("--workers must be in [1, 64]")
    readiness_path = args.readiness.resolve()
    source_manifest_path = args.source_manifest.resolve()
    import_spec_path = args.import_spec.resolve()
    root_object = args.root_object.resolve()
    if not root_object.is_file():
        raise SystemExit(f"root object not found: {root_object}")

    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    import_spec = json.loads(import_spec_path.read_text(encoding="utf-8"))
    validate_inputs(readiness, source_manifest, import_spec)
    if source_manifest["readiness_report_sha256"] != sha256(readiness_path):
        raise SystemExit("source manifest readiness hash mismatch")
    if source_manifest["import_spec_sha256"] != sha256(import_spec_path):
        raise SystemExit("source manifest import-spec hash mismatch")

    nm = resolve_executable(args.nm, "nm")
    objdump = resolve_executable(args.objdump, "objdump")
    try:
        paths = available_provider_paths(
            readiness,
            import_spec,
            excluded_paths=frozenset((args.root_source,)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"provider source selection failed: {error}") from error
    try:
        if args.object_root is not None:
            object_root = args.object_root.resolve()
            if not object_root.is_dir():
                raise ValueError(
                    f"provider object root not found: {object_root}"
                )
            objects = map_ready_objects(object_root, paths)
        else:
            object_files = read_object_list(args.object_list.resolve())
            objects = map_ready_object_files(object_files, paths)
            if len(objects) != len(object_files):
                raise ValueError(
                    "provider object list contains unclaimed objects"
                )
            object_root = Path(os.path.commonpath(objects.values()))
            if object_root.is_file():
                object_root = object_root.parent
    except (OSError, ValueError) as error:
        raise SystemExit(f"provider object mapping failed: {error}") from error
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        rows = list(
            executor.map(
                lambda path: read_unit_symbols(
                    path,
                    object_path=objects[path],
                    object_root=object_root,
                    nm=nm,
                ),
                paths,
            )
        )
    units = {row.path: row for row in rows}
    if args.root_source in units:
        raise SystemExit("root source unexpectedly overlaps provider object pool")
    units[args.root_source] = read_root_symbols(
        args.root_source, object_path=root_object, nm=nm
    )

    owners = source_owner_index(source_manifest)
    external_definitions: dict[str, tuple[str, ...]] = {}
    external_provider_objects: list[Path] = []
    if args.external_provider_object_list is not None:
        try:
            external_provider_objects = read_object_list(
                args.external_provider_object_list.resolve()
            )
            external_definitions = external_definition_index(
                external_provider_objects,
                nm=nm,
            )
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise SystemExit(
                f"external provider indexing failed: {error}"
            ) from error
    initial_roots = {args.root_source: set(args.root)}
    for encoded in args.provider_root:
        source_path, separator, symbol = encoded.partition("=")
        if not separator or not source_path or not symbol:
            raise SystemExit(
                f"invalid --provider-root value, expected path=symbol: {encoded}"
            )
        if source_path not in paths:
            raise SystemExit(
                f"provider root source is absent from provider pool: {source_path}"
            )
        initial_roots.setdefault(source_path, set()).add(symbol)
    host_adapted_paths = frozenset(
        str(unit["path"])
        for unit in import_spec["translation_units"]
        if "host_adaptation" in unit
    )
    validate_root_ownership(
        initial_roots,
        owners,
        units=units,
        host_adapted_paths=host_adapted_paths,
    )
    object_paths = {**objects, args.root_source: root_object}
    graph_cache: dict[str, ObjectSectionGraph] = {}

    def graph_for(source_path: str) -> ObjectSectionGraph:
        if source_path not in graph_cache:
            graph_cache[source_path] = load_section_graph(
                source_path,
                object_path=object_paths[source_path],
                object_label=units[source_path].object_path,
                objdump=objdump,
            )
        return graph_cache[source_path]

    try:
        closure = compute_rooted_provider_closure(
            initial_roots=initial_roots,
            units=units,
            owners=owners,
            load_graph=graph_for,
            external_definitions=external_definitions,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise SystemExit(f"native root closure planning failed: {error}") from error

    report = {
        "schema": 1,
        "target": import_spec["target"],
        "claim_boundary": CLAIM_BOUNDARY,
        "decomp_revision": readiness["decomp_revision"],
        "readiness_report_sha256": sha256(readiness_path),
        "source_manifest_sha256": sha256(source_manifest_path),
        "import_spec_sha256": sha256(import_spec_path),
        "provider_object_count": len(paths),
        "provider_inventory_sha256": provider_inventory_sha256(
            {path: units[path] for path in paths}
        ),
        "external_provider_object_count": len(external_provider_objects),
        "external_provider_inventory_sha256": (
            external_provider_inventory_sha256(external_provider_objects)
        ),
        "tools": {
            "nm": {
                "name": nm.name,
                "version": executable_version(nm),
                "sha256": sha256(nm),
            },
            "objdump": {
                "name": objdump.name,
                "version": executable_version(objdump),
                "sha256": sha256(objdump),
            },
        },
        **closure,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    print(
        "native-root-closure=pass "
        f"providers={report['provider_object_count']} "
        f"units={report['selected_unit_count']} "
        f"sections={report['selected_section_count']} "
        f"edges={report['dependency_edge_count']} "
        f"unresolved={report['unresolved_symbol_count']} "
        f"ambiguous={report['ambiguous_symbol_count']} "
        f"weak={report['weak_unresolved_symbol_count']} "
        f"external={report['external_provider_edge_count']} sha256={digest}"
    )
    if args.fail_on_unresolved and (
        report["unresolved_symbol_count"] or report["ambiguous_symbol_count"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
