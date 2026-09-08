#!/usr/bin/env python3
"""Classify direct host-compile readiness for pinned Melee source units.

This is a mechanical compiler probe, not a behavior or runtime-coverage claim.
The checked-in report distinguishes source availability, strict host codegen,
selection into the native import, and later qualification work.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Iterable

from apply_source_adaptation import prepare_header_adaptations
from native_source_policy import options_by_path, source_compile_options


GAMEPLAY_PREFIXES = (
    "extern/dolphin/src/dolphin/mtx/",
    "src/MSL/",
    "src/Runtime/",
    "src/melee/",
    "src/sysdolphin/baselib/",
)

GAMEPLAY_EXACT_SOURCES = (
    "extern/dolphin/src/dolphin/gx/GXTransform.c",
)

FORBIDDEN_RUNTIME_TOKENS = (
    "CPUState",
    "DOLRECOMP",
    "guest_pc",
    "guest_memory",
    "mmio_read",
    "mmio_write",
)

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text_if_different(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


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


def git_revision(root: Path) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.strip().lower()


def verify_revision(root: Path, expected: str, label: str) -> str:
    actual = git_revision(root)
    if actual != expected.lower():
        raise SystemExit(
            f"{label} revision mismatch: expected {expected.lower()}, got {actual}"
        )
    return actual


def source_module(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    if parts[:4] == ("extern", "dolphin", "src", "dolphin") and len(parts) >= 6:
        return f"dolphin/{parts[4]}"
    if parts[:2] == ("src", "MSL") and len(parts) >= 3:
        return "MSL"
    if parts[:2] == ("src", "Runtime") and len(parts) >= 3:
        return "Runtime"
    if parts[:2] == ("src", "melee") and len(parts) >= 3:
        return parts[2]
    if parts[:2] == ("src", "sysdolphin") and len(parts) >= 3:
        return f"sysdolphin/{parts[2]}"
    return "unknown"


def discover_sources(decomp: Path, declared_sources: Iterable[str] = ()) -> list[Path]:
    sources: list[Path] = []
    source_roots = (
        decomp / "src",
        decomp / "extern" / "dolphin" / "src" / "dolphin" / "mtx",
    )
    for source_root in source_roots:
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.c"):
            relative = path.relative_to(decomp).as_posix()
            if relative.startswith(GAMEPLAY_PREFIXES):
                sources.append(path)
    for relative in GAMEPLAY_EXACT_SOURCES:
        path = decomp.joinpath(*PurePosixPath(relative).parts)
        if path.is_file():
            sources.append(path)
    for relative in declared_sources:
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".c":
            raise ValueError(f"invalid declared C source path: {relative}")
        path = decomp.joinpath(*rel.parts)
        if not path.is_file():
            raise ValueError(f"missing declared C source: {relative}")
        sources.append(path)
    return sorted(set(sources), key=lambda path: path.relative_to(decomp).as_posix())


def normalized_diagnostic(
    diagnostic: str,
    *,
    replacements: Iterable[tuple[Path, str]],
    line_limit: int = 12,
    character_limit: int = 4096,
) -> str:
    result = ANSI_ESCAPE.sub("", diagnostic).replace("\\", "/")
    candidates = {
        (candidate, label)
        for path, label in replacements
        for candidate in (
            str(path).replace("\\", "/"),
            str(path.resolve()).replace("\\", "/"),
        )
        if candidate
    }
    ordered = sorted(candidates, key=lambda item: len(item[0]), reverse=True)
    for path, label in ordered:
        result = result.replace(path, label)
    lines = [line.rstrip() for line in result.splitlines() if line.strip()]
    error_indices = [
        index
        for index, line in enumerate(lines)
        if " error:" in line or "fatal error:" in line
    ]
    if error_indices:
        first = error_indices[0]
        start = max(0, first - 2)
        lines = lines[start : start + line_limit]
    else:
        lines = lines[:line_limit]
    return "\n".join(lines)[:character_limit]


def classify_blocker(diagnostic: str, *, timed_out: bool = False) -> str:
    if timed_out:
        return "compiler-timeout"
    lowered = diagnostic.lower()
    if re.search(r"fatal error: .*\.inc: no such file", lowered):
        return "missing-generated-include"
    if "fatal error:" in lowered and "no such file or directory" in lowered:
        return "missing-header"
    if any(
        token in lowered
        for token in (
            "unknown register name",
            "impossible constraint in 'asm'",
            "unsupported inline asm",
            "powerpc",
        )
    ):
        return "powerpc-assembly"
    if any(
        token in lowered
        for token in (
            "static assertion failed",
            "size of array",
            "negative width in bit-field",
        )
    ):
        return "host-layout-assertion"
    if "conflicting types for" in lowered or "previous declaration" in lowered:
        return "sdk-or-source-type-conflict"
    if any(
        token in lowered
        for token in (
            "implicit declaration of function",
            "undeclared (first use",
            "has no member named",
            "unknown type name",
        )
    ):
        return "missing-host-declaration"
    if any(
        token in lowered
        for token in (
            "incompatible pointer type",
            "incompatible type for argument",
            "makes pointer from integer",
            "makes integer from pointer",
        )
    ):
        return "host-type-incompatibility"
    if "[-werror" in lowered or "all warnings being treated as errors" in lowered:
        return "strict-warning"
    if any(
        token in lowered
        for token in (
            "expected declaration specifiers",
            "expected identifier or '('",
            "expected expression before",
            "stray '",
        )
    ):
        return "unsupported-source-syntax"
    return "other-compile-error"


def compiler_arguments(
    compiler: Path,
    *,
    source: Path,
    decomp: Path,
    aurora: Path,
    compat: Path,
    adapted_header_root: Path | None = None,
    forced_headers: tuple[Path, ...] = (),
    target_arguments: tuple[str, ...] = (),
    system_headers: tuple[str, ...] = (),
    source_options: tuple[str, ...] = (),
) -> list[str]:
    arguments = [
        str(compiler),
        *target_arguments,
        "-std=c2x",
        "-c",
        "-o",
        os.devnull,
        "-DDEBUG=0",
        "-DTARGET_PC=1",
        "-include",
        str(compat / "platform.h"),
    ]
    for header in system_headers:
        arguments.extend(("-include", header))
    for header in forced_headers:
        arguments.extend(("-include", str(header)))
    if adapted_header_root is not None:
        arguments.append(f"-I{adapted_header_root}")
    arguments.extend(
        [
            f"-I{compat}",
            f"-I{aurora / 'include'}",
            f"-I{decomp / 'src'}",
            f"-I{decomp / 'src' / 'melee'}",
            f"-I{decomp / 'src' / 'melee' / 'ft' / 'kinds'}",
            f"-I{decomp / 'src' / 'Runtime'}",
            f"-I{decomp / 'src' / 'sysdolphin'}",
            f"-I{decomp / 'extern' / 'dolphin' / 'include'}",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-Wconversion",
            "-Wformat=2",
            "-Wmissing-prototypes",
            "-Wshadow",
            "-Wstrict-prototypes",
            "-Wundef",
            "-Wwrite-strings",
            "-fno-strict-aliasing",
            "-Wno-absolute-value",
            "-Wno-address",
            "-Wno-array-bounds",
            "-Wno-bool-compare",
            "-Wno-bool-operation",
            "-Wno-conversion",
            "-Wno-discarded-qualifiers",
            "-Wno-enum-conversion",
            "-Wno-implicit-fallthrough",
            "-Wno-int-in-bool-context",
            "-Wno-maybe-uninitialized",
            "-Wno-missing-braces",
            "-Wno-missing-field-initializers",
            "-Wno-missing-prototypes",
            "-Wno-old-style-declaration",
            "-Wno-pedantic",
            "-Wno-pointer-compare",
            "-Wno-shadow",
            "-Wno-sign-compare",
            "-Wno-sign-conversion",
            "-Wno-strict-prototypes",
            "-Wno-unused-but-set-variable",
            "-Wno-unused-function",
            "-Wno-unused-parameter",
            "-Wno-unused-value",
            "-Wno-unused-variable",
            "-Wno-unknown-pragmas",
            "-Wno-cast-function-type",
            "-Wno-format-overflow",
            "-fno-fast-math",
            "-ffp-contract=off",
            "-fexcess-precision=standard",
            *source_options,
            str(source),
        ]
    )
    return arguments


def recorded_target_arguments(
    actual: tuple[str, ...], recorded: tuple[str, ...]
) -> list[str]:
    if not recorded:
        return list(actual)
    if len(actual) != len(recorded):
        raise ValueError(
            "recorded target arguments must match the actual argument count"
        )
    return list(recorded)


def probe_source(
    source: Path,
    *,
    compiler: Path,
    decomp: Path,
    aurora: Path,
    compat: Path,
    adapted_header_root: Path | None,
    forced_headers: tuple[Path, ...],
    target_arguments: tuple[str, ...],
    system_headers: tuple[str, ...],
    source_options: tuple[str, ...],
    timeout_seconds: float,
) -> dict[str, object]:
    relative = source.relative_to(decomp).as_posix()
    text = source.read_text(encoding="utf-8")
    forbidden = [token for token in FORBIDDEN_RUNTIME_TOKENS if token in text]
    arguments = compiler_arguments(
        compiler,
        source=source,
        decomp=decomp,
        aurora=aurora,
        compat=compat,
        adapted_header_root=adapted_header_root,
        forced_headers=forced_headers,
        target_arguments=target_arguments,
        system_headers=system_headers,
        source_options=source_options,
    )
    timed_out = False
    try:
        process = subprocess.run(
            arguments,
            cwd=decomp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        diagnostic = process.stderr or process.stdout
        return_code = process.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        return_code = 124
        diagnostic = "\n".join(
            part
            for part in (
                error.stdout if isinstance(error.stdout, str) else "",
                error.stderr if isinstance(error.stderr, str) else "",
                f"compiler timeout after {timeout_seconds:g} seconds",
            )
            if part
        )
    normalized = normalized_diagnostic(
        diagnostic,
        replacements=(
            (decomp, "<decomp>"),
            (aurora, "<aurora>"),
            (compat.parent.parent.parent, "<repo>"),
            *(
                ((adapted_header_root, "<adapted-headers>"),)
                if adapted_header_root is not None
                else ()
            ),
        ),
    )
    ready = return_code == 0 and not forbidden
    blocker = None if ready else classify_blocker(normalized, timed_out=timed_out)
    if forbidden:
        blocker = "emulator-runtime-token"
        normalized = "forbidden runtime tokens: " + ", ".join(forbidden)
    return {
        "path": relative,
        "module": source_module(relative),
        "sha256": sha256(source),
        "bytes": source.stat().st_size,
        "compile_status": "ready" if ready else "blocked",
        "blocker": blocker,
        "diagnostic": normalized or None,
    }


def resolve_compiler(value: str) -> Path:
    candidate = shutil.which(value)
    if candidate is None:
        raise SystemExit(f"C compiler not found: {value}")
    return Path(candidate).resolve()


def compiler_version(compiler: Path) -> str:
    process = subprocess.run(
        [str(compiler), "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.splitlines()[0].strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decomp", required=True, type=Path)
    parser.add_argument("--aurora", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--compat", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument(
        "--target-argument",
        action="append",
        default=[],
        help="repeatable compiler argument that selects the native target ABI",
    )
    parser.add_argument(
        "--recorded-target-argument",
        action="append",
        default=[],
        help="portable report spelling for the corresponding target argument",
    )
    parser.add_argument(
        "--target-identity",
        help="content identity of the target toolchain or sysroot",
    )
    parser.add_argument(
        "--workers", type=int, default=min(16, max(1, os.cpu_count() or 1))
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--require-all-ready", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.workers <= 64:
        raise SystemExit("--workers must be in [1, 64]")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    decomp = args.decomp.resolve()
    aurora = args.aurora.resolve()
    compat = args.compat.resolve()
    spec_path = args.spec.resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("schema") != 1:
        raise SystemExit("unsupported native import spec schema")
    decomp_revision = verify_revision(
        decomp, str(spec["decomp_revision"]), "decomp"
    )
    aurora_spec = spec["dependencies"]["aurora"]
    aurora_revision = verify_revision(
        aurora, str(aurora_spec["revision"]), "Aurora"
    )
    types_header = aurora / "include" / "dolphin" / "types.h"
    actual_header_hash = sha256(types_header)
    if actual_header_hash != str(aurora_spec["types_header_sha256"]).lower():
        raise SystemExit("Aurora types header hash mismatch")
    pad_header = aurora / "include" / "dolphin" / "pad.h"
    actual_pad_hash = sha256(pad_header)
    if actual_pad_hash != str(aurora_spec["pad_header_sha256"]).lower():
        raise SystemExit("Aurora PAD header hash mismatch")
    gx_compat_header = aurora / "include" / "dolphin" / "gx" / "GXAurora.h"
    actual_gx_compat_hash = sha256(gx_compat_header)
    if actual_gx_compat_hash != str(
        aurora_spec["gx_compat_header_sha256"]
    ).lower():
        raise SystemExit("Aurora GX compatibility header hash mismatch")
    gx_enum_header = aurora / "include" / "dolphin" / "gx" / "GXEnum.h"
    actual_gx_enum_hash = sha256(gx_enum_header)
    if actual_gx_enum_hash != str(
        aurora_spec["gx_enum_header_sha256"]
    ).lower():
        raise SystemExit("Aurora GX enum header hash mismatch")
    gx_tev_header = aurora / "include" / "dolphin" / "gx" / "GXTev.h"
    actual_gx_tev_hash = sha256(gx_tev_header)
    if actual_gx_tev_hash != str(
        aurora_spec["gx_tev_header_sha256"]
    ).lower():
        raise SystemExit("Aurora GX TEV header hash mismatch")
    gx_pixel_header = aurora / "include" / "dolphin" / "gx" / "GXPixel.h"
    actual_gx_pixel_hash = sha256(gx_pixel_header)
    if actual_gx_pixel_hash != str(
        aurora_spec["gx_pixel_header_sha256"]
    ).lower():
        raise SystemExit("Aurora GX pixel header hash mismatch")
    if not (compat / "platform.h").is_file():
        raise SystemExit(f"missing native compatibility platform: {compat}")

    compiler = resolve_compiler(args.compiler)
    target_arguments = tuple(args.target_argument)
    try:
        report_target_arguments = recorded_target_arguments(
            target_arguments, tuple(args.recorded_target_argument)
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    system_headers = (
        ("math.h", "stdarg.h", "sys/types.h") if os.name == "posix" else ()
    )
    sources = discover_sources(decomp, (entry["path"] for entry in spec["translation_units"]))
    try:
        compile_policy = source_compile_options(spec, decomp=decomp)
    except ValueError as error:
        raise SystemExit(f"native source compile policy failed: {error}") from error
    compile_options = options_by_path(compile_policy)
    with TemporaryDirectory(prefix="ssbm-native-headers-") as directory:
        adapted_header_root = Path(directory).resolve()
        try:
            header_adaptations = prepare_header_adaptations(
                spec,
                decomp=decomp,
                spec_dir=spec_path.parent,
                output_root=adapted_header_root,
            )
        except ValueError as error:
            raise SystemExit(f"native header adaptation failed: {error}") from error
        global_forced_headers = tuple(
            adapted_header_root / str(entry["include_path"])
            for entry in header_adaptations
            if "force_include_sources" not in entry
        )
        scoped_forced_headers: dict[str, tuple[Path, ...]] = {}
        for entry in header_adaptations:
            header = adapted_header_root / str(entry["include_path"])
            for source_path in entry.get("force_include_sources", []):
                scoped_forced_headers.setdefault(str(source_path), ())
                scoped_forced_headers[str(source_path)] += (header,)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            units = list(
                executor.map(
                    lambda source: probe_source(
                        source,
                        compiler=compiler,
                        decomp=decomp,
                        aurora=aurora,
                        compat=compat,
                        adapted_header_root=adapted_header_root,
                        forced_headers=global_forced_headers
                        + scoped_forced_headers.get(
                            source.relative_to(decomp).as_posix(), ()
                        ),
                        target_arguments=target_arguments,
                        system_headers=system_headers,
                        source_options=compile_options.get(
                            source.relative_to(decomp).as_posix(), ()
                        ),
                        timeout_seconds=args.timeout_seconds,
                    ),
                    sources,
                )
            )

    units.sort(key=lambda unit: str(unit["path"]))
    ready_count = sum(unit["compile_status"] == "ready" for unit in units)
    blocker_counts: dict[str, int] = {}
    module_counts: dict[str, dict[str, int]] = {}
    for unit in units:
        blocker = unit["blocker"]
        if blocker is not None:
            blocker_counts[str(blocker)] = blocker_counts.get(str(blocker), 0) + 1
        module = str(unit["module"])
        counts = module_counts.setdefault(module, {"total": 0, "ready": 0})
        counts["total"] += 1
        if unit["compile_status"] == "ready":
            counts["ready"] += 1

    manifest = {
        "schema": 1,
        "target": spec["target"],
        "claim_boundary": "strict-host-compile-readiness-only",
        "decomp_revision": decomp_revision,
        "aurora": {
            "repository": aurora_spec["repository"],
            "branch": aurora_spec["branch"],
            "revision": aurora_revision,
            "gx_compat_header_sha256": actual_gx_compat_hash,
            "gx_enum_header_sha256": actual_gx_enum_hash,
            "gx_pixel_header_sha256": actual_gx_pixel_hash,
            "gx_tev_header_sha256": actual_gx_tev_hash,
            "pad_header_sha256": actual_pad_hash,
            "types_header_sha256": actual_header_hash,
        },
        "source_authority_sha256": source_authority_sha256(spec),
        "native_platform_sha256": sha256(compat / "platform.h"),
        "native_header_adaptations": header_adaptations,
        "native_source_compile_options": compile_policy,
        "compiler": {
            "name": compiler.name,
            "version": compiler_version(compiler),
            "sha256": sha256(compiler),
            "target_arguments": report_target_arguments,
            "target_identity": args.target_identity,
            "system_headers": list(system_headers),
        },
        "translation_unit_count": len(units),
        "ready_count": ready_count,
        "blocked_count": len(units) - ready_count,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "module_counts": dict(sorted(module_counts.items())),
        "translation_units": units,
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    write_text_if_different(args.output, encoded)
    print(
        "ssbm-native-source-probe=pass "
        f"units={len(units)} ready={ready_count} "
        f"blocked={len(units) - ready_count} "
        f"sha256={hashlib.sha256(encoded.encode()).hexdigest()}"
    )
    return 1 if args.require_all_ready and ready_count != len(units) else 0


if __name__ == "__main__":
    raise SystemExit(main())
