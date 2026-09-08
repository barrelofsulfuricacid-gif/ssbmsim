#!/usr/bin/env python3
"""Preserve the corpus and add only identity-verified nonpassing candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ssbm_backfill_corpus import BackfillError, build_entry
from ssbm_corpus_coverage import audit_manifest
from ssbm_native_full_match import ReplayError, extract_replay, sha256, validate_replay
from ssbm_corpus_sweep import tool_identity

ROOT = Path(__file__).resolve().parents[1]


def preserve_provenance(entry: dict, previous: dict) -> dict:
    """Refresh validated replay facts without discarding archive provenance."""
    result = {**previous, **entry}
    for key in ("source", "source_provenance", "nonpassing_admission"):
        if key in previous:
            result[key] = previous[key]
    return result


def verified_failure(report: dict, digest: str, identity: dict) -> bool:
    """A failed admission or a stale report is not a simulator failure."""
    if (not isinstance(report, dict)
            or report.get("schema") != 2 or report.get("replay_sha256") != digest
            or report.get("complete_exact") is not False
            or report.get("comparison_scope") != "final-state"
            or report.get("configuration_error")
            or not isinstance(report.get("source_frames"), int)
            or report["source_frames"] <= 0
            or not isinstance(report.get("runner_exit_code"), int)):
        return False
    for key in ("runner_sha256", "asset_pack_sha256"):
        if report.get(key) != identity[key]:
            return False
    cached = report.get("sweep_cache_identity", {})
    if cached.get("comparison_scope") != "final-state":
        return False
    for key in identity:
        if cached.get(key) != identity[key]:
            return False
    return bool(report.get("first_divergence")) or report["runner_exit_code"] != 0


def select_entries(manifest: dict, candidates, admit, *, allow_partial=False) -> tuple[list[dict], list[dict]]:
    """Preserve membership and prioritize verified failures filling coverage gaps."""
    protected_entries = {entry["sha256"]: entry for entry in manifest["qualified"]}
    protected = set(protected_entries)
    if len(protected) != len(manifest["qualified"]):
        raise ValueError("existing corpus contains duplicate content")
    target = max(manifest["required_match_count"], len(protected))
    selected = {}
    rejected = []
    seen = set()
    for path, digest in candidates:
        if digest in seen:
            continue
        seen.add(digest)
        try:
            entry = admit(path, digest)
        except (ReplayError, BackfillError) as error:
            if digest in protected:
                raise ValueError(f"protected replay no longer admits: {digest}: {error}") from error
            rejected.append({"sha256": digest, "replay": str(path), "reason": str(error)})
            print(f"rejected {path.name}: {error}", flush=True)
            continue
        if entry["sha256"] != digest:
            raise ValueError("admission changed replay identity")
        selected[digest] = entry
        print(f"validated candidate {path.name}", flush=True)
    missing = protected - selected.keys()
    if missing:
        raise ValueError(f"candidate list omitted protected replays: {sorted(missing)}")
    kept = {digest: selected[digest] for digest in protected}
    remaining = {digest: entry for digest, entry in selected.items() if digest not in protected}
    needed_chars = set(map(int, manifest.get("required_characters", {})))
    needed_stages = set(map(int, manifest.get("required_stages", {})))

    def cover(entry):
        needed_chars.difference_update(entry.get("characters", []))
        needed_stages.discard(entry.get("stage_id"))

    for entry in kept.values():
        cover(entry)
    while remaining and (needed_chars or needed_stages):
        def gain(digest):
            entry = remaining[digest]
            return len(needed_chars.intersection(entry.get("characters", []))) + int(entry.get("stage_id") in needed_stages)
        digest = max(remaining, key=gain)
        if gain(digest) == 0:
            break
        kept[digest] = remaining.pop(digest)
        cover(kept[digest])
    # Leave room for still-missing coverage during acquisition. If an older
    # corpus already fills the count, never discard members to make room.
    reserved = max(len(needed_chars), len(needed_stages)) if allow_partial else 0
    capacity = max(len(kept), target - reserved)
    for digest, entry in remaining.items():
        if len(kept) >= capacity:
            break
        kept[digest] = entry
    selected = kept
    if len(selected) < target and not allow_partial:
        raise ValueError(f"only {len(selected)} admitted candidates for target {target}")
    return sorted(selected.values(), key=lambda entry: entry["sha256"]), rejected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "tools/ssbm_acceptance_corpus.json")
    parser.add_argument("--candidate-list", type=Path, required=True)
    parser.add_argument("--parser-prefix", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "build/ssbm-native/replay-cache")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--failure-reports", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--asset-pack", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-partial", action="store_true",
                        help="save confirmed additions while retaining the unchanged full target")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    protected_entries = {entry["sha256"]: entry for entry in manifest["qualified"]}
    protected = set(protected_entries)
    identity = tool_identity(args.runner, args.asset_pack, args.parser_prefix)
    paths = [Path(line.strip()).resolve() for line in args.candidate_list.read_text().splitlines() if line.strip()]

    def admit(path, digest):
        report = None
        if digest not in protected:
            report_path = args.failure_reports / f"{digest}.json"
            if not report_path.is_file():
                raise ReplayError("no tested nonpassing report")
            try:
                report = json.loads(report_path.read_text())
            except (OSError, ValueError) as error:
                raise ReplayError("failure report is not completely published yet") from error
            if not verified_failure(report, digest, identity):
                raise ReplayError("not a current-identity simulator failure")
        replay = extract_replay(path, args.parser_prefix, args.cache_dir, args.node)
        validate_replay(replay)
        entry = build_entry(digest, args.cache_dir, {}, bucket=path.parent.name)
        if digest in protected_entries:
            entry = preserve_provenance(entry, protected_entries[digest])
        entry["replay_path"] = path.relative_to(ROOT).as_posix()
        entry["result"] = "pending"
        entry["pending_reason"] = "admitted from replay inputs; full canonical oracle qualification pending"
        entry["ucf_evidence"] = "GameStart controllerFix=UCF; exact UCF 0.84 oracle configuration remains to be qualified"
        if report is not None:
            entry["nonpassing_admission"] = {
                "comparison_scope": report["comparison_scope"],
                "runner_sha256": identity["runner_sha256"],
                "asset_pack_sha256": identity["asset_pack_sha256"],
                "first_divergence": report["first_divergence"],
                "runner_exit_code": report["runner_exit_code"],
            }
        elif digest in protected_entries and "nonpassing_admission" in protected_entries[digest]:
            entry["nonpassing_admission"] = protected_entries[digest]["nonpassing_admission"]
        return entry

    entries, rejections = select_entries(manifest, ((p, sha256(p)) for p in paths), admit,
                                        allow_partial=args.allow_partial)
    manifest["qualified"] = entries  # Existing schema key; these are admissions, not passes.
    corpus_hash = hashlib.sha256(("\n".join(e["sha256"] for e in entries) + "\n").encode()).hexdigest()
    manifest["selection"] = {
        "policy": "preserve all existing entries; prioritize missing character/stage coverage among current-identity final-state failures, then fill remaining capacity in candidate order",
        "candidate_list_sha256": sha256(args.candidate_list),
        "corpus_sha256": corpus_hash,
        "frozen": len(entries) >= manifest["required_match_count"],
        "membership_append_only": True,
        "target_met": len(entries) >= manifest["required_match_count"],
    }
    manifest["description"] = f"{len(entries)} admitted matches toward the unchanged {manifest['required_match_count']}-match target. Membership is append-only; new additions require a verified simulator failure. Every entry is pending full canonical oracle qualification."
    coverage = audit_manifest(manifest)
    coverage_complete = not coverage["missing_characters"] and not coverage["missing_stages"]
    manifest["selection"]["target_met"] = len(entries) >= manifest["required_match_count"] and coverage_complete
    manifest["selection"]["frozen"] = manifest["selection"]["target_met"]
    if coverage["violations"] or coverage["unexpected_characters"] or (not args.allow_partial and not coverage_complete):
        raise ValueError(f"coverage gate failed: {coverage}")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"selection": manifest["selection"], "coverage": coverage,
                                      "rejections": rejections}, indent=2, sort_keys=True) + "\n")
    if args.write:
        args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"corpus-admission=pass count={len(entries)} sha256={corpus_hash} written={args.write}")


if __name__ == "__main__":
    main()
