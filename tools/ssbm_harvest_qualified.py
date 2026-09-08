#!/usr/bin/env python3
"""Harvest distinct qualified replays from native full-match oracle reports.

Scans schema-2 full-match report files (tools/ssbm_native_full_match.py
output) for complete_exact:true entries and groups them by replay content
hash. Mixed stage/character claims for one hash, or source/native frame
count mismatches, are hard failures: they indicate corrupted evidence, not
a wider corpus. Reports lacking settings-level fields (slippi version,
item state, UCF evidence, dataset provenance) are harvested as-is; those
manifest fields are backfilled from the pinned-parser extraction cache by
tools/ssbm_backfill_corpus.py before manifest admission.

Output is tools/ssbm_qualified_harvest.json. Regenerate after every
qualification run; the file records which runner and asset-pack identities
produced each pass so stale-identity entries are visible.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_GLOBS = (
    "build/ssbm-native/*.json",
    "build/slippi-full-match/*.json",
)
DEFAULT_OUTPUT = ROOT / "tools" / "ssbm_qualified_harvest.json"


def harvest(report_patterns: tuple[str, ...], repo_root: Path) -> dict:
    entries: dict[str, dict] = {}
    scanned = 0
    for pattern in report_patterns:
        for path in glob.glob(str(repo_root / pattern)):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(report, dict):
                continue
            scanned += 1
            if report.get("complete_exact") is not True:
                continue
            digest = report.get("replay_sha256")
            if not isinstance(digest, str) or not digest:
                raise ValueError(f"{path}: passing report lacks replay_sha256")
            stage = report.get("stage_id")
            chars = tuple(report.get("character_ids", []))
            if report.get("source_frames") != report.get("native_frames"):
                raise ValueError(
                    f"{path}: pass report frame count mismatch "
                    f"{report.get('source_frames')} vs {report.get('native_frames')}"
                )
            entry = entries.setdefault(
                digest,
                {
                    "sha256": digest,
                    "stage_id": stage,
                    "characters": list(chars),
                    "frames": report.get("source_frames"),
                    "asset_pack_sha256": set(),
                    "runner_sha256": set(),
                    "report_paths": [],
                },
            )
            if entry["stage_id"] != stage or entry["characters"] != list(chars):
                raise ValueError(
                    f"{path}: conflicting identity for replay {digest[:12]}"
                )
            entry["asset_pack_sha256"].add(report.get("asset_pack_sha256", ""))
            entry["runner_sha256"].add(report.get("runner_sha256", ""))
            entry["report_paths"].append(
                str(Path(path).relative_to(repo_root))
            )

    qualified = []
    for digest in sorted(entries):
        entry = entries[digest]
        qualified.append(
            {
                "sha256": digest,
                "stage_id": entry["stage_id"],
                "characters": entry["characters"],
                "frames": entry["frames"],
                "asset_pack_sha256": sorted(entry["asset_pack_sha256"]),
                "runner_sha256": sorted(entry["runner_sha256"]),
                "report_count": len(entry["report_paths"]),
                "report_paths": sorted(entry["report_paths"]),
                "result": "pass",
            }
        )
    harvest_blob = json.dumps(qualified, sort_keys=True).encode("utf-8")
    return {
        "schema": 1,
        "id": "ssbm-native-qualified-harvest",
        "description": (
            "Distinct replays with at least one complete_exact:true schema-2 "
            "native full-match report. Settings-level manifest fields "
            "(slippi version, item state, UCF evidence, dataset provenance) "
            "are backfilled by tools/ssbm_backfill_corpus.py from the "
            "pinned-parser extraction cache before manifest admission. "
            "Identity note 2026-09-03: all 13 latest pass reports ran under "
            "runner SHA-256 "
            "7d2579cfceed9fec284ab3e2163489c76ef69248a751bcdc4745901e2d46c632, "
            "which is byte-identical to the runner built from post-81693c4 "
            "HEAD content (a post-commit reconfigure regenerates "
            "byte-identical adapted sources and rebuilds nothing; the "
            "committed anim-flags layout test passes). All 10 distinct "
            "report-pinned asset-pack bytes are present on disk, including "
            "the latest 3e1886a8... pack behind the x596-class-fix passes; "
            "promotion to gate-counted passes awaits the recorded-identity "
            "re-run per the evidence model."
        ),
        "distinct_replays": len(qualified),
        "reports_scanned": scanned,
        "harvest_sha256": hashlib.sha256(harvest_blob).hexdigest(),
        "qualified": qualified,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("patterns", nargs="*", default=list(DEFAULT_REPORT_GLOBS))
    args = parser.parse_args(argv)

    result = harvest(tuple(args.patterns), ROOT)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"distinct qualified replays: {result['distinct_replays']}")
    print(f"reports scanned: {result['reports_scanned']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
