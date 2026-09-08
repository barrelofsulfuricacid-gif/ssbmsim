#!/usr/bin/env python3
"""Compute link dependencies among host-compiled decomp translation units.

The report is a mechanical object-symbol graph.  It does not claim that any
translation unit is initialized, consumed by the runtime, or Dolphin-qualified.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Iterable


CLAIM_BOUNDARY = "host-object-link-closure-not-runtime-or-behavioral-coverage"
IGNORED_SYMBOL_PREFIXES = (".refptr.",)


@dataclass(frozen=True)
class UnitSymbols:
    path: str
    object_path: str
    object_sha256: str
    definitions: tuple[str, ...]
    undefined: tuple[str, ...]
    weak_undefined: tuple[str, ...]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_nm_posix(output: str) -> tuple[set[str], set[str], set[str]]:
    """Parse one object's ``nm -g -P`` output.

    GNU nm uses lower-case ``w`` and ``v`` for unresolved weak symbols.  Those
    do not force another object into a static-link closure, so they are retained
    separately from strong undefined symbols.
    """

    definitions: set[str] = set()
    undefined: set[str] = set()
    weak_undefined: set[str] = set()
    for line_number, line in enumerate(output.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split()
        if len(fields) < 2 or len(fields[1]) != 1:
            raise ValueError(f"unrecognized nm output at line {line_number}: {line}")
        symbol, kind = fields[0], fields[1]
        if symbol.startswith(IGNORED_SYMBOL_PREFIXES):
            continue
        if kind in {"U", "u"}:
            undefined.add(symbol)
        elif kind in {"w", "v"}:
            weak_undefined.add(symbol)
        else:
            definitions.add(symbol)
    return definitions, undefined, weak_undefined


def resolve_executable(value: str, label: str) -> Path:
    candidate = shutil.which(value)
    if candidate is None:
        raise SystemExit(f"{label} executable not found: {value}")
    return Path(candidate).resolve()


def executable_version(executable: Path) -> str:
    process = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.splitlines()[0].strip()


def ready_paths(readiness: dict[str, object]) -> list[str]:
    paths = [
        str(unit["path"])
        for unit in readiness["translation_units"]
        if unit["compile_status"] == "ready"
    ]
    if len(paths) != int(readiness["ready_count"]):
        raise ValueError("readiness ready-unit count mismatch")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate ready translation unit")
    return sorted(paths)


def map_ready_object_files(
    object_files: Iterable[Path], unit_paths: Iterable[str]
) -> dict[str, Path]:
    object_files = sorted(
        (path.resolve() for path in object_files),
        key=lambda path: path.as_posix().casefold(),
    )
    if not object_files:
        raise ValueError("provider object list is empty")
    if len(object_files) != len(set(object_files)):
        raise ValueError("provider object list contains duplicates")
    invalid = [
        path
        for path in object_files
        if not path.is_file() or path.suffix.lower() not in {".o", ".obj"}
    ]
    if invalid:
        raise ValueError(f"invalid provider object: {invalid[0]}")
    relative_objects = [
        (path, path.as_posix().casefold())
        for path in object_files
    ]
    result: dict[str, Path] = {}
    claimed_objects: set[Path] = set()
    for unit_path in unit_paths:
        normalized = PurePosixPath(unit_path).as_posix().casefold()
        suffixes = (f"{normalized}.o", f"{normalized}.obj")
        matches = [
            path
            for path, relative in relative_objects
            if any(relative == suffix or relative.endswith(f"/{suffix}") for suffix in suffixes)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one object for {unit_path}, found {len(matches)}"
            )
        if matches[0] in claimed_objects:
            raise ValueError(f"object mapped to more than one unit: {matches[0]}")
        claimed_objects.add(matches[0])
        result[unit_path] = matches[0]
    return result


def map_ready_objects(
    object_root: Path, unit_paths: Iterable[str]
) -> dict[str, Path]:
    return map_ready_object_files(
        (
            path
            for path in object_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".o", ".obj"}
        ),
        unit_paths,
    )


def read_unit_symbols(
    path: str, *, object_path: Path, object_root: Path, nm: Path
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
        path=path,
        object_path=object_path.relative_to(object_root).as_posix(),
        object_sha256=sha256(object_path),
        definitions=tuple(sorted(definitions)),
        undefined=tuple(sorted(undefined)),
        weak_undefined=tuple(sorted(weak_undefined)),
    )


def definition_index(units: dict[str, UnitSymbols]) -> dict[str, tuple[str, ...]]:
    index: dict[str, set[str]] = {}
    for path, unit in units.items():
        for symbol in unit.definitions:
            index.setdefault(symbol, set()).add(path)
    return {symbol: tuple(sorted(paths)) for symbol, paths in index.items()}


def source_owner_index(
    source_manifest: dict[str, object],
) -> dict[str, tuple[dict[str, object], ...]]:
    owners: dict[str, list[dict[str, object]]] = {}
    for symbol in source_manifest["symbols"]:
        owners.setdefault(str(symbol["name"]), []).append(
            {
                "path": symbol["source_path"],
                "port_status": symbol["port_status"],
                "symbol_type": symbol["symbol_type"],
            }
        )
    return {
        symbol: tuple(
            sorted(
                records,
                key=lambda record: (
                    str(record["path"]),
                    str(record["port_status"]),
                    str(record["symbol_type"]),
                ),
            )
        )
        for symbol, records in owners.items()
    }


def choose_provider(
    symbol: str,
    providers: tuple[str, ...],
    owners: dict[str, tuple[dict[str, object], ...]],
) -> tuple[str | None, str]:
    if len(providers) == 1:
        return providers[0], "unique-ready-definition"
    owned_paths = {
        str(owner["path"])
        for owner in owners.get(symbol, ())
        if owner["path"] in providers
    }
    if len(owned_paths) == 1:
        return next(iter(owned_paths)), "decomp-symbol-owner"
    return None, "ambiguous-ready-definitions"


def missing_classification(
    symbol: str, owners: dict[str, tuple[dict[str, object], ...]]
) -> str:
    records = owners.get(symbol, ())
    statuses = {str(record["port_status"]) for record in records}
    if statuses & {
        "selected-native-import-host-adapted",
        "selected-rooted-native-import-host-adapted",
    }:
        return "host-adapted-source-provider-outside-ready-object-set"
    if "host-object-blocked" in statuses:
        return "blocked-source-provider"
    if "host-object-excluded-from-native-provider-inventory" in statuses:
        return "excluded-noncompetitive-source-provider"
    if "outside-gameplay-candidate-scope" in statuses:
        return "outside-gameplay-source-provider"
    if statuses & {
        "host-object-ready",
        "selected-native-import",
        "selected-rooted-native-import",
    }:
        return "ready-source-symbol-not-exported"
    if records:
        return "source-symbol-without-ready-provider"
    return "external-or-source-unowned"


def compute_closure(
    roots: Iterable[str],
    units: dict[str, UnitSymbols],
    owners: dict[str, tuple[dict[str, object], ...]],
) -> dict[str, object]:
    root_list = sorted(set(roots))
    unknown = [root for root in root_list if root not in units]
    if unknown:
        raise ValueError("root is not host-object ready: " + ", ".join(unknown))
    definitions = definition_index(units)
    closure = set(root_list)
    queue = list(root_list)
    edges: set[tuple[str, str, str, str]] = set()
    ambiguous: dict[str, set[str]] = {}
    unresolved: dict[str, set[str]] = {}

    while queue:
        consumer = queue.pop(0)
        for symbol in units[consumer].undefined:
            providers = definitions.get(symbol, ())
            provider, reason = choose_provider(symbol, providers, owners)
            if provider is None:
                target = ambiguous if providers else unresolved
                target.setdefault(symbol, set()).add(consumer)
                continue
            edges.add((consumer, provider, symbol, reason))
            if provider not in closure:
                closure.add(provider)
                queue.append(provider)

    unresolved_rows = [
        {
            "symbol": symbol,
            "consumers": sorted(consumers),
            "classification": missing_classification(symbol, owners),
            "source_owners": list(owners.get(symbol, ())),
        }
        for symbol, consumers in sorted(unresolved.items())
    ]
    ambiguous_rows = [
        {
            "symbol": symbol,
            "consumers": sorted(consumers),
            "ready_providers": list(definitions.get(symbol, ())),
            "source_owners": list(owners.get(symbol, ())),
        }
        for symbol, consumers in sorted(ambiguous.items())
    ]
    return {
        "roots": root_list,
        "closure_units": sorted(closure),
        "dependency_edges": [
            {
                "consumer": consumer,
                "provider": provider,
                "symbol": symbol,
                "selection": reason,
            }
            for consumer, provider, symbol, reason in sorted(edges)
        ],
        "unresolved_symbols": unresolved_rows,
        "ambiguous_symbols": ambiguous_rows,
    }


def validate_inputs(
    readiness: dict[str, object],
    source_manifest: dict[str, object],
    import_spec: dict[str, object],
) -> None:
    if readiness.get("schema") != 1:
        raise ValueError("unsupported readiness schema")
    if source_manifest.get("schema") != 2:
        raise ValueError("unsupported source-manifest schema")
    if import_spec.get("schema") != 1:
        raise ValueError("unsupported import-spec schema")
    revisions = {
        str(readiness.get("decomp_revision")),
        str(source_manifest.get("decomp_revision")),
        str(import_spec.get("decomp_revision")),
    }
    if len(revisions) != 1:
        raise ValueError("decomp revision mismatch across inputs")
    if source_manifest.get("readiness_report_sha256") is None:
        raise ValueError("source manifest lacks readiness provenance")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--import-spec", required=True, type=Path)
    parser.add_argument("--object-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--nm", default="nm")
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
    object_root = args.object_root.resolve()
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    import_spec = json.loads(import_spec_path.read_text(encoding="utf-8"))
    validate_inputs(readiness, source_manifest, import_spec)
    if source_manifest["readiness_report_sha256"] != sha256(readiness_path):
        raise SystemExit("source manifest readiness hash mismatch")
    if source_manifest["import_spec_sha256"] != sha256(import_spec_path):
        raise SystemExit("source manifest import-spec hash mismatch")

    paths = ready_paths(readiness)
    objects = map_ready_objects(object_root, paths)
    nm = resolve_executable(args.nm, "nm")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        unit_rows = list(
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
    units = {unit.path: unit for unit in unit_rows}
    roots = args.root or [
        str(unit["path"]) for unit in import_spec["translation_units"]
    ]
    owners = source_owner_index(source_manifest)
    closure = compute_closure(roots, units, owners)
    closure_paths = set(closure["closure_units"])
    report = {
        "schema": 1,
        "target": import_spec["target"],
        "claim_boundary": CLAIM_BOUNDARY,
        "decomp_revision": readiness["decomp_revision"],
        "readiness_report_sha256": sha256(readiness_path),
        "source_manifest_sha256": sha256(source_manifest_path),
        "import_spec_sha256": sha256(import_spec_path),
        "nm": {
            "name": nm.name,
            "version": executable_version(nm),
            "sha256": sha256(nm),
        },
        "ready_object_count": len(units),
        "root_unit_count": len(closure["roots"]),
        "closure_unit_count": len(closure_paths),
        "dependency_edge_count": len(closure["dependency_edges"]),
        "unresolved_symbol_count": len(closure["unresolved_symbols"]),
        "ambiguous_symbol_count": len(closure["ambiguous_symbols"]),
        **closure,
        "translation_units": [
            {
                "path": unit.path,
                "object_path": unit.object_path,
                "object_sha256": unit.object_sha256,
                "definition_count": len(unit.definitions),
                "undefined_count": len(unit.undefined),
                "weak_undefined_count": len(unit.weak_undefined),
                "definitions": list(unit.definitions),
                "undefined": list(unit.undefined),
                "weak_undefined": list(unit.weak_undefined),
            }
            for unit in sorted(
                (units[path] for path in closure_paths), key=lambda unit: unit.path
            )
        ],
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    print(
        "native-link-closure=pass "
        f"roots={report['root_unit_count']} units={report['closure_unit_count']} "
        f"edges={report['dependency_edge_count']} "
        f"unresolved={report['unresolved_symbol_count']} "
        f"ambiguous={report['ambiguous_symbol_count']} sha256={digest}"
    )
    if args.fail_on_unresolved and (
        report["unresolved_symbol_count"] or report["ambiguous_symbol_count"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
