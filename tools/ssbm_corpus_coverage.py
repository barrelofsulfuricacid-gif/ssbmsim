#!/usr/bin/env python3
"""Fail-closed admission and coverage audit for the declared acceptance corpus.

Reads tools/ssbm_acceptance_corpus.json, rejects every entry that violates
the admission filters, deduplicates by content hash, and reports character
and stage coverage against the required roster. Exit status is non-zero
when any entry is inadmissible or a duplicate exists; coverage shortfalls
are reported but do not fail, since acquisition is still in progress.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tools" / "ssbm_acceptance_corpus.json"


def load_manifest(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def audit_entry(entry: dict, admission: dict) -> list[str]:
    """Return a list of violation strings; empty means admissible."""
    violations = []
    if entry.get("stage_id") not in admission["stage_ids"]:
        violations.append(f"stage_id {entry.get('stage_id')} not in admission set")
    if admission["items_must_be_off"] and entry.get("items_off") is not True:
        violations.append("items_off must be true")
    if (
        entry.get("stage_id") == 3
        and admission["pokemon_stadium_requires_frozen_flag"]
        and entry.get("frozen_pokemon_stadium") is not True
    ):
        violations.append("Pokemon Stadium entry lacks frozen flag")
    if admission["complete_match_only"] and entry.get("complete") is not True:
        violations.append("only complete matches are admissible")
    for field in ("sha256", "characters", "start_frame", "end_frame"):
        if entry.get(field) is None:
            violations.append(f"missing required field: {field}")
    return violations


def audit_manifest(manifest: dict) -> dict:
    admission = manifest["admission"]
    required_characters = manifest["required_characters"]
    required_stages = manifest["required_stages"]
    seen_hashes: dict[str, int] = {}
    violations: list[str] = []
    admitted: list[dict] = []

    for index, entry in enumerate(manifest.get("qualified", [])):
        digest = entry.get("sha256", f"<missing-hash-{index}>")
        if digest in seen_hashes:
            violations.append(
                f"duplicate content hash {digest} at index {index} "
                f"(first seen at {seen_hashes[digest]})"
            )
            continue
        seen_hashes[digest] = index
        for problem in audit_entry(entry, admission):
            violations.append(f"entry {index} ({digest[:12]}): {problem}")
            break
        else:
            admitted.append(entry)

    covered_chars = sorted(
        {str(char) for entry in admitted for char in entry.get("characters", [])}
    )
    covered_stages = sorted({str(entry["stage_id"]) for entry in admitted})
    missing_chars = sorted(set(required_characters) - set(covered_chars))
    missing_stages = sorted(set(required_stages) - set(covered_stages))

    return {
        "target": manifest["required_match_count"],
        "admitted": len(admitted),
        "violations": violations,
        "covered_characters": {
            char: required_characters[char] for char in covered_chars if char in required_characters
        },
        "unexpected_characters": [c for c in covered_chars if c not in required_characters],
        "missing_characters": {
            char: required_characters[char] for char in missing_chars
        },
        "covered_stages": {
            stage: required_stages[stage] for stage in covered_stages if stage in required_stages
        },
        "missing_stages": {
            stage: required_stages[stage] for stage in missing_stages
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))
    report = audit_manifest(manifest)

    print(f"admitted {report['admitted']} / {report['target']} target")
    print(
        "characters covered "
        f"{len(report['covered_characters'])}/{len(manifest['required_characters'])} "
        f"missing: {sorted(report['missing_characters'].values())}"
    )
    print(
        "stages covered "
        f"{len(report['covered_stages'])}/6 "
        f"missing: {sorted(report['missing_stages'].values())}"
    )
    if report["unexpected_characters"]:
        print(f"unexpected character IDs: {report['unexpected_characters']}")
    for problem in report["violations"]:
        print(f"VIOLATION: {problem}")

    if args.report is not None:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)

    return 1 if report["violations"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
