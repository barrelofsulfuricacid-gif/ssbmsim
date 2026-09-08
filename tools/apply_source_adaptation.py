#!/usr/bin/env python3
"""Apply a hash-pinned, exact-count native host adaptation to one source file.

Adaptations are reviewed source-level compatibility changes.  They do not
change the pinned upstream checkout, and successful application is not a
runtime or behavioral-equivalence claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


CLAIM_BOUNDARY = "source-host-adaptation-not-behavioral-coverage"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_adaptation(source: bytes, adaptation: dict[str, object]) -> bytes:
    if adaptation.get("schema") != 1:
        raise ValueError("unsupported source-adaptation schema")
    if adaptation.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("source-adaptation claim boundary is missing or invalid")
    expected_source_hash = str(adaptation.get("source_sha256", "")).lower()
    actual_source_hash = sha256_bytes(source)
    if actual_source_hash != expected_source_hash:
        raise ValueError(
            "source-adaptation input hash mismatch: "
            f"expected {expected_source_hash}, got {actual_source_hash}"
        )

    text = source.decode("utf-8")
    if "\r" in text.replace("\r\n", ""):
        raise ValueError("source adaptation input contains unsupported lone CR")
    # Generated host sources use one byte-stable newline convention even when
    # the pinned checkout is materialized with Windows working-tree endings.
    text = text.replace("\r\n", "\n")
    replacements = adaptation.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("source adaptation must contain replacements")
    seen_old: set[str] = set()
    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, dict):
            raise ValueError(f"replacement {index} is not an object")
        old = replacement.get("old")
        new = replacement.get("new")
        expected_count = replacement.get("count")
        reason = replacement.get("reason")
        if not isinstance(old, str) or not old:
            raise ValueError(f"replacement {index} has no old text")
        if not isinstance(new, str) or old == new:
            raise ValueError(f"replacement {index} has invalid new text")
        if not isinstance(expected_count, int) or expected_count < 1:
            raise ValueError(f"replacement {index} has invalid count")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"replacement {index} has no reason")
        if old in seen_old:
            raise ValueError(f"replacement {index} duplicates old text")
        seen_old.add(old)
        actual_count = text.count(old)
        if actual_count != expected_count:
            raise ValueError(
                f"replacement {index} count mismatch: "
                f"expected {expected_count}, got {actual_count}"
            )
        text = text.replace(old, new)

    result = text.encode("utf-8")
    expected_adapted_hash = str(adaptation.get("adapted_sha256", "")).lower()
    actual_adapted_hash = sha256_bytes(result)
    if actual_adapted_hash != expected_adapted_hash:
        raise ValueError(
            "source-adaptation output hash mismatch: "
            f"expected {expected_adapted_hash}, got {actual_adapted_hash}"
        )
    return result


def load_adaptation(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("source adaptation root must be an object")
    return value


def verify_native_dependencies(
    adaptation: dict[str, object], repo_root: Path
) -> list[dict[str, str]]:
    entries = adaptation.get("native_dependencies", [])
    if not isinstance(entries, list):
        raise ValueError("source adaptation native_dependencies must be a list")

    verified: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"native dependency {index} is not an object")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError(f"native dependency {index} has no path")
        relative = PurePosixPath(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe native dependency path: {relative}")
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise ValueError(f"duplicate native dependency path: {relative_text}")
        seen.add(relative_text)

        expected_hash = str(entry.get("sha256", "")).lower()
        if len(expected_hash) != 64 or any(
            digit not in "0123456789abcdef" for digit in expected_hash
        ):
            raise ValueError(
                f"native dependency {relative_text} has an invalid sha256"
            )
        dependency_path = repo_root.joinpath(*relative.parts)
        if not dependency_path.is_file():
            raise ValueError(f"missing native dependency: {relative_text}")
        actual_hash = sha256_bytes(dependency_path.read_bytes())
        if actual_hash != expected_hash:
            raise ValueError(
                f"native dependency hash mismatch for {relative_text}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        verified.append({"path": relative_text, "sha256": actual_hash})
    return verified


def prepare_header_adaptations(
    spec: dict[str, object],
    *,
    decomp: Path,
    spec_dir: Path,
    output_root: Path,
) -> list[dict[str, object]]:
    """Materialize pinned source-header adaptations under one include root."""

    entries = spec.get("header_adaptations", [])
    if not isinstance(entries, list):
        raise ValueError("header_adaptations must be a list")

    manifest: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"header adaptation {index} is not an object")
        source_value = entry.get("path")
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f"header adaptation {index} has no source path")
        source_relative = PurePosixPath(source_value)
        if (
            source_relative.is_absolute()
            or ".." in source_relative.parts
            or len(source_relative.parts) < 2
            or source_relative.parts[0] != "src"
        ):
            raise ValueError(f"unsafe adapted header path: {source_relative}")
        source_text = source_relative.as_posix()
        if source_text in seen:
            raise ValueError(f"duplicate adapted header: {source_text}")
        seen.add(source_text)

        force_include_value = entry.get("force_include_sources")
        force_include_sources: list[str] | None = None
        if force_include_value is not None:
            if not isinstance(force_include_value, list) or not force_include_value:
                raise ValueError(
                    f"header adaptation for {source_text} has invalid "
                    "force_include_sources"
                )
            force_include_sources = []
            force_seen: set[str] = set()
            for value in force_include_value:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"header adaptation for {source_text} has an invalid "
                        "force-include source"
                    )
                relative = PurePosixPath(value)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or len(relative.parts) < 2
                    or relative.parts[0] != "src"
                ):
                    raise ValueError(f"unsafe force-include source: {relative}")
                relative_text = relative.as_posix()
                if relative_text in force_seen:
                    raise ValueError(
                        f"duplicate force-include source: {relative_text}"
                    )
                if not decomp.joinpath(*relative.parts).is_file():
                    raise ValueError(
                        f"missing force-include source: {relative_text}"
                    )
                force_seen.add(relative_text)
                force_include_sources.append(relative_text)

        adaptation_entry = entry.get("host_adaptation")
        if not isinstance(adaptation_entry, dict):
            raise ValueError(f"header adaptation for {source_text} is missing")
        adaptation_value = adaptation_entry.get("path")
        if not isinstance(adaptation_value, str) or not adaptation_value.strip():
            raise ValueError(
                f"header adaptation for {source_text} has no manifest path"
            )
        adaptation_relative = PurePosixPath(adaptation_value)
        if adaptation_relative.is_absolute() or ".." in adaptation_relative.parts:
            raise ValueError(
                f"unsafe header-adaptation manifest path: {adaptation_relative}"
            )

        source_path = decomp.joinpath(*source_relative.parts)
        adaptation_path = spec_dir.joinpath(*adaptation_relative.parts)
        if not source_path.is_file():
            raise ValueError(f"missing adapted header source: {source_text}")
        if not adaptation_path.is_file():
            raise ValueError(
                f"missing header-adaptation manifest: "
                f"{adaptation_relative.as_posix()}"
            )
        expected_adaptation_hash = str(
            adaptation_entry.get("sha256", "")
        ).lower()
        actual_adaptation_hash = sha256_bytes(adaptation_path.read_bytes())
        if actual_adaptation_hash != expected_adaptation_hash:
            raise ValueError(
                f"header-adaptation manifest hash mismatch for {source_text}: "
                f"expected {expected_adaptation_hash}, "
                f"got {actual_adaptation_hash}"
            )

        adaptation = load_adaptation(adaptation_path)
        if adaptation.get("source_path") != source_text:
            raise ValueError(
                f"header-adaptation source path mismatch for {source_text}"
            )
        adapted = apply_adaptation(source_path.read_bytes(), adaptation)
        include_relative = PurePosixPath(*source_relative.parts[1:])
        output_path = output_root.joinpath(*include_relative.parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.is_file() or output_path.read_bytes() != adapted:
            output_path.write_bytes(adapted)
        manifest_entry: dict[str, object] = {
            "path": source_text,
            "source_sha256": sha256_bytes(source_path.read_bytes()),
            "include_path": include_relative.as_posix(),
            "adaptation_path": adaptation_relative.as_posix(),
            "adaptation_sha256": actual_adaptation_hash,
            "adapted_sha256": sha256_bytes(adapted),
            "replacement_count": len(adaptation["replacements"]),
            "claim_boundary": adaptation["claim_boundary"],
        }
        if force_include_sources is not None:
            manifest_entry["force_include_sources"] = force_include_sources
        manifest.append(manifest_entry)

    # Preserve the reviewed spec order. Forced headers can depend on an earlier
    # adapted header being parsed before a consumer's quoted include reaches
    # the upstream include tree and sets the same include guard.
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--adaptation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = args.source.read_bytes()
    adaptation = load_adaptation(args.adaptation)
    verify_native_dependencies(adaptation, args.adaptation.resolve().parents[2])
    result = apply_adaptation(source, adaptation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    print(
        "source-adaptation=pass "
        f"source={adaptation['source_path']} "
        f"sha256={sha256_bytes(result)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
