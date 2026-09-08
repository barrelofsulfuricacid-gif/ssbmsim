#!/usr/bin/env python3
"""Validate pinned, source-scoped native compiler policy exceptions."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re


CLAIM_BOUNDARY = "source-scoped-host-diagnostic-not-behavioral-coverage"
OPTION_PATTERN = re.compile(r"-Wno-[a-z0-9-]+\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_compile_options(
    spec: dict[str, object], *, decomp: Path
) -> list[dict[str, object]]:
    entries = spec.get("source_compile_options", [])
    if not isinstance(entries, list):
        raise ValueError("source_compile_options must be a list")

    result: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"source compile policy {index} is not an object")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise ValueError(f"source compile policy {index} has no path")
        relative = PurePosixPath(path_value)
        is_primary_source = (
            len(relative.parts) >= 3 and relative.parts[0] == "src"
        )
        is_dolphin_matrix_source = (
            len(relative.parts) >= 6
            and relative.parts[:5]
            == ("extern", "dolphin", "src", "dolphin", "mtx")
        )
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not (is_primary_source or is_dolphin_matrix_source)
            or relative.suffix != ".c"
        ):
            raise ValueError(f"unsafe source compile policy path: {relative}")
        path_text = relative.as_posix()
        if path_text in seen_paths:
            raise ValueError(f"duplicate source compile policy path: {path_text}")
        seen_paths.add(path_text)

        expected_hash = entry.get("source_sha256")
        if (
            not isinstance(expected_hash, str)
            or not SHA256_PATTERN.fullmatch(expected_hash)
        ):
            raise ValueError(f"invalid source hash for {path_text}")
        source_path = decomp.joinpath(*relative.parts)
        if not source_path.is_file():
            raise ValueError(f"missing source compile policy file: {path_text}")
        actual_hash = sha256(source_path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"source compile policy hash mismatch for {path_text}: "
                f"expected {expected_hash}, got {actual_hash}"
            )

        options = entry.get("options")
        if (
            not isinstance(options, list)
            or not options
            or not all(
                isinstance(option, str) and OPTION_PATTERN.fullmatch(option)
                for option in options
            )
            or len(options) != len(set(options))
        ):
            raise ValueError(f"invalid source compile options for {path_text}")
        evidence = entry.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError(f"missing source compile evidence for {path_text}")
        if entry.get("claim_boundary") != CLAIM_BOUNDARY:
            raise ValueError(f"invalid source compile claim boundary for {path_text}")

        result.append(
            {
                "path": path_text,
                "source_sha256": actual_hash,
                "options": list(options),
                "evidence": evidence,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    return result


def options_by_path(
    entries: list[dict[str, object]],
) -> dict[str, tuple[str, ...]]:
    return {
        str(entry["path"]): tuple(str(value) for value in entry["options"])
        for entry in entries
    }
