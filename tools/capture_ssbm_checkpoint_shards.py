#!/usr/bin/env python3
"""Fork preloaded checkpoint-capture workers and merge their traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

import capture_ssbm_movement
import merge_ssbm_checkpoint_captures
from ssbm_checkpoint_manifest import projected_manifest


MEMORY_PROBE_CHOICES = (
    "none",
    "input",
    "surface",
    "input-surface",
    "hitbox",
    "hurtbox",
)


def memory_probe_arguments(memory_probe: str) -> tuple[str, ...]:
    if memory_probe == "none":
        return ()
    if memory_probe == "input-surface":
        return ("--memory-probe-input", "--memory-probe-surface")
    if memory_probe not in MEMORY_PROBE_CHOICES:
        raise ValueError(f"unknown memory probe: {memory_probe}")
    return (f"--memory-probe-{memory_probe}",)


def run_worker(argv: list[str]) -> None:
    status = 1
    try:
        status = capture_ssbm_movement.main(argv)
    except BaseException:  # Child must report the original capture failure.
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(status)


def main() -> int:
    warm_started_ns = time.time_ns()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dolphin", required=True, type=Path)
    parser.add_argument("--oracle-release-artifact", required=True, type=Path)
    parser.add_argument("--iso", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-port", type=int, default=51441)
    parser.add_argument("--started-ns", required=True, type=int)
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="capture only this manifest case; repeat to select a projection",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        help="repartition a selected case projection across this many workers",
    )
    parser.add_argument(
        "--memory-probe",
        choices=MEMORY_PROBE_CHOICES,
        default=None,
        help=(
            "live-memory observation family recorded by every shard "
            "(defaults to none for acquisition and surface otherwise)"
        ),
    )
    parser.add_argument(
        "--disable-fast-forward",
        action="store_true",
        help="keep ExiAI input/checkpoints but evaluate display-side bones",
    )
    parser.add_argument(
        "--checkpoint-no-batch-inputs",
        action="store_true",
        help="sample every response frame for collision-memory geometry",
    )
    parser.add_argument(
        "--projection-warm-budget-seconds",
        type=float,
        help="wall budget for a selected observation-family projection",
    )
    parser.add_argument(
        "--projection-cold-budget-seconds",
        type=float,
        help="cold wall budget for a selected observation-family projection",
    )
    args = parser.parse_args()
    if args.shard_count is not None and not args.case:
        parser.error("--shard-count requires at least one --case")
    if (args.projection_warm_budget_seconds is None) != (
        args.projection_cold_budget_seconds is None
    ):
        parser.error("projection warm and cold budgets must be provided together")
    if args.projection_warm_budget_seconds is not None and (
        not args.case
        or args.projection_warm_budget_seconds <= 0.0
        or args.projection_cold_budget_seconds
        < args.projection_warm_budget_seconds
    ):
        parser.error("projection budgets require cases and cold >= warm > 0")

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    try:
        manifest = projected_manifest(
            manifest,
            [str(case_id) for case_id in args.case],
            hashlib.sha256(manifest_bytes).hexdigest(),
            args.shard_count,
            args.projection_warm_budget_seconds,
            args.projection_cold_budget_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    checkpoint_pack = manifest.get("checkpoint_pack")
    if not isinstance(checkpoint_pack, dict):
        raise SystemExit("checkpoint_pack is missing")
    shards = checkpoint_pack.get("capture_shards")
    warm_budget = checkpoint_pack.get("warm_budget_seconds")
    cold_budget = checkpoint_pack.get("cold_budget_seconds", warm_budget)
    capture_route = checkpoint_pack.get("capture_route", "damage-hit")
    expected_cases = [str(case["id"]) for case in manifest["checkpoint_cases"]]
    if (
        not isinstance(shards, list)
        or not shards
        or any(not isinstance(shard, list) or not shard for shard in shards)
        or not isinstance(warm_budget, (int, float))
        or isinstance(warm_budget, bool)
        or float(warm_budget) <= 0.0
        or not isinstance(cold_budget, (int, float))
        or isinstance(cold_budget, bool)
        or float(cold_budget) < float(warm_budget)
        or capture_route not in (
            "damage-hit",
            "common-hurt-geometry",
            "special-acquisition",
        )
    ):
        raise SystemExit("checkpoint capture shards or wall budgets are invalid")
    memory_probe = args.memory_probe or (
        "none" if capture_route == "special-acquisition" else "surface"
    )
    captured_cases = [str(case) for shard in shards for case in shard]
    if len(captured_cases) != len(set(captured_cases)) or set(captured_cases) != set(
        expected_cases
    ):
        raise SystemExit("checkpoint capture_shards do not partition the cases")
    if not 1024 <= args.base_port <= 65535 - len(shards):
        raise SystemExit("checkpoint base port is out of range")

    dolphin = args.dolphin.resolve()
    release_artifact = args.oracle_release_artifact.resolve()
    iso = args.iso.resolve()
    source_manifest_path = args.manifest.resolve()
    for required in (dolphin, release_artifact, iso, source_manifest_path):
        if not required.is_file():
            raise SystemExit(f"missing required oracle input: {required}")

    worker_links: list[Path] = []
    child_pids: list[int] = []
    workers_started_ns = 0
    workers_finished_ns = 0
    merge_finished_ns = 0
    with tempfile.TemporaryDirectory(prefix="pf-ssbm-checkpoint-") as temporary:
        manifest_path = Path(temporary) / "capture-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shard_outputs = [
            Path(temporary) / f"shard-{index}.json"
            for index in range(len(shards))
        ]
        try:
            for index in range(len(shards)):
                worker_link = dolphin.with_name(
                    f"dpf{os.getpid() % 100000:05d}s{index:02d}"
                )
                os.link(dolphin, worker_link)
                worker_links.append(worker_link)

            # Every process-specific executable is a hardlink to this exact
            # inode. Seed its content hash once after link creation so child
            # provenance reads reuse the matching fingerprint instead of six
            # workers hashing the same launcher concurrently.
            capture_ssbm_movement.cached_sha256(dolphin)
            capture_ssbm_movement.cached_sha256(release_artifact)
            capture_ssbm_movement.cached_sha256(iso)
            capture_ssbm_movement.preload_hardlinked_dolphin_version(dolphin)

            for index, shard in enumerate(shards):
                worker_argv = [
                    "--dolphin",
                    str(worker_links[index]),
                    "--oracle-release-artifact",
                    str(release_artifact),
                    "--iso",
                    str(iso),
                    "--output",
                    str(shard_outputs[index]),
                    "--slippi-port",
                    str(args.base_port + index),
                    {
                        "common-hurt-geometry": "--common-hurt-geometry-only",
                        "damage-hit": "--damage-hit-only",
                        "special-acquisition": "--special-acquisition-only",
                    }[capture_route],
                    "--oracle-exiai",
                    "--oracle-checkpoint-pack",
                    "--oracle-coverage-manifest",
                    str(manifest_path),
                ]
                worker_argv.extend(memory_probe_arguments(memory_probe))
                if args.disable_fast_forward:
                    worker_argv.append("--oracle-exiai-no-fast-forward")
                if args.checkpoint_no_batch_inputs:
                    worker_argv.append("--oracle-checkpoint-no-batch-inputs")
                for case_id in shard:
                    worker_argv.extend(("--oracle-case", str(case_id)))
                child_pid = os.fork()
                if child_pid == 0:
                    run_worker(worker_argv)
                child_pids.append(child_pid)
            workers_started_ns = time.time_ns()

            failed_children: list[int] = []
            for child_pid in child_pids:
                _, wait_status = os.waitpid(child_pid, 0)
                if not os.WIFEXITED(wait_status) or os.WEXITSTATUS(wait_status) != 0:
                    failed_children.append(child_pid)
            if failed_children:
                raise SystemExit(
                    "parallel checkpoint capture failed: "
                    + ",".join(map(str, failed_children))
                )
            workers_finished_ns = time.time_ns()

            merge_ssbm_checkpoint_captures.main(
                [
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(args.output),
                    *map(str, shard_outputs),
                ]
            )
            merge_finished_ns = time.time_ns()
        finally:
            for worker_link in worker_links:
                worker_link.unlink(missing_ok=True)

    finished_ns = time.time_ns()
    warm_seconds = (finished_ns - warm_started_ns) / 1e9
    cold_seconds = (finished_ns - args.started_ns) / 1e9
    warm_budget_seconds = float(warm_budget)
    cold_budget_seconds = float(cold_budget)
    if warm_seconds > warm_budget_seconds:
        raise SystemExit(
            "checkpoint pack exceeded "
            f"{warm_budget_seconds:.1f}-second warm wall budget: "
            f"{warm_seconds:.6f}"
        )
    if cold_seconds > cold_budget_seconds:
        raise SystemExit(
            "checkpoint pack exceeded "
            f"{cold_budget_seconds:.1f}-second cold wall budget: "
            f"{cold_seconds:.6f}"
        )
    print(
        "ssbm-checkpoint-parent-time "
        f"setup_seconds={(workers_started_ns - warm_started_ns) / 1e9:.6f} "
        f"workers_seconds={(workers_finished_ns - workers_started_ns) / 1e9:.6f} "
        f"merge_seconds={(merge_finished_ns - workers_finished_ns) / 1e9:.6f} "
        f"cleanup_seconds={(finished_ns - merge_finished_ns) / 1e9:.6f}"
    )
    print(
        "ssbm-checkpoint-shards=pass "
        f"shards={len(shards)} warm_seconds={warm_seconds:.6f} "
        f"cold_seconds={cold_seconds:.6f} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
