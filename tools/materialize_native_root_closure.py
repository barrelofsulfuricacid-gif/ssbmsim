#!/usr/bin/env python3
"""Materialize one planned native source-root closure as an audited archive.

The archive contains host-compiled, section-sliced decomp source objects.  It
does not execute guest instructions and does not establish runtime or
behavioral coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable

from analyze_native_link_closure import (
    map_ready_object_files,
    map_ready_objects,
    parse_nm_posix,
    sha256,
)
from plan_native_root_closure import CLAIM_BOUNDARY as PLAN_CLAIM_BOUNDARY
from plan_native_root_closure import read_object_list
from slice_native_object import (
    executable_version,
    resolve_executable,
    slice_object,
)


CLAIM_BOUNDARY = (
    "materialized-native-root-archive-not-runtime-or-behavioral-coverage"
)


def validate_plan(plan: dict[str, object]) -> list[dict[str, object]]:
    if plan.get("schema") != 1:
        raise ValueError("unsupported native root-closure plan schema")
    if plan.get("claim_boundary") != PLAN_CLAIM_BOUNDARY:
        raise ValueError("invalid native root-closure plan claim boundary")
    selected = plan.get("selected_units")
    if not isinstance(selected, list) or not selected:
        raise ValueError("native root-closure plan selects no units")
    if len(selected) != int(plan.get("selected_unit_count", -1)):
        raise ValueError("native root-closure selected-unit count mismatch")
    paths = [str(unit.get("source_path")) for unit in selected]
    if len(paths) != len(set(paths)):
        raise ValueError("native root-closure plan has duplicate source units")
    if paths != sorted(paths):
        raise ValueError("native root-closure selected units are not sorted")
    section_count = sum(
        len(unit.get("selected_sections", [])) for unit in selected
    )
    if section_count != int(plan.get("selected_section_count", -1)):
        raise ValueError("native root-closure selected-section count mismatch")
    for field, rows in (
        ("dependency_edge_count", plan.get("dependency_edges")),
        ("unresolved_symbol_count", plan.get("unresolved_symbols")),
        ("ambiguous_symbol_count", plan.get("ambiguous_symbols")),
        ("weak_unresolved_symbol_count", plan.get("weak_unresolved_symbols")),
        ("external_provider_edge_count", plan.get("external_provider_edges")),
    ):
        if not isinstance(rows, list) or len(rows) != int(plan.get(field, -1)):
            raise ValueError(f"native root-closure {field} mismatch")
    if int(plan["ambiguous_symbol_count"]) != 0:
        raise ValueError("cannot materialize a plan with ambiguous providers")
    external_inventory = str(
        plan.get("external_provider_inventory_sha256", "")
    )
    if len(external_inventory) != 64 or any(
        ch not in "0123456789abcdef" for ch in external_inventory
    ):
        raise ValueError("invalid external provider inventory hash")
    roots_by_source = plan.get("roots_by_source")
    if not isinstance(roots_by_source, dict):
        raise ValueError("native root-closure roots_by_source is missing")
    if set(roots_by_source) != set(paths):
        raise ValueError("native root-closure source/root set mismatch")
    for unit in selected:
        source_path = str(unit["source_path"])
        roots = unit.get("roots")
        sections = unit.get("selected_sections")
        if not isinstance(roots, list) or not roots:
            raise ValueError(f"selected source has no roots: {source_path}")
        if roots != sorted(set(roots)):
            raise ValueError(f"selected roots are not canonical: {source_path}")
        if roots != roots_by_source[source_path]:
            raise ValueError(f"selected roots disagree with plan: {source_path}")
        if not isinstance(sections, list) or sections != sorted(set(sections)):
            raise ValueError(
                f"selected sections are not canonical: {source_path}"
            )
        digest = str(unit.get("object_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"invalid object hash for {source_path}")
    return selected


def verify_input_hashes(
    plan: dict[str, object],
    *,
    readiness: Path,
    source_manifest: Path,
    import_spec: Path,
) -> None:
    expected = {
        "readiness_report_sha256": readiness,
        "source_manifest_sha256": source_manifest,
        "import_spec_sha256": import_spec,
    }
    for field, path in expected.items():
        if not path.is_file():
            raise ValueError(f"materializer input not found: {path}")
        if str(plan.get(field, "")) != sha256(path):
            raise ValueError(f"native root-closure {field} mismatch")


def resolve_selected_objects(
    plan: dict[str, object],
    *,
    provider_objects: Iterable[Path],
    root_source: str,
    root_object: Path,
) -> dict[str, Path]:
    selected = validate_plan(plan)
    initial_roots = plan.get("initial_roots")
    if not isinstance(initial_roots, dict) or root_source not in initial_roots:
        raise ValueError("materializer root source does not match plan")
    selected_paths = [str(unit["source_path"]) for unit in selected]
    unexpected_initial_sources = set(initial_roots) - set(selected_paths)
    if unexpected_initial_sources:
        raise ValueError(
            "materializer initial-root source is not selected: "
            + ", ".join(sorted(unexpected_initial_sources))
        )
    if root_source not in selected_paths:
        raise ValueError("materializer root source is not selected")
    if not root_object.is_file():
        raise ValueError(f"root object not found: {root_object}")
    providers = [path for path in selected_paths if path != root_source]
    result = map_ready_object_files(provider_objects, providers)
    result[root_source] = root_object.resolve()
    return result


def member_name(index: int, source_path: str, suffix: str) -> str:
    source_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]
    return f"{index:03d}_{source_hash}{suffix.lower()}"


def parse_symbol_redefinitions(
    values: Iterable[str],
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    old_names: set[str] = set()
    new_names: set[str] = set()
    for value in values:
        old, separator, new = value.partition("=")
        if separator == "" or not old or not new or old == new:
            raise ValueError(f"invalid symbol redefinition: {value}")
        if any(character.isspace() for character in old + new):
            raise ValueError(f"invalid symbol redefinition: {value}")
        if old in old_names or new in new_names:
            raise ValueError(f"duplicate symbol redefinition: {value}")
        old_names.add(old)
        new_names.add(new)
        result.append((old, new))
    return tuple(sorted(result))


def redefine_symbols(
    objcopy: Path,
    path: Path,
    definitions: tuple[tuple[str, str], ...],
) -> None:
    if not definitions:
        return
    rewritten = path.with_suffix(path.suffix + ".renamed")
    command = [str(objcopy), "--strip-unneeded"]
    for old, new in definitions:
        command.extend(("--redefine-sym", f"{old}={new}"))
    command.extend((str(path), str(rewritten)))
    subprocess.run(command, check=True)
    os.replace(rewritten, path)


def renamed_symbol(
    symbol: str,
    definitions: tuple[tuple[str, str], ...],
) -> str:
    return dict(definitions).get(symbol, symbol)


def create_archive(ar: Path, output: Path, members: list[Path]) -> None:
    command = [str(ar), "rcsD", str(output)]
    command.extend(member.name for member in members)
    subprocess.run(command, cwd=members[0].parent, check=True)


def archive_members(ar: Path, archive: Path) -> list[str]:
    process = subprocess.run(
        [str(ar), "t", str(archive)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in process.stdout.splitlines() if line.strip()]


def audit_archive_link(
    *,
    linker: Path,
    linker_arguments: tuple[str, ...],
    nm: Path,
    archive: Path,
    plan: dict[str, object],
    output_a: Path,
    output_b: Path,
    symbol_redefinitions: tuple[tuple[str, str], ...] = (),
) -> dict[str, object]:
    initial_roots = sorted(
        {
            str(root)
            for roots in plan["initial_roots"].values()
            for root in roots
        }
    )
    command = [str(linker), *linker_arguments, "-r"]
    for root in initial_roots:
        command.extend(("-u", root))
    command.append(str(archive))
    for output in (output_a, output_b):
        subprocess.run([*command, "-o", str(output)], check=True)
    digest = sha256(output_a)
    if digest != sha256(output_b):
        raise ValueError("native root archive link is not deterministic")
    process = subprocess.run(
        [str(nm), "-g", "-P", str(output_a)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    definitions, undefined, weak = parse_nm_posix(process.stdout)
    selected_roots = {
        renamed_symbol(str(root), symbol_redefinitions)
        for roots in plan["roots_by_source"].values()
        for root in roots
    }
    missing_roots = sorted(selected_roots - definitions)
    if missing_roots:
        raise ValueError(
            "archive link did not extract all selected roots: "
            + ", ".join(missing_roots)
        )
    required_undefined = {
        renamed_symbol(str(row["symbol"]), symbol_redefinitions)
        for row in plan["unresolved_symbols"]
    }
    external_symbols = {
        renamed_symbol(str(row["symbol"]), symbol_redefinitions)
        for row in plan["external_provider_edges"]
    }
    shadowed_external = external_symbols.intersection(definitions)
    if shadowed_external:
        raise ValueError(
            "archive defines symbols reserved for native host providers: "
            + ", ".join(sorted(shadowed_external))
        )
    allowed_undefined = required_undefined.union(external_symbols)
    if not required_undefined.issubset(undefined) or not undefined.issubset(
        allowed_undefined
    ):
        raise ValueError(
            "archive link unresolved frontier differs from plan: "
            f"missing={sorted(required_undefined - undefined)} "
            f"unexpected={sorted(undefined - allowed_undefined)}"
        )
    expected_weak = {
        renamed_symbol(str(row["symbol"]), symbol_redefinitions)
        for row in plan["weak_unresolved_symbols"]
    }
    if not expected_weak.issubset(weak):
        raise ValueError(
            "archive link lost planned weak symbols: "
            + ", ".join(sorted(expected_weak - weak))
        )
    return {
        "sha256": digest,
        "bytes": output_a.stat().st_size,
        "initial_roots": initial_roots,
        "selected_root_count": len(selected_roots),
        "strong_unresolved_symbols": sorted(undefined),
        "weak_unresolved_symbols": sorted(weak),
    }


def materialize_plan(
    *,
    plan: dict[str, object],
    plan_sha256: str,
    objects: dict[str, Path],
    output_archive: Path,
    output_manifest: Path,
    objdump: Path,
    objcopy: Path,
    linker: Path,
    linker_arguments: tuple[str, ...] = (),
    symbol_redefinitions: tuple[tuple[str, str], ...] = (),
    ar: Path,
    nm: Path,
) -> dict[str, object]:
    selected = validate_plan(plan)
    selected_paths = {str(unit["source_path"]) for unit in selected}
    if set(objects) != selected_paths:
        raise ValueError("materializer object map does not match selected units")
    output_archive.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="native-root-materialize-", dir=output_archive.parent
    ) as temporary_directory:
        staging = Path(temporary_directory)
        member_paths: list[Path] = []
        unit_rows: list[dict[str, object]] = []
        external_symbols = {
            str(row["symbol"]) for row in plan["external_provider_edges"]
        }
        for index, unit in enumerate(selected):
            source_path = str(unit["source_path"])
            input_path = objects[source_path].resolve()
            input_digest = sha256(input_path)
            if input_digest != str(unit["object_sha256"]):
                raise ValueError(f"planned object hash mismatch: {source_path}")
            member = staging / member_name(index, source_path, input_path.suffix)
            closure = slice_object(
                objdump=objdump,
                objcopy=objcopy,
                linker=linker,
                linker_arguments=linker_arguments,
                input_path=input_path,
                output_path=member,
                roots=unit["roots"],
                external_symbols=external_symbols,
            )
            for field in (
                "roots",
                "selected_sections",
                "section_edges",
                "external_frontier",
                "object_format",
                "slice_method",
            ):
                if closure[field] != unit[field]:
                    raise ValueError(
                        f"materialized {field} differs from plan: {source_path}"
                    )
            redefine_symbols(objcopy, member, symbol_redefinitions)
            member_paths.append(member)
            unit_rows.append(
                {
                    "source_path": source_path,
                    "planned_object_path": unit["object_path"],
                    "input_sha256": input_digest,
                    "member": member.name,
                    "member_sha256": sha256(member),
                    "roots": unit["roots"],
                    "selected_section_count": len(unit["selected_sections"]),
                    "external_frontier_count": len(unit["external_frontier"]),
                }
            )

        first_archive = staging / "closure-a.a"
        second_archive = staging / "closure-b.a"
        create_archive(ar, first_archive, member_paths)
        create_archive(ar, second_archive, member_paths)
        first_digest = sha256(first_archive)
        second_digest = sha256(second_archive)
        if first_digest != second_digest:
            raise ValueError("native root archive is not deterministic")
        expected_members = [path.name for path in member_paths]
        actual_members = archive_members(ar, first_archive)
        if actual_members != expected_members:
            raise ValueError(
                "native root archive member order mismatch: "
                f"expected {expected_members}, got {actual_members}"
            )
        link_audit = audit_archive_link(
            linker=linker,
            linker_arguments=linker_arguments,
            nm=nm,
            archive=first_archive,
            plan=plan,
            output_a=staging / "closure-link-a.o",
            output_b=staging / "closure-link-b.o",
            symbol_redefinitions=symbol_redefinitions,
        )
        os.replace(first_archive, output_archive)

    manifest = {
        "schema": 1,
        "target": plan["target"],
        "claim_boundary": CLAIM_BOUNDARY,
        "decomp_revision": plan["decomp_revision"],
        "plan": {
            "sha256": plan_sha256,
            "claim_boundary": plan["claim_boundary"],
            "provider_inventory_sha256": plan["provider_inventory_sha256"],
            "external_provider_inventory_sha256": plan[
                "external_provider_inventory_sha256"
            ],
        },
        "inputs": {
            "readiness_report_sha256": plan["readiness_report_sha256"],
            "source_manifest_sha256": plan["source_manifest_sha256"],
            "import_spec_sha256": plan["import_spec_sha256"],
        },
        "tools": {
            name: {
                "name": path.name,
                "version": executable_version(path),
                "sha256": sha256(path),
            }
            for name, path in (
                ("objdump", objdump),
                ("objcopy", objcopy),
                ("linker", linker),
                ("ar", ar),
                ("nm", nm),
            )
        },
        "linker_arguments": list(linker_arguments),
        "symbol_redefinitions": [
            {"from": old, "to": new}
            for old, new in symbol_redefinitions
        ],
        "selected_unit_count": len(unit_rows),
        "selected_section_count": plan["selected_section_count"],
        "dependency_edge_count": plan["dependency_edge_count"],
        "unresolved_symbol_count": plan["unresolved_symbol_count"],
        "ambiguous_symbol_count": plan["ambiguous_symbol_count"],
        "weak_unresolved_symbol_count": plan["weak_unresolved_symbol_count"],
        "external_provider_edge_count": plan["external_provider_edge_count"],
        "archive": {
            "name": output_archive.name,
            "sha256": sha256(output_archive),
            "bytes": output_archive.stat().st_size,
            "member_count": len(unit_rows),
            "members": [row["member"] for row in unit_rows],
        },
        "link_audit": link_audit,
        "translation_units": unit_rows,
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        prefix=output_manifest.name + ".",
        suffix=".tmp",
        dir=output_manifest.parent,
        delete=False,
        mode="w",
        encoding="utf-8",
        newline="\n",
    ) as temporary:
        temporary.write(encoded)
        temporary_manifest = Path(temporary.name)
    try:
        os.replace(temporary_manifest, output_manifest)
    finally:
        if temporary_manifest.exists():
            temporary_manifest.unlink()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--import-spec", required=True, type=Path)
    object_input = parser.add_mutually_exclusive_group(required=True)
    object_input.add_argument("--object-root", type=Path)
    object_input.add_argument("--object-list", type=Path)
    parser.add_argument("--root-source", required=True)
    parser.add_argument("--root-object", required=True, type=Path)
    parser.add_argument("--output-archive", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--objcopy", default="objcopy")
    parser.add_argument("--linker", default="ld")
    parser.add_argument("--linker-argument", action="append", default=[])
    parser.add_argument("--redefine-symbol", action="append", default=[])
    parser.add_argument("--ar", default="ar")
    parser.add_argument("--nm", default="nm")
    args = parser.parse_args()

    try:
        plan_path = args.plan.resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        validate_plan(plan)
        verify_input_hashes(
            plan,
            readiness=args.readiness.resolve(),
            source_manifest=args.source_manifest.resolve(),
            import_spec=args.import_spec.resolve(),
        )
        if args.object_root is not None:
            provider_objects = map_ready_objects(
                args.object_root.resolve(),
                [
                    str(unit["source_path"])
                    for unit in plan["selected_units"]
                    if str(unit["source_path"]) != args.root_source
                ],
            ).values()
        else:
            provider_objects = read_object_list(args.object_list.resolve())
        objects = resolve_selected_objects(
            plan,
            provider_objects=provider_objects,
            root_source=args.root_source,
            root_object=args.root_object.resolve(),
        )
        objdump = resolve_executable(args.objdump, "objdump")
        objcopy = resolve_executable(args.objcopy, "objcopy")
        linker = resolve_executable(args.linker, "linker")
        ar = resolve_executable(args.ar, "archiver")
        nm = resolve_executable(args.nm, "nm")
        manifest = materialize_plan(
            plan=plan,
            plan_sha256=sha256(plan_path),
            objects=objects,
            output_archive=args.output_archive.resolve(),
            output_manifest=args.output_manifest.resolve(),
            objdump=objdump,
            objcopy=objcopy,
            linker=linker,
            linker_arguments=tuple(args.linker_argument),
            symbol_redefinitions=parse_symbol_redefinitions(
                args.redefine_symbol
            ),
            ar=ar,
            nm=nm,
        )
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(
            f"native root-closure materialization failed: {error}"
        ) from error

    print(
        "native-root-materialization=pass "
        f"units={manifest['selected_unit_count']} "
        f"sections={manifest['selected_section_count']} "
        f"unresolved={manifest['unresolved_symbol_count']} "
        f"archive_sha256={manifest['archive']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
