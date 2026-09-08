#!/usr/bin/env python3
"""Summarize sweep reports: pass count, divergence-field clusters, examples."""

import glob
import json
import sys

out_dir = sys.argv[1]
passes = []
fields: dict[str, int] = {}
examples: dict[str, list] = {}
for path in glob.glob(f"{out_dir}/*.json"):
    report = json.load(open(path))
    if report.get("complete_exact") is True:
        passes.append(report["replay_sha256"][:12])
    else:
        div = report.get("first_divergence") or {}
        if div.get("field"):
            key = div["field"]
            detail = (
                report["replay_sha256"][:12],
                div.get("frame"),
                div.get("player_port"),
                div.get("fighter_type"),
                report.get("stage_id"),
                report.get("character_ids"),
                {k: v for k, v in div.items()
                 if k not in ("frame", "player_port", "fighter_type", "field")},
            )
        else:
            key = "CONFIG:" + str(report.get("configuration_error", "?"))[:70]
            detail = (report.get("replay", "?")[-40:], None, None, None, None, None, {})
        fields[key] = fields.get(key, 0) + 1
        examples.setdefault(key, []).append(detail)

print(f"reports={len(passes) + sum(fields.values())} passes={len(passes)}")
for key in sorted(fields, key=lambda k: -fields[k]):
    print(f"--- {key}: {fields[key]}")
    for row in examples[key][:6]:
        print("   ", row)
print("PASS:", sorted(passes))
