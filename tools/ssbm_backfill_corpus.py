#!/usr/bin/env python3
"""Backfill acceptance-corpus manifest entries from pinned-parser evidence.

Reads tools/ssbm_qualified_harvest.json for the distinct qualified replay
hashes, then fills every settings-level manifest field from the hash-keyed
pinned-parser extraction cache (build/ssbm-native/replay-cache/<sha>.json,
schema 2, produced by tools/ssbm_slippi_extract.mjs through the pinned
@slippi/slippi-js revision). Dataset bucket names come from the schema-2
full-match reports on disk.

Fail-closed: any entry whose cached extraction violates the admission
filters (legal stage, items-off, frozen-PS flag, complete contiguous frames
from -123, GameEnd present, human 4-stock UCF players, exact raw sticks)
aborts without writing. Entries are written with result "pending": promotion
to "pass" requires full canonical oracle qualification, never this tool.
Frozen acceptance corpora cannot be replaced by a harvest.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tools" / "ssbm_acceptance_corpus.json"
DEFAULT_HARVEST = ROOT / "tools" / "ssbm_qualified_harvest.json"
DEFAULT_CACHE_DIR = ROOT / "build" / "ssbm-native" / "replay-cache"
DEFAULT_REPORT_GLOBS = ("build/ssbm-native/*.json",)

# Buckets with pinned redistribution evidence. Every other bucket keeps an
# explicit unconfirmed license so no entry overclaims redistribution rights.
PINNED_SOURCES = {
    "ganondorf-master-master-a6": (
        "erickfm/melee-ranked-replays @11142d4b86d423716fdd2e9ca565de9bafc9d37e "
        "(MIT); archive GANONDORF_master-master_a6.tar.gz upstream-sha256 "
        "f5b3c9177ca74504f3984e2820cd4bc31c00e59a5a639cdfe7d83f69c7a80388"
    ),
}


class BackfillError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as error:
        raise BackfillError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise BackfillError(f"{path}: root must be an object")
    return value


def index_buckets(report_globs: tuple[str, ...]) -> dict[str, str]:
    index: dict[str, str] = {}
    for pattern in report_globs:
        for path in glob.glob(str(ROOT / pattern)):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(report, dict):
                continue
            digest = report.get("replay_sha256")
            replay = str(report.get("replay", ""))
            parent = Path(replay).parent.name if replay else ""
            if isinstance(digest, str) and digest and parent and digest not in index:
                index[digest] = parent
    return index


def replay_bucket(digest: str, buckets: dict[str, str]) -> str:
    try:
        return buckets[digest]
    except KeyError:
        raise BackfillError(
            f"{digest[:12]}: no full-match report names its replay path"
        ) from None


def build_entry(
    digest: str,
    cache_dir: Path,
    buckets: dict[str, str],
    bucket: str | None = None,
) -> dict:
    cache_path = cache_dir / f"{digest}.json"
    cached = load_json(cache_path)
    if cached.get("replay_sha256") != digest:
        raise BackfillError(f"{cache_path}: digest mismatch")
    replay = cached.get("replay")
    if not isinstance(replay, dict):
        raise BackfillError(f"{cache_path}: missing replay object")
    settings = replay.get("settings")
    frames = replay.get("frames")
    provenance = replay.get("inputProvenance")
    if not isinstance(settings, dict):
        raise BackfillError(f"{digest[:12]}: missing settings")
    if not isinstance(frames, list) or not frames:
        raise BackfillError(f"{digest[:12]}: missing frames")
    if not isinstance(replay.get("gameEnd"), dict):
        raise BackfillError(f"{digest[:12]}: missing GameEnd (not complete)")
    numbers = [f.get("frame") for f in frames if isinstance(f, dict)]
    if len(numbers) != len(frames) or numbers[0] != -123 or any(
        not isinstance(left, int) or right != left + 1
        for left, right in zip(numbers, numbers[1:])
    ):
        raise BackfillError(f"{digest[:12]}: frames not contiguous from -123")
    players = settings.get("players")
    if not isinstance(players, list) or len(players) != 2:
        raise BackfillError(f"{digest[:12]}: requires two players")
    if any(p.get("type") != 0 for p in players):
        raise BackfillError(f"{digest[:12]}: only human players admitted")
    if any(p.get("startStocks") != 4 for p in players):
        raise BackfillError(f"{digest[:12]}: not four-stock")
    if any(p.get("controllerFix") != "UCF" for p in players):
        raise BackfillError(f"{digest[:12]}: not explicitly UCF")
    if settings.get("isPAL") is not False or settings.get("isTeams") is not False:
        raise BackfillError(f"{digest[:12]}: not NTSC singles")
    if settings.get("itemSpawnBehavior") != 255:
        raise BackfillError(f"{digest[:12]}: items enabled")
    stage = settings.get("stageId")
    if stage not in (2, 3, 8, 28, 31, 32):
        raise BackfillError(f"{digest[:12]}: stage {stage!r} outside legal slice")
    if stage == 3 and settings.get("isFrozenPS") is not True:
        raise BackfillError(f"{digest[:12]}: Pokemon Stadium not frozen")
    if not isinstance(provenance, dict) or any(
        provenance.get(f) is not True
        for f in ("exactRawMainX", "exactRawMainY", "exactRawCX", "exactRawCY")
    ):
        raise BackfillError(f"{digest[:12]}: exact raw sticks unavailable")
    ordered = sorted(players, key=lambda p: int(p.get("playerIndex", -1)))
    ports = [int(p["playerIndex"]) for p in ordered]
    if bucket is None:
        bucket = replay_bucket(digest, buckets)
    source = PINNED_SOURCES.get(
        bucket, f"build/slippi-differential/{bucket} (license unconfirmed)"
    )
    return {
        "sha256": digest,
        "slippi_version": str(settings.get("slpVersion")),
        "players": 2,
        "characters": [int(p["characterId"]) for p in ordered],
        "ports": ports,
        "stage_id": stage,
        "frozen_pokemon_stadium": bool(settings.get("isFrozenPS")),
        "items_off": True,
        "start_frame": int(numbers[0]),
        "end_frame": int(numbers[-1]),
        "complete": True,
        "ucf_evidence": (
            "controllerFix=UCF both players via pinned @slippi/slippi-js 9.1.2; "
            "exact UCF 0.84 revision/config proof rides with the oracle identity"
        ),
        "source": source,
        "result": "pending",
        "pending_reason": "admission metadata only; full canonical oracle qualification pending",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--harvest", default=str(DEFAULT_HARVEST))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--report-glob",
        dest="report_globs",
        action="append",
        default=None,
        help="Report glob for dataset bucket names (repeatable; "
        "defaults to build/ssbm-native/*.json).",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    report_globs = tuple(args.report_globs) if args.report_globs else DEFAULT_REPORT_GLOBS

    manifest = load_json(Path(args.manifest))
    if args.write and (manifest.get("selection", {}).get("frozen")
                       or manifest.get("selection", {}).get("membership_append_only")):
        raise BackfillError("cannot replace a frozen acceptance corpus with a pass harvest")
    harvest = load_json(Path(args.harvest))
    digests = [q["sha256"] for q in harvest.get("qualified", [])]
    if len(set(digests)) != len(digests):
        raise BackfillError("harvest contains duplicate hashes")

    buckets = index_buckets(report_globs)
    entries = [build_entry(d, Path(args.cache_dir), buckets) for d in digests]
    entries.sort(key=lambda e: str(e["sha256"]))
    print(f"backfilled {len(entries)} entries")
    for entry in entries:
        print(
            f"  {entry['sha256'][:12]} chars={entry['characters']} "
            f"stage={entry['stage_id']} frames={entry['start_frame']}.."
            f"{entry['end_frame']}"
        )

    if args.write:
        manifest["qualified"] = entries
        manifest["description"] = (
            "Manifest-addressed 200 complete-match acceptance corpus for the "
            f"native GALE01 NTSC 1.02 + UCF 0.84 simulator. {len(entries)} entries backfilled "
            "from pinned-parser extraction cache (settings, UCF controllerFix, "
            "frozen-PS flag, items-off, contiguous -123..end frames, GameEnd); "
            "all pending full canonical oracle qualification."
        )
        with open(args.manifest, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BackfillError as error:
        print(f"ssbm_backfill_corpus=fail {error}", file=sys.stderr)
        raise SystemExit(2)
