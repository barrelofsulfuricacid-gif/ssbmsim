#!/usr/bin/env python3
"""Screen complete .slp replays by final state in parallel by default.

Each replay runs tools/ssbm_native_full_match.py with the pinned runner,
asset pack, parser prefix, and hash-keyed extraction cache. Per-replay
schema-2 reports name the comparison scope and land keyed by replay sha256, plus
a summary.json clustering failures by first-divergence field so one repair
can target a whole class (per the roadmap divergence-repair policy).

Use --comparison-scope all-frames for per-frame recorded-field diagnostics.
Neither scope is full canonical instrumented-oracle qualification.
Fail-closed: a replay counts as pass only with complete_exact:true for its scope.
Everything else (admission rejection, crash, divergence) is a classified
non-pass, never silently dropped.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ssbm_native_full_match import extraction_cache_path, endpoint_preparation_identity, extractor_identity

ROOT = Path(__file__).resolve().parent.parent
FULL_MATCH = ROOT / "tools" / "ssbm_native_full_match.py"


def tool_identity(runner: Path, pack: Path, parser_prefix: Path | None = None) -> dict[str, str]:
    identity = {
        "runner_sha256": sha256(runner),
        "asset_pack_sha256": sha256(pack),
        "comparator_sha256": sha256(FULL_MATCH),
        "extractor_sha256": extractor_identity(),
        "sweep_sha256": sha256(Path(__file__)),
    }
    if parser_prefix is not None:
        identity['parser_sha256'] = endpoint_preparation_identity(parser_prefix)['parser_sha256']
    return identity


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_one(
    replay: Path,
    runner: Path,
    pack: Path,
    parser_prefix: str,
    node: str,
    cache_dir: Path,
    out_dir: Path,
    identity: dict[str, str] | None = None,
    comparison_scope: str = "final-state",
    arithmetic_profile: int = 0,
) -> dict:
    try:
        digest = sha256(replay)
    except OSError as error:
        return {"replay": str(replay), "status": "unreadable", "error": str(error)}
    report_path = out_dir / f"{digest}.json"
    identity = identity or tool_identity(runner, pack, Path(parser_prefix))
    extraction_path = extraction_cache_path(cache_dir, digest, comparison_scope)
    extraction_digest = sha256(extraction_path) if extraction_path.is_file() else None
    prepared_cache_is_stale = False
    if extraction_digest is not None:
        try:
            previous = json.loads(extraction_path.read_text(encoding='utf-8'))
            headers = [('extractor_sha256', 'extractor_sha256')]
            if comparison_scope == 'final-state':
                headers += [('preparer_sha256', 'comparator_sha256'),
                            ('parser_sha256', 'parser_sha256')]
            prepared_cache_is_stale = isinstance(previous, dict) and any(
                previous.get(header) != identity.get(tool) for header, tool in headers)
        except (OSError, ValueError):
            pass
    cache_identity = {**identity, "extracted_replay_sha256": extraction_digest,
                      "comparison_scope": comparison_scope, "arithmetic_profile": arithmetic_profile}
    if report_path.is_file():
        try:
            cached = json.loads(report_path.read_text(encoding="utf-8"))
            if (isinstance(cached, dict)
                    and not prepared_cache_is_stale
                    and extraction_digest is not None
                    and cached.get("schema") == 2
                    and cached.get("replay_sha256") == digest
                    and cached.get("arithmetic_profile") == arithmetic_profile
                    and cached.get("comparison_scope") == comparison_scope
                    and cached.get("runner_sha256") == identity["runner_sha256"]
                    and cached.get("asset_pack_sha256") == identity["asset_pack_sha256"]
                    and cached.get("sweep_cache_identity") == cache_identity):
                return {"replay": str(replay), "status": "cached", "report": cached}
        except (OSError, ValueError):
            pass
        # A failed child must never leave an older successful report consumable.
        report_path.unlink()
    proc = subprocess.run(
        [
            sys.executable,
            str(FULL_MATCH),
            str(replay),
            "--parser-prefix",
            parser_prefix,
            "--node",
            node,
            "--runner",
            str(runner),
            "--asset-pack",
            str(pack),
            "--cache-dir",
            str(cache_dir),
            "--report",
            str(report_path),
            "--comparison-scope",
            comparison_scope,
            "--arithmetic-profile", str(arithmetic_profile),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "replay": str(replay),
            "status": "no-report",
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    if (not isinstance(report, dict)
            or report.get("replay_sha256") != digest
            or report.get("arithmetic_profile") != arithmetic_profile
            or report.get("comparison_scope") != comparison_scope
            or report.get("runner_sha256") != identity["runner_sha256"]
            or report.get("asset_pack_sha256") != identity["asset_pack_sha256"]):
        rejected = dict(report) if isinstance(report, dict) else {}
        rejected["complete_exact"] = False
        rejected["identity_error"] = "report identity missing or changed"
        return {"replay": str(replay), "status": "unverified-report", "report": rejected}
    if proc.returncode != 0 and report.get("complete_exact") is True:
        report["complete_exact"] = False
        report["configuration_error"] = "comparison process failed despite pass report"
    current_extraction = sha256(extraction_path) if extraction_path.is_file() else None
    if (not prepared_cache_is_stale and extraction_digest is not None
            and current_extraction != extraction_digest):
        report["complete_exact"] = False
        report["configuration_error"] = "extracted replay changed during comparison"
    report["sweep_cache_identity"] = {
        **identity, "extracted_replay_sha256": current_extraction,
        "comparison_scope": comparison_scope,
        "arithmetic_profile": arithmetic_profile,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return {"replay": str(replay), "status": "ran", "report": report}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-list", type=Path, required=True,
                        help="text file with one .slp path per line")
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--asset-pack", type=Path, required=True)
    parser.add_argument("--parser-prefix", required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--cache-dir", type=Path,
                        default=ROOT / "build" / "ssbm-native" / "replay-cache")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--comparison-scope", choices=("final-state", "all-frames"),
                        default="final-state")
    parser.add_argument("--arithmetic-profile", type=int, choices=(0, 1), default=0)
    args = parser.parse_args()

    replays = [
        Path(line.strip())
        for line in args.replay_list.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    # An interrupted or failed run must not expose a summary from an older run.
    (args.out_dir / "summary.json").unlink(missing_ok=True)
    identity = tool_identity(args.runner, args.asset_pack, Path(args.parser_prefix))
    replay_hashes = [sha256(replay) for replay in replays]
    if len(set(replay_hashes)) != len(replay_hashes):
        raise ValueError("duplicate replay content in sweep manifest")
    corpus_digest = hashlib.sha256(
        ("\n".join(sorted(replay_hashes)) + "\n").encode("ascii")
    ).hexdigest()

    passes: list[str] = []
    nonpass: list[dict] = []
    field_counter: collections.Counter = collections.Counter()
    config_counter: collections.Counter = collections.Counter()

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(
                run_one, replay, args.runner, args.asset_pack,
                args.parser_prefix, args.node, args.cache_dir, args.out_dir, identity,
                args.comparison_scope, args.arithmetic_profile,
            ): replay
            for replay in replays
        }
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            report = result.get("report") or {}
            if report.get("complete_exact") is True:
                passes.append(result["replay"])
            else:
                div = report.get("first_divergence") or {}
                field_counter[f"{div.get('field','?')}"] += 1
                config_counter[
                    f"stage={report.get('stage_id','?')} "
                    f"chars={report.get('character_ids','?')} "
                    f"frame={div.get('frame','?')} "
                    f"field={div.get('field', report.get('configuration_error','error')[:60] if report.get('configuration_error') else '?')}"
                ] += 1
                nonpass.append(
                    {"replay": result["replay"], "status": result["status"],
                     "report": report}
                )
            if done % 25 == 0 or done == len(replays):
                print(f"sweep: {done}/{len(replays)} passes={len(passes)}", flush=True)

    if tool_identity(args.runner, args.asset_pack, Path(args.parser_prefix)) != identity:
        raise RuntimeError("sweep inputs changed during execution; no summary published")
    summary = {
        "claim_boundary": "recorded-slippi-fields-only-not-full-oracle-qualification",
        "comparison_scope": args.comparison_scope,
        "arithmetic_profile": args.arithmetic_profile,
        "replay_manifest_sha256": corpus_digest,
        "total": len(replays),
        "passes": len(passes),
        "nonpasses": len(nonpass),
        "pass_replays": sorted(passes),
        "first_divergence_fields": dict(field_counter),
        "top_failure_configs": config_counter.most_common(30),
        **identity,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
