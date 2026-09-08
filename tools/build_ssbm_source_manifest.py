#!/usr/bin/env python3
"""Build the exhaustive GALE01 symbol and native-port evidence ledger."""

from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import subprocess
from dataclasses import dataclass


SYMBOL = re.compile(
    r"^(?P<name>[^=]+?)\s*=\s*(?P<section>[^:;]+):0x(?P<address>[0-9A-Fa-f]+);"
    r"\s*//\s*type:(?P<type>\w+)(?:\s+size:0x(?P<size>[0-9A-Fa-f]+))?"
)
SPLIT_UNIT = re.compile(r"^(?P<unit>[^\s].*):$")
SPLIT_SECTION = re.compile(
    r"^\s*(?P<section>\.?[A-Za-z0-9_]+)\s+"
    r"start:0x(?P<start>[0-9A-Fa-f]+)\s+end:0x(?P<end>[0-9A-Fa-f]+)"
)
CALLBACK_TABLE_NAME = re.compile(
    r"(?:motion|action|item|stage|callback|callbacks|state)table", re.IGNORECASE
)


@dataclass(frozen=True)
class SectionRange:
    unit: str
    section: str
    start: int
    end: int


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def revision(root: Path) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.strip().lower()


def parse_section_ranges(path: Path) -> dict[str, list[SectionRange]]:
    result: dict[str, list[SectionRange]] = {}
    unit: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        unit_match = SPLIT_UNIT.match(line)
        if unit_match and not line.startswith("Sections"):
            unit = unit_match.group("unit")
            continue
        section_match = SPLIT_SECTION.match(line)
        if section_match and unit is not None:
            section = section_match.group("section")
            result.setdefault(section, []).append(
                SectionRange(
                    unit,
                    section,
                    int(section_match.group("start"), 16),
                    int(section_match.group("end"), 16),
                )
            )
    for section, ranges in result.items():
        ranges.sort(key=lambda entry: (entry.start, entry.end, entry.unit))
        for left, right in zip(ranges, ranges[1:], strict=False):
            if left.end > right.start:
                raise ValueError(
                    f"overlapping {section} ranges: {left.unit} and {right.unit}"
                )
    return result


def owner_for(
    address: int, section: str, ranges: dict[str, list[SectionRange]]
) -> str | None:
    candidates = ranges.get(section)
    if not candidates:
        return None
    starts = [candidate.start for candidate in candidates]
    index = bisect_right(starts, address) - 1
    if index < 0:
        return None
    candidate = candidates[index]
    return candidate.unit if address < candidate.end else None


def module_for(unit: str | None) -> str:
    if unit is None:
        return "unowned"
    parts = unit.split("/")
    if parts[0] == "melee" and len(parts) > 1:
        return parts[1]
    if parts[0] == "sysdolphin" and len(parts) > 1:
        return f"sysdolphin/{parts[1]}"
    if parts[0] == "dolphin" and len(parts) > 1:
        return f"dolphin/{parts[1]}"
    return parts[0]


def candidate(module: str) -> bool:
    return module in {
        "ft",
        "gm",
        "gr",
        "it",
        "lb",
        "mp",
        "pl",
        "MSL",
        "dolphin/mtx",
        "sysdolphin/baselib",
    }


def source_relative(unit: str | None) -> str | None:
    if unit is None:
        return None
    if unit.startswith("dolphin/"):
        return f"extern/dolphin/src/{unit}"
    return f"src/{unit}"


def record_source_hash(
    source_hashes: dict[str, str], relative: str, source_path: Path
) -> None:
    if relative not in source_hashes and source_path.is_file():
        source_hashes[relative] = sha256(source_path)


def port_evidence(
    relative: str | None,
    module: str,
    readiness_by_path: dict[str, dict[str, object]],
    selected: dict[str, dict[str, object]],
    excluded: dict[str, dict[str, object]],
    readiness_digest: str,
) -> tuple[str, dict[str, object] | None]:
    if relative is None:
        return "source-unowned", None
    if not candidate(module):
        return "outside-gameplay-candidate-scope", None
    readiness = readiness_by_path.get(relative)
    if readiness is None:
        return "readiness-missing", {"translation_unit": relative}
    compile_status = str(readiness["compile_status"])
    is_selected = relative in selected
    host_adaptation = (
        selected[relative].get("host_adaptation") if is_selected else None
    )
    native_import_roots = (
        selected[relative].get("roots", []) if is_selected else []
    )
    if is_selected and compile_status != "ready" and host_adaptation is None:
        raise ValueError(f"selected source is not compile-ready: {relative}")
    if is_selected and native_import_roots and host_adaptation is not None:
        status = "selected-rooted-native-import-host-adapted"
    elif is_selected and native_import_roots:
        status = "selected-rooted-native-import"
    elif is_selected and host_adaptation is not None:
        status = "selected-native-import-host-adapted"
    elif is_selected:
        status = "selected-native-import"
    elif relative in excluded:
        status = "host-object-excluded-from-native-provider-inventory"
    elif compile_status == "ready":
        status = "host-object-ready"
    else:
        status = "host-object-blocked"
    return status, {
        "translation_unit": relative,
        "source_sha256": readiness["sha256"],
        "compile_status": compile_status,
        "blocker": readiness["blocker"],
        "native_import_selected": is_selected,
        "native_import_roots": native_import_roots,
        "host_adaptation": host_adaptation,
        "provider_exclusion": excluded.get(relative),
        "readiness_report_sha256": readiness_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decomp", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--import-spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = args.decomp.resolve()
    actual_revision = revision(root)
    expected_revision = args.revision.lower()
    if actual_revision != expected_revision:
        raise SystemExit(
            f"decomp revision mismatch: expected {expected_revision}, got {actual_revision}"
        )

    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
    import_spec = json.loads(args.import_spec.read_text(encoding="utf-8"))
    if readiness.get("schema") != 1:
        raise SystemExit("unsupported readiness schema")
    if import_spec.get("schema") != 1:
        raise SystemExit("unsupported import-spec schema")
    if readiness.get("decomp_revision") != actual_revision:
        raise SystemExit("readiness decomp revision mismatch")
    if import_spec.get("decomp_revision") != actual_revision:
        raise SystemExit("import-spec decomp revision mismatch")

    readiness_digest = sha256(args.readiness)
    readiness_by_path = {
        str(unit["path"]): unit for unit in readiness["translation_units"]
    }
    if len(readiness_by_path) != int(readiness["translation_unit_count"]):
        raise SystemExit("duplicate or missing readiness translation unit")
    selected = {
        str(unit["path"]): unit for unit in import_spec["translation_units"]
    }
    if len(selected) != len(import_spec["translation_units"]):
        raise SystemExit("duplicate selected import translation unit")
    excluded = {
        str(unit["path"]): unit
        for unit in import_spec.get("provider_exclusions", [])
    }
    if len(excluded) != len(import_spec.get("provider_exclusions", [])):
        raise SystemExit("duplicate provider exclusion")

    config = root / "config" / "GALE01"
    symbols_path = config / "symbols.txt"
    splits_path = config / "splits.txt"
    config_path = config / "config.yml"
    ranges = parse_section_ranges(splits_path)
    symbols: list[dict[str, object]] = []
    source_hashes: dict[str, str] = {}
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    callback_table_candidate_count = 0

    for line_number, line in enumerate(
        symbols_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = SYMBOL.match(line)
        if match is None:
            continue
        address = int(match.group("address"), 16)
        section = match.group("section")
        unit = owner_for(address, section, ranges)
        module = module_for(unit)
        relative = source_relative(unit)
        source_path = root / relative if relative is not None else None
        if source_path is not None:
            record_source_hash(source_hashes, relative, source_path)
        status, evidence = port_evidence(
            relative,
            module,
            readiness_by_path,
            selected,
            excluded,
            readiness_digest,
        )
        symbol_type = match.group("type")
        table_candidate = bool(
            symbol_type == "object"
            and CALLBACK_TABLE_NAME.search(match.group("name"))
        )
        callback_table_candidate_count += int(table_candidate)
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[symbol_type] = type_counts.get(symbol_type, 0) + 1
        symbols.append(
            {
                "name": match.group("name").strip(),
                "symbol_type": symbol_type,
                "section": section,
                "address": address,
                "size": int(match.group("size"), 16)
                if match.group("size")
                else None,
                "symbol_line": line_number,
                "source_unit": unit,
                "source_path": relative,
                "module": module,
                "gameplay_candidate": candidate(module),
                "callback_table_name_candidate": table_candidate,
                "port_status": status,
                "port_evidence": evidence,
            }
        )

    symbols.sort(key=lambda symbol: (symbol["address"], symbol["name"]))
    address_keys = [(symbol["address"], symbol["name"]) for symbol in symbols]
    if len(address_keys) != len(set(address_keys)):
        raise SystemExit("duplicate symbol address/name record")

    unit_symbol_counts: dict[str, dict[str, int]] = {}
    for symbol in symbols:
        relative = symbol["source_path"]
        if relative is None:
            continue
        counts = unit_symbol_counts.setdefault(str(relative), {})
        symbol_type = str(symbol["symbol_type"])
        counts[symbol_type] = counts.get(symbol_type, 0) + 1

    translation_units: list[dict[str, object]] = []
    for relative, readiness_unit in sorted(readiness_by_path.items()):
        module = module_for(relative.removeprefix("src/"))
        status, evidence = port_evidence(
            relative,
            module,
            readiness_by_path,
            selected,
            excluded,
            readiness_digest,
        )
        translation_units.append(
            {
                "path": relative,
                "module": module,
                "sha256": readiness_unit["sha256"],
                "bytes": readiness_unit["bytes"],
                "symbol_counts": dict(
                    sorted(unit_symbol_counts.get(relative, {}).items())
                ),
                "port_status": status,
                "port_evidence": evidence,
            }
        )

    manifest = {
        "schema": 2,
        "target": "GALE01 NTSC 1.02 + UCF 0.84",
        "claim_boundary": "source-and-host-port-evidence-not-behavioral-coverage",
        "decomp_revision": actual_revision,
        "expected_dol_sha1": "08e0bf20134dfcb260699671004527b2d6bb1a45",
        "symbols_sha256": sha256(symbols_path),
        "splits_sha256": sha256(splits_path),
        "config_sha256": sha256(config_path),
        "readiness_report_sha256": readiness_digest,
        "import_spec_sha256": sha256(args.import_spec),
        "symbol_count": len(symbols),
        "symbol_type_counts": dict(sorted(type_counts.items())),
        "symbol_port_status_counts": dict(sorted(status_counts.items())),
        "gameplay_candidate_symbol_count": sum(
            1 for symbol in symbols if symbol["gameplay_candidate"]
        ),
        "callback_table_name_candidate_count": callback_table_candidate_count,
        "translation_unit_count": len(translation_units),
        "host_object_ready_unit_count": int(readiness["ready_count"]),
        "host_object_blocked_unit_count": int(readiness["blocked_count"]),
        "selected_native_import_unit_count": len(selected),
        "host_adapted_selected_unit_count": sum(
            1 for unit in selected.values() if unit.get("host_adaptation") is not None
        ),
        "rooted_selected_unit_count": sum(
            1 for unit in selected.values() if unit.get("roots")
        ),
        "provider_excluded_unit_count": len(excluded),
        "source_files": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(source_hashes.items())
        ],
        "translation_units": translation_units,
        "symbols": symbols,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if (
        not args.output.is_file()
        or args.output.read_text(encoding="utf-8") != encoded
    ):
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "ssbm-source-manifest=pass "
        f"symbols={manifest['symbol_count']} "
        f"candidates={manifest['gameplay_candidate_symbol_count']} "
        f"units={manifest['translation_unit_count']} "
        f"ready={manifest['host_object_ready_unit_count']} "
        f"selected={manifest['selected_native_import_unit_count']} "
        f"sha256={hashlib.sha256(encoded.encode()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
