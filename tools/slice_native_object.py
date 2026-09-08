#!/usr/bin/env python3
"""Retain one exact function/data section closure from a native object.

This is a host-link transformation over an already compiled source object.  It
does not translate instructions, emulate the source platform, or establish
runtime/behavioral coverage.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Iterable


CLAIM_BOUNDARY = "native-section-closure-not-runtime-or-behavioral-coverage"
COFF_SYMBOL = re.compile(
    r"^\[\s*\d+\]\(sec\s+(-?\d+)\).*?\)\s+"
    r"0x[0-9A-Fa-f]+\s+(\S+)\s*$"
)
SECTION_HEADER = re.compile(r"^\s*(\d+)\s+(\S+)\s+[0-9A-Fa-f]+\s+")
RELOCATION_HEADER = re.compile(r"^RELOCATION RECORDS FOR \[(.+)\]:$")
RELOCATION_ROW = re.compile(
    r"^\s*[0-9A-Fa-f]+\s+\S+\s+(\S+?)(?:[+-]0x[0-9A-Fa-f]+)?\s*$"
)
OBJECT_FORMAT = re.compile(r"file format (\S+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_executable(value: str, label: str) -> Path:
    resolved = shutil.which(value)
    if resolved is None:
        raise ValueError(f"{label} executable not found: {value}")
    return Path(resolved).resolve()


def executable_version(executable: Path) -> str:
    process = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = process.stdout.splitlines()
    if not lines:
        raise ValueError(f"{executable} produced no version output")
    return lines[0].strip()


def run_text(executable: Path, *arguments: str) -> str:
    process = subprocess.run(
        [str(executable), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout


def parse_sections(output: str) -> tuple[str, ...]:
    sections: list[str] = []
    for line in output.splitlines():
        match = SECTION_HEADER.match(line)
        if match is None:
            continue
        index = int(match.group(1))
        if index != len(sections):
            raise ValueError(
                f"non-contiguous objdump section index: expected "
                f"{len(sections)}, got {index}"
            )
        sections.append(match.group(2))
    if not sections:
        raise ValueError("objdump reported no object sections")
    duplicates = {
        section for section in sections if sections.count(section) > 1
    }
    unsupported_duplicates = duplicates - {".group"}
    if unsupported_duplicates:
        raise ValueError(
            "object contains unsupported duplicate section names: "
            + ", ".join(sorted(unsupported_duplicates))
        )
    return tuple(sections)


def parse_object_format(output: str) -> str:
    match = OBJECT_FORMAT.search(output)
    if match is None:
        raise ValueError("objdump reported no object format")
    return match.group(1)


def slice_method_for_format(object_format: str) -> str:
    if object_format.startswith("elf"):
        return "elf-relocatable-link-gc"
    if object_format.startswith(("pe-", "pei-")):
        return "coff-explicit-section-remove-strip"
    raise ValueError(f"unsupported native object format: {object_format}")


def parse_symbols(
    output: str, sections: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    known_sections = set(sections)
    symbol_sections: dict[str, set[str]] = {}
    for line in output.splitlines():
        coff = COFF_SYMBOL.match(line)
        if coff is not None:
            section_index = int(coff.group(1))
            if section_index <= 0:
                continue
            if section_index > len(sections):
                raise ValueError(
                    f"symbol references missing section index {section_index}"
                )
            section = sections[section_index - 1]
            symbol_sections.setdefault(coff.group(2), set()).add(section)
            continue

        fields = line.split()
        if len(fields) < 2:
            continue
        matching = [field for field in fields[:-1] if field in known_sections]
        if not matching:
            continue
        section = matching[-1]
        symbol_sections.setdefault(fields[-1], set()).add(section)

    return {
        symbol: tuple(sorted(owners))
        for symbol, owners in sorted(symbol_sections.items())
    }


def parse_relocations(output: str) -> dict[str, tuple[str, ...]]:
    relocations: dict[str, set[str]] = {}
    current: str | None = None
    for line_number, line in enumerate(output.splitlines(), start=1):
        header = RELOCATION_HEADER.match(line.strip())
        if header is not None:
            current = header.group(1)
            relocations.setdefault(current, set())
            continue
        if current is None or not line.strip() or line.lstrip().startswith("OFFSET"):
            continue
        row = RELOCATION_ROW.match(line)
        if row is None:
            raise ValueError(
                f"unrecognized relocation output at line {line_number}: {line}"
            )
        relocations[current].add(row.group(1))
    return {
        section: tuple(sorted(targets))
        for section, targets in sorted(relocations.items())
    }


def companion_sections(section: str, sections: set[str]) -> tuple[str, ...]:
    companions = [f".rel{section}", f".rela{section}"]
    if section.startswith(".text$"):
        suffix = section[len(".text$") :]
        companions.extend((f".xdata${suffix}", f".pdata${suffix}"))
    return tuple(candidate for candidate in companions if candidate in sections)


def compute_section_closure(
    *,
    roots: Iterable[str],
    sections: Iterable[str],
    symbol_sections: dict[str, tuple[str, ...]],
    relocations: dict[str, tuple[str, ...]],
    external_symbols: Iterable[str] = (),
) -> dict[str, object]:
    root_list = tuple(sorted(set(roots)))
    if not root_list:
        raise ValueError("at least one root symbol is required")
    section_set = set(sections)
    external_symbol_set = set(external_symbols)
    root_sections: dict[str, str] = {}
    for root in root_list:
        owners = symbol_sections.get(root, ())
        if len(owners) != 1:
            raise ValueError(
                f"root symbol must have exactly one defining section: "
                f"{root} has {len(owners)}"
            )
        root_sections[root] = owners[0]

    selected: set[str] = set()
    queue: deque[tuple[str, str]] = deque(
        (section, f"root:{root}") for root, section in root_sections.items()
    )
    edges: set[tuple[str, str, str]] = set()
    unresolved: dict[str, set[str]] = {}

    while queue:
        section, reason = queue.popleft()
        if section in selected:
            continue
        if section not in section_set:
            raise ValueError(f"selected section is missing from object: {section}")
        selected.add(section)

        for companion in companion_sections(section, section_set):
            edges.add((section, companion, "host-unwind-companion"))
            queue.append((companion, "host-unwind-companion"))

        for target in relocations.get(section, ()):
            if target in external_symbol_set:
                unresolved.setdefault(target, set()).add(section)
                continue
            if target in section_set:
                owners = (target,)
            else:
                owners = symbol_sections.get(target, ())
            if len(owners) > 1:
                raise ValueError(
                    f"relocation target has ambiguous defining sections: "
                    f"{target}: {', '.join(owners)}"
                )
            if owners:
                destination = owners[0]
                edges.add((section, destination, target))
                queue.append((destination, f"relocation:{target}"))
            else:
                unresolved.setdefault(target, set()).add(section)

    return {
        "roots": list(root_list),
        "root_sections": root_sections,
        "selected_sections": sorted(selected),
        "section_edges": [
            {"consumer": consumer, "provider": provider, "target": target}
            for consumer, provider, target in sorted(edges)
        ],
        "external_frontier": [
            {"symbol": symbol, "consumers": sorted(consumers)}
            for symbol, consumers in sorted(unresolved.items())
        ],
    }


def slice_object(
    *,
    objdump: Path,
    objcopy: Path,
    linker: Path,
    linker_arguments: tuple[str, ...] = (),
    input_path: Path,
    output_path: Path,
    roots: Iterable[str],
    external_symbols: Iterable[str] = (),
) -> dict[str, object]:
    headers = run_text(objdump, "-h", str(input_path))
    object_format = parse_object_format(headers)
    slice_method = slice_method_for_format(object_format)
    is_elf = slice_method == "elf-relocatable-link-gc"
    sections = parse_sections(headers)
    symbols = parse_symbols(run_text(objdump, "-t", str(input_path)), sections)
    relocations = parse_relocations(run_text(objdump, "-r", str(input_path)))
    closure = compute_section_closure(
        roots=roots,
        sections=sections,
        symbol_sections=symbols,
        relocations=relocations,
        external_symbols=external_symbols,
    )
    closure["object_format"] = object_format
    closure["slice_method"] = slice_method

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        if is_elf:
            command = [str(linker), *linker_arguments, "-r", "--gc-sections"]
            for root in closure["roots"]:
                command.extend(("-u", root))
            command.extend((str(input_path), "-o", str(temporary_path)))
        else:
            command = [str(objcopy), "--strip-unneeded"]
            selected_sections = set(closure["selected_sections"])
            command.extend(
                f"--remove-section={section}"
                for section in sections
                if section not in selected_sections
            )
            command.extend((str(input_path), str(temporary_path)))
        subprocess.run(command, check=True)

        sliced_sections = parse_sections(
            run_text(objdump, "-h", str(temporary_path))
        )
        if (
            not is_elf
            and set(sliced_sections) != set(closure["selected_sections"])
        ):
            raise ValueError(
                "objcopy output section set mismatch: "
                f"expected {closure['selected_sections']}, "
                f"got {sorted(sliced_sections)}"
            )
        sliced_symbols = parse_symbols(
            run_text(objdump, "-t", str(temporary_path)), sliced_sections
        )
        missing_roots = [
            root for root in closure["roots"] if root not in sliced_symbols
        ]
        if missing_roots:
            raise ValueError(
                "objcopy output lost root symbols: " + ", ".join(missing_roots)
            )
        unexpected_symbols = sorted(
            symbol
            for symbol, owners in sliced_symbols.items()
            if symbol in symbols
            and not symbol.startswith(
                (".text.__x86.get_pc_thunk.", "__x86.get_pc_thunk.")
            )
            and not set(symbols[symbol]) & set(closure["selected_sections"])
            and any(
                not owner.startswith((".comment", ".eh_frame", ".note"))
                for owner in owners
            )
        )
        if unexpected_symbols:
            raise ValueError(
                "sliced object retained symbols from outside the closure: "
                + ", ".join(unexpected_symbols)
            )
        sliced_relocations = parse_relocations(
            run_text(objdump, "-r", str(temporary_path))
        )
        sliced_closure = compute_section_closure(
            roots=closure["roots"],
            sections=sliced_sections,
            symbol_sections=sliced_symbols,
            relocations=sliced_relocations,
            external_symbols=external_symbols,
        )
        for field in (
            "roots",
            "root_sections",
            "selected_sections",
            "section_edges",
            "external_frontier",
        ):
            if sliced_closure[field] != closure[field]:
                raise ValueError(
                    f"sliced object {field} differs from planned closure"
                )
        for consumer, targets in sliced_relocations.items():
            if consumer not in set(sliced_sections):
                raise ValueError(
                    f"sliced relocation owner is not retained: {consumer}"
                )
            for target in targets:
                if consumer.startswith((".eh_frame", ".comment", ".note")):
                    continue
                owners = sliced_symbols.get(target, ())
                if target in sliced_sections or owners:
                    continue
                if not any(
                    row["symbol"] == target
                    for row in closure["external_frontier"]
                ):
                    raise ValueError(
                        f"sliced object introduced external symbol: {target}"
                    )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return closure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--objcopy", default="objcopy")
    parser.add_argument("--linker", default="ld")
    parser.add_argument("--linker-argument", action="append", default=[])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", action="append", required=True)
    args = parser.parse_args()

    input_path = args.input.resolve()
    if not input_path.is_file():
        raise SystemExit(f"input object not found: {input_path}")
    objdump = resolve_executable(args.objdump, "objdump")
    objcopy = resolve_executable(args.objcopy, "objcopy")
    linker = resolve_executable(args.linker, "linker")
    try:
        closure = slice_object(
            objdump=objdump,
            objcopy=objcopy,
            linker=linker,
            linker_arguments=tuple(args.linker_argument),
            input_path=input_path,
            output_path=args.output.resolve(),
            roots=args.root,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise SystemExit(f"native object slicing failed: {error}") from error

    manifest = {
        "schema": 1,
        "claim_boundary": CLAIM_BOUNDARY,
        "input": {
            "path": input_path.as_posix(),
            "sha256": sha256(input_path),
        },
        "output": {
            "path": args.output.resolve().as_posix(),
            "sha256": sha256(args.output.resolve()),
        },
        "tools": {
            "objdump": {
                "path": objdump.as_posix(),
                "version": executable_version(objdump),
            },
            "objcopy": {
                "path": objcopy.as_posix(),
                "version": executable_version(objcopy),
            },
            "linker": {
                "path": linker.as_posix(),
                "version": executable_version(linker),
                "arguments": args.linker_argument,
            },
        },
        **closure,
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "native-object-slice=pass "
        f"roots={len(manifest['roots'])} "
        f"sections={len(manifest['selected_sections'])} "
        f"external={len(manifest['external_frontier'])} "
        f"sha256={manifest['output']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
