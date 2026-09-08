#!/usr/bin/env python3
"""Pure manifest projections shared by SSBM capture and verification tools."""

from __future__ import annotations

import copy


def projected_manifest(
    manifest: dict[str, object],
    requested_case_ids: list[str],
    source_sha256: str,
    shard_count: int | None,
    warm_budget_seconds: float | None,
    cold_budget_seconds: float | None,
) -> dict[str, object]:
    """Return a capture-only projection in original case/shard order."""

    if not requested_case_ids:
        return manifest
    if len(requested_case_ids) != len(set(requested_case_ids)):
        raise ValueError("duplicate projected checkpoint case")

    case_specs = manifest.get("checkpoint_cases")
    projection_case_specs = manifest.get("projection_cases", [])
    checkpoint_pack = manifest.get("checkpoint_pack")
    if (
        not isinstance(case_specs, list)
        or not isinstance(projection_case_specs, list)
        or not isinstance(checkpoint_pack, dict)
    ):
        raise ValueError("checkpoint cases or pack are missing")
    selectable_case_specs = [*case_specs, *projection_case_specs]
    available_case_ids = [
        str(case["id"])
        for case in selectable_case_specs
        if isinstance(case, dict) and "id" in case
    ]
    if (
        len(available_case_ids) != len(selectable_case_specs)
        or len(available_case_ids) != len(set(available_case_ids))
    ):
        raise ValueError("checkpoint case ids are invalid")
    requested = set(requested_case_ids)
    missing = requested - set(available_case_ids)
    if missing:
        raise ValueError(
            "unknown checkpoint case(s): " + ", ".join(sorted(missing))
        )

    projected = copy.deepcopy(manifest)
    projected["checkpoint_cases"] = [
        copy.deepcopy(case)
        for case in selectable_case_specs
        if str(case["id"]) in requested
    ]
    projected.pop("projection_cases", None)
    projected_pack = projected["checkpoint_pack"]
    projected_pack.pop("expected_rows", None)
    if warm_budget_seconds is not None:
        projected_pack["warm_budget_seconds"] = warm_budget_seconds
        projected_pack["cold_budget_seconds"] = cold_budget_seconds
    selected_case_ids = [
        case_id for case_id in available_case_ids if case_id in requested
    ]
    capture_shards = projected_pack.get("capture_shards")
    if capture_shards is None:
        if shard_count is not None:
            raise ValueError("projected shard count requires capture_shards")
    elif shard_count is not None:
        if not 1 <= shard_count <= len(selected_case_ids):
            raise ValueError(
                "projected shard count must be within the selected case count"
            )
        projected_pack["capture_shards"] = [
            selected_case_ids[index::shard_count] for index in range(shard_count)
        ]
    else:
        if not isinstance(capture_shards, list):
            raise ValueError("checkpoint capture_shards must be a list")
        projected_pack["capture_shards"] = [
            [case_id for case_id in shard if str(case_id) in requested]
            for shard in capture_shards
        ]
        projected_pack["capture_shards"] = [
            shard for shard in projected_pack["capture_shards"] if shard
        ]
    capture_plan = projected_pack.get("capture_plan")
    if not isinstance(capture_plan, dict):
        raise ValueError("checkpoint capture plan is missing")
    case_fields = [
        key
        for key, value in capture_plan.items()
        if key.endswith("_cases") and isinstance(value, list)
    ]
    if len(case_fields) > 1:
        raise ValueError("checkpoint capture plan contains multiple case lists")
    if case_fields:
        case_field = case_fields[0]
        capture_plan[case_field] = [
            case
            for case in capture_plan[case_field]
            if isinstance(case, dict) and str(case.get("id")) in requested
        ]
    projected.pop("selection", None)
    projected.pop("stored_oracle", None)
    projected["capture_projection"] = {
        "schema": 1,
        "source_manifest_sha256": source_sha256,
        "case_ids": selected_case_ids,
        **(
            {"shards": len(projected_pack["capture_shards"])}
            if "capture_shards" in projected_pack
            else {}
        ),
        **(
            {
                "warm_budget_seconds": warm_budget_seconds,
                "cold_budget_seconds": cold_budget_seconds,
            }
            if warm_budget_seconds is not None
            else {}
        ),
    }
    return projected
