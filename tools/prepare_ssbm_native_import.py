#!/usr/bin/env python3
"""Verify and expose pinned doldecomp translation units to the host build."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess

from apply_source_adaptation import (
    CLAIM_BOUNDARY as ADAPTATION_CLAIM_BOUNDARY,
    apply_adaptation,
    load_adaptation,
    prepare_header_adaptations,
    verify_native_dependencies,
)
from native_source_policy import source_compile_options


FORBIDDEN_RUNTIME_TOKENS = (
    "CPUState",
    "DOLRECOMP",
    "guest_pc",
    "guest_memory",
    "mmio_read",
    "mmio_write",
)


def git_revision(root: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower()


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_authority_sha256(spec: dict[str, object]) -> str:
    authority = {
        "target": spec["target"],
        "decomp_revision": spec["decomp_revision"],
        "dependencies": spec["dependencies"],
        "header_adaptations": spec.get("header_adaptations", []),
        "provider_exclusions": spec.get("provider_exclusions", []),
        "source_compile_options": spec.get("source_compile_options", []),
    }
    encoded = json.dumps(authority, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def cmake_path(path: pathlib.Path) -> str:
    return path.resolve().as_posix().replace('"', '\\"')


def safe_relative_path(value: object, label: str) -> pathlib.PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"missing {label} path")
    relative = pathlib.PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"unsafe {label} path: {relative}")
    return relative


def source_unit_id(path: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", path)
    if not result or result[0].isdigit():
        result = "unit_" + result
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decomp", required=True, type=pathlib.Path)
    parser.add_argument("--aurora", required=True, type=pathlib.Path)
    parser.add_argument("--spec", required=True, type=pathlib.Path)
    parser.add_argument("--readiness", required=True, type=pathlib.Path)
    parser.add_argument("--compat", required=True, type=pathlib.Path)
    parser.add_argument("--output-cmake", required=True, type=pathlib.Path)
    parser.add_argument("--output-manifest", required=True, type=pathlib.Path)
    args = parser.parse_args()

    root = args.decomp.resolve()
    aurora = args.aurora.resolve()
    compat = args.compat.resolve()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
    if spec.get("schema") != 1:
        raise SystemExit("unsupported native import spec schema")
    if readiness.get("schema") != 1:
        raise SystemExit("unsupported native readiness schema")
    if readiness.get("claim_boundary") != "strict-host-compile-readiness-only":
        raise SystemExit("native readiness claim boundary is missing or invalid")
    expected_revision = str(spec["decomp_revision"]).lower()
    actual_revision = git_revision(root)
    if actual_revision != expected_revision:
        raise SystemExit(
            "decomp revision mismatch: "
            f"expected {expected_revision}, got {actual_revision}"
        )
    expected_aurora_revision = str(
        spec["dependencies"]["aurora"]["revision"]
    ).lower()
    actual_aurora_revision = git_revision(aurora)
    if actual_aurora_revision != expected_aurora_revision:
        raise SystemExit(
            "Aurora revision mismatch: "
            f"expected {expected_aurora_revision}, got {actual_aurora_revision}"
        )
    aurora_types = aurora / "include" / "dolphin" / "types.h"
    if not aurora_types.is_file():
        raise SystemExit("Aurora checkout lacks source-level Dolphin SDK headers")
    expected_types_hash = str(
        spec["dependencies"]["aurora"]["types_header_sha256"]
    ).lower()
    actual_types_hash = sha256(aurora_types)
    if actual_types_hash != expected_types_hash:
        raise SystemExit(
            "Aurora types header mismatch: "
            f"expected {expected_types_hash}, got {actual_types_hash}"
        )
    aurora_pad = aurora / "include" / "dolphin" / "pad.h"
    expected_pad_hash = str(
        spec["dependencies"]["aurora"]["pad_header_sha256"]
    ).lower()
    actual_pad_hash = sha256(aurora_pad)
    if actual_pad_hash != expected_pad_hash:
        raise SystemExit(
            "Aurora PAD header mismatch: "
            f"expected {expected_pad_hash}, got {actual_pad_hash}"
        )
    aurora_gx_compat = aurora / "include" / "dolphin" / "gx" / "GXAurora.h"
    expected_gx_compat_hash = str(
        spec["dependencies"]["aurora"]["gx_compat_header_sha256"]
    ).lower()
    actual_gx_compat_hash = sha256(aurora_gx_compat)
    if actual_gx_compat_hash != expected_gx_compat_hash:
        raise SystemExit(
            "Aurora GX compatibility header mismatch: "
            f"expected {expected_gx_compat_hash}, got {actual_gx_compat_hash}"
        )
    aurora_gx_enum = aurora / "include" / "dolphin" / "gx" / "GXEnum.h"
    expected_gx_enum_hash = str(
        spec["dependencies"]["aurora"]["gx_enum_header_sha256"]
    ).lower()
    actual_gx_enum_hash = sha256(aurora_gx_enum)
    if actual_gx_enum_hash != expected_gx_enum_hash:
        raise SystemExit(
            "Aurora GX enum header mismatch: "
            f"expected {expected_gx_enum_hash}, got {actual_gx_enum_hash}"
        )
    aurora_gx_tev = aurora / "include" / "dolphin" / "gx" / "GXTev.h"
    expected_gx_tev_hash = str(
        spec["dependencies"]["aurora"]["gx_tev_header_sha256"]
    ).lower()
    actual_gx_tev_hash = sha256(aurora_gx_tev)
    if actual_gx_tev_hash != expected_gx_tev_hash:
        raise SystemExit(
            "Aurora GX TEV header mismatch: "
            f"expected {expected_gx_tev_hash}, got {actual_gx_tev_hash}"
        )
    aurora_gx_pixel = aurora / "include" / "dolphin" / "gx" / "GXPixel.h"
    expected_gx_pixel_hash = str(
        spec["dependencies"]["aurora"]["gx_pixel_header_sha256"]
    ).lower()
    actual_gx_pixel_hash = sha256(aurora_gx_pixel)
    if actual_gx_pixel_hash != expected_gx_pixel_hash:
        raise SystemExit(
            "Aurora GX pixel header mismatch: "
            f"expected {expected_gx_pixel_hash}, got {actual_gx_pixel_hash}"
        )
    if readiness.get("decomp_revision") != actual_revision:
        raise SystemExit("native readiness decomp revision mismatch")
    if readiness.get("aurora", {}).get("revision") != actual_aurora_revision:
        raise SystemExit("native readiness Aurora revision mismatch")
    if readiness.get("source_authority_sha256") != source_authority_sha256(spec):
        raise SystemExit("native readiness source-authority hash mismatch")
    platform_header = compat / "platform.h"
    if readiness.get("native_platform_sha256") != sha256(platform_header):
        raise SystemExit("native readiness platform hash mismatch")

    generated_root = args.output_cmake.resolve().parent
    adapted_header_root = generated_root / "adapted-include"
    try:
        header_adaptations = prepare_header_adaptations(
            spec,
            decomp=root,
            spec_dir=args.spec.resolve().parent,
            output_root=adapted_header_root,
        )
    except ValueError as error:
        raise SystemExit(f"native header adaptation failed: {error}") from error
    if readiness.get("native_header_adaptations", []) != header_adaptations:
        raise SystemExit("native readiness header-adaptation evidence mismatch")
    try:
        compile_policy = source_compile_options(spec, decomp=root)
    except ValueError as error:
        raise SystemExit(f"native source compile policy failed: {error}") from error
    if readiness.get("native_source_compile_options", []) != compile_policy:
        raise SystemExit("native readiness source-compile evidence mismatch")
    adapted_root = generated_root / "adapted-source"
    units: list[dict[str, object]] = []
    build_paths: dict[str, pathlib.Path] = {}
    adapted_include_dirs: dict[str, pathlib.Path] = {}
    seen: set[str] = set()
    for source in spec["translation_units"]:
        relative = safe_relative_path(source["path"], "source")
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise SystemExit(f"duplicate translation unit: {relative_text}")
        seen.add(relative_text)
        path = root.joinpath(*relative.parts)
        if not path.is_file():
            raise SystemExit(f"missing translation unit: {relative_text}")
        actual_hash = sha256(path)
        expected_hash = str(source["sha256"]).lower()
        if actual_hash != expected_hash:
            raise SystemExit(
                f"source hash mismatch for {relative_text}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        text = path.read_text(encoding="utf-8")
        forbidden = [token for token in FORBIDDEN_RUNTIME_TOKENS if token in text]
        if forbidden:
            raise SystemExit(
                f"emulator runtime token in {relative_text}: {', '.join(forbidden)}"
            )
        unit: dict[str, object] = {
            "path": relative_text,
            "sha256": actual_hash,
            "role": str(source["role"]),
            "bytes": path.stat().st_size,
        }
        provider_only = source.get("provider_only", False)
        if not isinstance(provider_only, bool):
            raise SystemExit(
                f"provider_only for {relative_text} is not a boolean"
            )
        if provider_only:
            unit["provider_only"] = True
        replaces_ready_provider = source.get("replaces_ready_provider", False)
        if not isinstance(replaces_ready_provider, bool):
            raise SystemExit(
                f"replaces_ready_provider for {relative_text} is not a boolean"
            )
        if replaces_ready_provider:
            if not provider_only:
                raise SystemExit(
                    "replaces_ready_provider requires provider_only for "
                    f"{relative_text}"
                )
            unit["replaces_ready_provider"] = True
        original_include_dir = source.get("original_include_dir", True)
        if not isinstance(original_include_dir, bool):
            raise SystemExit(
                f"original_include_dir for {relative_text} is not a boolean"
            )
        if not original_include_dir:
            unit["original_include_dir"] = False
        roots_entry = source.get("roots", [])
        if not isinstance(roots_entry, list) or any(
            not isinstance(root_symbol, str) or not root_symbol.strip()
            for root_symbol in roots_entry
        ):
            raise SystemExit(f"invalid source roots for {relative_text}")
        roots = sorted(set(roots_entry))
        if len(roots) != len(roots_entry):
            raise SystemExit(f"duplicate source root for {relative_text}")
        if roots:
            unit["roots"] = roots
        build_path = path
        adaptation_entry = source.get("host_adaptation")
        if adaptation_entry is not None:
            if not isinstance(adaptation_entry, dict):
                raise SystemExit(
                    f"host adaptation for {relative_text} is not an object"
                )
            adaptation_relative = safe_relative_path(
                adaptation_entry.get("path"), "host adaptation"
            )
            adaptation_path = args.spec.resolve().parent.joinpath(
                *adaptation_relative.parts
            )
            if not adaptation_path.is_file():
                raise SystemExit(
                    f"missing host adaptation for {relative_text}: "
                    f"{adaptation_relative.as_posix()}"
                )
            expected_adaptation_hash = str(
                adaptation_entry.get("sha256", "")
            ).lower()
            actual_adaptation_hash = sha256(adaptation_path)
            if actual_adaptation_hash != expected_adaptation_hash:
                raise SystemExit(
                    f"host adaptation hash mismatch for {relative_text}: "
                    f"expected {expected_adaptation_hash}, "
                    f"got {actual_adaptation_hash}"
                )
            adaptation = load_adaptation(adaptation_path)
            if adaptation.get("claim_boundary") != ADAPTATION_CLAIM_BOUNDARY:
                raise SystemExit(
                    f"invalid host adaptation claim boundary for {relative_text}"
                )
            if adaptation.get("source_path") != relative_text:
                raise SystemExit(
                    f"host adaptation source path mismatch for {relative_text}"
                )
            try:
                native_dependencies = verify_native_dependencies(
                    adaptation, args.spec.resolve().parent.parent
                )
                adapted_source = apply_adaptation(path.read_bytes(), adaptation)
            except ValueError as error:
                raise SystemExit(
                    f"host adaptation failed for {relative_text}: {error}"
                ) from error
            build_path = adapted_root.joinpath(*relative.parts)
            build_path.parent.mkdir(parents=True, exist_ok=True)
            if (
                not build_path.is_file()
                or build_path.read_bytes() != adapted_source
            ):
                build_path.write_bytes(adapted_source)
            if original_include_dir:
                adapted_include_dirs[relative_text] = path.parent
            unit["host_adaptation"] = {
                "path": adaptation_relative.as_posix(),
                "sha256": actual_adaptation_hash,
                "adapted_sha256": sha256(build_path),
                "replacement_count": len(adaptation["replacements"]),
                "claim_boundary": adaptation["claim_boundary"],
            }
            if native_dependencies:
                unit["host_adaptation"]["native_dependencies"] = (
                    native_dependencies
                )
        if provider_only and "host_adaptation" not in unit:
            raise SystemExit(
                f"provider-only source requires a host adaptation: {relative_text}"
            )
        if replaces_ready_provider and "host_adaptation" not in unit:
            raise SystemExit(
                "replaces_ready_provider requires a host adaptation for "
                f"{relative_text}"
            )
        if not original_include_dir and "host_adaptation" not in unit:
            raise SystemExit(
                "original_include_dir can be disabled only for an adapted "
                f"source: {relative_text}"
            )
        if provider_only and "roots" in unit:
            raise SystemExit(
                f"provider-only source cannot also declare roots: {relative_text}"
            )
        units.append(unit)
        build_paths[relative_text] = build_path

    readiness_units: list[dict[str, object]] = []
    readiness_seen: set[str] = set()
    for source in readiness["translation_units"]:
        relative = pathlib.PurePosixPath(str(source["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit(f"unsafe readiness source path: {relative}")
        relative_text = relative.as_posix()
        if relative_text in readiness_seen:
            raise SystemExit(f"duplicate readiness source: {relative_text}")
        readiness_seen.add(relative_text)
        path = root.joinpath(*relative.parts)
        if not path.is_file():
            raise SystemExit(f"missing readiness source: {relative_text}")
        actual_hash = sha256(path)
        if actual_hash != str(source["sha256"]).lower():
            raise SystemExit(f"readiness source hash mismatch: {relative_text}")
        status = str(source["compile_status"])
        if status not in {"ready", "blocked"}:
            raise SystemExit(
                f"invalid readiness compile status for {relative_text}: {status}"
            )
        if status == "ready":
            readiness_units.append(
                {
                    "path": relative_text,
                    "sha256": actual_hash,
                }
            )

    if len(readiness_seen) != int(readiness["translation_unit_count"]):
        raise SystemExit("native readiness translation-unit count mismatch")
    if len(readiness_units) != int(readiness["ready_count"]):
        raise SystemExit("native readiness ready-unit count mismatch")
    selected_paths = {str(unit["path"]) for unit in units}
    ready_paths = {str(unit["path"]) for unit in readiness_units}
    adapted_paths = {
        str(unit["path"]) for unit in units if "host_adaptation" in unit
    }
    ready_provider_paths = sorted(
        str(unit["path"])
        for unit in units
        if unit.get("provider_only")
        and not unit.get("replaces_ready_provider")
        and str(unit["path"]) in ready_paths
    )
    if ready_provider_paths:
        raise SystemExit(
            "provider-only sources must be blocked in the original readiness "
            "inventory: " + ", ".join(ready_provider_paths)
        )
    missing = sorted(selected_paths - ready_paths - adapted_paths)
    if missing:
        raise SystemExit(
            "selected import is not compile-ready: " + ", ".join(missing)
        )

    provider_exclusions_entry = spec.get("provider_exclusions", [])
    if not isinstance(provider_exclusions_entry, list):
        raise SystemExit("provider_exclusions must be a list")
    provider_exclusions: list[dict[str, str]] = []
    excluded_paths: set[str] = set()
    for entry in provider_exclusions_entry:
        expected_keys = {"path", "sha256", "scope", "reason"}
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise SystemExit("invalid provider_exclusions entry")
        path_text = safe_relative_path(
            entry["path"], "provider exclusion"
        ).as_posix()
        if path_text in excluded_paths:
            raise SystemExit(f"duplicate provider exclusion: {path_text}")
        if path_text not in readiness_seen:
            raise SystemExit(
                f"provider exclusion is absent from readiness inventory: {path_text}"
            )
        if path_text in selected_paths:
            raise SystemExit(
                f"selected native import cannot be excluded: {path_text}"
            )
        path = root.joinpath(*pathlib.PurePosixPath(path_text).parts)
        expected_hash = str(entry["sha256"]).lower()
        if sha256(path) != expected_hash:
            raise SystemExit(f"provider exclusion source hash mismatch: {path_text}")
        scope = entry["scope"]
        reason = entry["reason"]
        if (
            scope != "noncompetitive-presentation"
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise SystemExit(f"invalid provider exclusion boundary: {path_text}")
        excluded_paths.add(path_text)
        provider_exclusions.append(
            {
                "path": path_text,
                "sha256": expected_hash,
                "scope": scope,
                "reason": reason,
            }
        )

    rooted_units = [unit for unit in units if "roots" in unit]
    provider_units = [unit for unit in units if unit.get("provider_only")]
    provider_paths = {
        str(unit["path"]) for unit in units if "roots" not in unit
    }
    provider_roots_entry = spec.get("provider_roots", [])
    if not isinstance(provider_roots_entry, list):
        raise SystemExit("provider_roots must be a list")
    provider_roots: list[tuple[str, str]] = []
    for entry in provider_roots_entry:
        if not isinstance(entry, dict) or set(entry) != {"path", "symbols"}:
            raise SystemExit("invalid provider_roots entry")
        path_text = safe_relative_path(entry["path"], "provider root").as_posix()
        symbols = entry["symbols"]
        if path_text not in provider_paths:
            raise SystemExit(
                f"provider root is not a selected non-root source: {path_text}"
            )
        if not isinstance(symbols, list) or not symbols or any(
            not isinstance(symbol, str) or not symbol for symbol in symbols
        ):
            raise SystemExit(f"invalid provider root symbols for {path_text}")
        if len(set(symbols)) != len(symbols):
            raise SystemExit(f"duplicate provider root symbol for {path_text}")
        provider_roots.extend((path_text, symbol) for symbol in sorted(symbols))
    if len(set(provider_roots)) != len(provider_roots):
        raise SystemExit("duplicate provider root")
    ordinary_units = [
        unit
        for unit in units
        if "roots" not in unit and not unit.get("provider_only")
    ]
    rooted_ids = {
        str(unit["path"]): source_unit_id(str(unit["path"]))
        for unit in rooted_units
    }
    if len(set(rooted_ids.values())) != len(rooted_ids):
        raise SystemExit("rooted source unit IDs collide")
    rooted_paths = set(rooted_ids)
    replaced_ready_provider_paths = {
        str(unit["path"])
        for unit in provider_units
        if unit.get("replaces_ready_provider")
    }
    compile_ready_units = [
        unit
        for unit in readiness_units
        if str(unit["path"])
        not in rooted_paths | replaced_ready_provider_paths | excluded_paths
    ]

    lines = [
        "# Generated by prepare_ssbm_native_import.py; do not edit.",
        f'set(PF_SSBM_DECOMP_REVISION "{actual_revision}")',
        f'set(PF_SSBM_NATIVE_ADAPTED_HEADER_INCLUDE_DIR "{cmake_path(adapted_header_root)}")',
        "set(PF_SSBM_NATIVE_FORCED_HEADERS",
    ]
    lines.extend(
        f'    "{cmake_path(adapted_header_root / str(entry["include_path"]))}"'
        for entry in header_adaptations
        if "force_include_sources" not in entry
    )
    lines.append(")")
    scoped_headers_by_source: dict[str, list[pathlib.Path]] = {}
    for entry in header_adaptations:
        header = adapted_header_root / str(entry["include_path"])
        for source_path in entry.get("force_include_sources", []):
            scoped_headers_by_source.setdefault(str(source_path), []).append(header)
    scoped_header_ids = {
        path: source_unit_id(path) for path in scoped_headers_by_source
    }
    if len(set(scoped_header_ids.values())) != len(scoped_header_ids):
        raise SystemExit("scoped header source IDs collide")
    lines.append("set(PF_SSBM_NATIVE_SCOPED_HEADER_SOURCE_IDS")
    lines.extend(f"    {unit_id}" for unit_id in scoped_header_ids.values())
    lines.append(")")
    for path_text, headers in scoped_headers_by_source.items():
        unit_id = scoped_header_ids[path_text]
        lines.append(
            f'set(PF_SSBM_NATIVE_SCOPED_HEADER_SOURCE_{unit_id} '
            f'"{cmake_path(root / path_text)}")'
        )
        lines.append(f"set(PF_SSBM_NATIVE_SCOPED_HEADERS_{unit_id}")
        lines.extend(f'    "{cmake_path(header)}"' for header in headers)
        lines.append(")")
    lines.append("set(PF_SSBM_NATIVE_SOURCE_COMPILE_OPTION_IDS")
    policy_ids = {
        str(entry["path"]): source_unit_id(str(entry["path"]))
        for entry in compile_policy
    }
    if len(set(policy_ids.values())) != len(policy_ids):
        raise SystemExit("source compile policy IDs collide")
    lines.extend(f"    {unit_id}" for unit_id in policy_ids.values())
    lines.append(")")
    for entry in compile_policy:
        path_text = str(entry["path"])
        unit_id = policy_ids[path_text]
        compile_source = build_paths.get(path_text, root / path_text)
        lines.append(
            f'set(PF_SSBM_NATIVE_SOURCE_COMPILE_SOURCE_{unit_id} '
            f'"{cmake_path(compile_source)}")'
        )
        lines.append(f"set(PF_SSBM_NATIVE_SOURCE_COMPILE_OPTIONS_{unit_id}")
        lines.extend(f'    "{option}"' for option in entry["options"])
        lines.append(")")
    lines.extend([
        "set(PF_SSBM_NATIVE_DECOMP_SOURCES",
    ])
    lines.extend(
        f'    "{cmake_path(build_paths[str(unit["path"])])}"'
        for unit in ordinary_units
    )
    lines.append(")")
    lines.append("set(PF_SSBM_NATIVE_ADAPTED_PROVIDER_SOURCES")
    lines.extend(
        f'    "{cmake_path(build_paths[str(unit["path"])])}"'
        for unit in provider_units
    )
    lines.append(")")
    lines.append("set(PF_SSBM_NATIVE_PROVIDER_ROOT_ARGUMENTS")
    for path_text, symbol in provider_roots:
        lines.extend((
            '    "--provider-root"',
            f'    "{path_text}={symbol}"',
        ))
    lines.append(")")
    adapted_source_ids = {
        path: source_unit_id(path) for path in sorted(adapted_include_dirs)
    }
    if len(set(adapted_source_ids.values())) != len(adapted_source_ids):
        raise SystemExit("adapted source unit IDs collide")
    lines.append("set(PF_SSBM_NATIVE_ADAPTED_SOURCE_IDS")
    lines.extend(f"    {unit_id}" for unit_id in adapted_source_ids.values())
    lines.append(")")
    for path_text, unit_id in adapted_source_ids.items():
        lines.append(
            f'set(PF_SSBM_NATIVE_ADAPTED_SOURCE_{unit_id} '
            f'"{cmake_path(build_paths[path_text])}")'
        )
        lines.append(
            f'set(PF_SSBM_NATIVE_ADAPTED_INCLUDE_DIR_{unit_id} '
            f'"{cmake_path(adapted_include_dirs[path_text])}")'
        )
    lines.append("set(PF_SSBM_NATIVE_ROOTED_UNIT_IDS")
    lines.extend(f"    {unit_id}" for unit_id in rooted_ids.values())
    lines.append(")")
    for unit in rooted_units:
        unit_id = rooted_ids[str(unit["path"])]
        lines.append(
            f'set(PF_SSBM_NATIVE_ROOTED_SOURCE_{unit_id} '
            f'"{cmake_path(build_paths[str(unit["path"])])}")'
        )
        lines.append(
            f'set(PF_SSBM_NATIVE_ROOTED_PATH_{unit_id} '
            f'"{unit["path"]}")'
        )
        lines.append(f"set(PF_SSBM_NATIVE_ROOTED_ROOTS_{unit_id}")
        lines.extend(f'    "{root_symbol}"' for root_symbol in unit["roots"])
        lines.append(")")
    lines.append("set(PF_SSBM_NATIVE_COMPILE_READY_SOURCES")
    lines.extend(
        f'    "{cmake_path(root / unit["path"])}"'
        for unit in compile_ready_units
    )
    lines.append(")")
    encoded_cmake = "\n".join(lines) + "\n"
    manifest = {
        "schema": 1,
        "target": spec["target"],
        "decomp_revision": actual_revision,
        "dependencies": {
            "aurora": {
                "repository": spec["dependencies"]["aurora"]["repository"],
                "branch": spec["dependencies"]["aurora"]["branch"],
                "revision": actual_aurora_revision,
                "gx_compat_header_sha256": actual_gx_compat_hash,
                "gx_enum_header_sha256": actual_gx_enum_hash,
                "gx_pixel_header_sha256": actual_gx_pixel_hash,
                "gx_tev_header_sha256": actual_gx_tev_hash,
                "pad_header_sha256": actual_pad_hash,
                "types_header_sha256": actual_types_hash,
            },
        },
        "native_header_adaptations": header_adaptations,
        "provider_exclusions": provider_exclusions,
        "provider_roots": [
            {"path": path_text, "symbol": symbol}
            for path_text, symbol in provider_roots
        ],
        "native_source_compile_options": compile_policy,
        "translation_unit_count": len(units),
        "translation_units": units,
        "compile_readiness": {
            "claim_boundary": readiness["claim_boundary"],
            "report_sha256": sha256(args.readiness),
            "translation_unit_count": len(readiness_seen),
            "ready_count": len(readiness_units),
            "blocked_count": len(readiness_seen) - len(readiness_units),
            "host_adapted_selected_count": len(adapted_paths),
            "adapted_provider_count": len(provider_units),
            "rooted_selected_count": len(rooted_units),
        },
    }
    encoded_manifest = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    args.output_cmake.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (args.output_cmake, encoded_cmake),
        (args.output_manifest, encoded_manifest),
    ):
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
    print(
        "ssbm-native-import=pass "
        f"revision={actual_revision} units={len(units)} "
        f"manifest_sha256={hashlib.sha256(encoded_manifest.encode()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
