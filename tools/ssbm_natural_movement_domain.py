#!/usr/bin/env python3
"""Shared live-capture projection for native CSV movement domains."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from compare_ssbm_movement import (
    CHARACTER_AERIAL_LANDING_ACTIONS,
    expected_action_state,
    expected_action_ticks,
    native_input_line,
)
from generate_ssbm_stored_trace_oracle import (
    expand_case_samples,
    native_csv_input_line,
)
from ssbm_live_trace import (
    common_movement_source_sample,
    selected_trace_fields,
)


class NaturalMovementDomainError(ValueError):
    """A live capture does not satisfy its checked-in domain contract."""


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_capture(
    path: Path,
    expected_sha256: str,
    live_source: dict[str, Any],
    *,
    require_zero_damage: bool = True,
) -> dict[str, Any]:
    actual_sha256 = raw_sha256(path)
    if actual_sha256 != expected_sha256:
        raise NaturalMovementDomainError(
            f"capture-sha256 path={path} expected={expected_sha256} "
            f"actual={actual_sha256}"
        )
    capture = json.loads(path.read_text(encoding="utf-8"))
    execution = capture.get("oracle_execution")
    gameplay_policy = capture.get("oracle_gameplay_policy")
    expected_policy = live_source.get("oracle_gameplay_policy")
    disc = capture.get("disc")
    rows = capture.get("rows")
    if (
        capture.get("schema") != live_source.get("capture_schema", 11)
        or capture.get("oracle")
        != live_source.get(
            "oracle",
            "SSBM GALE01 NTSC-U revision 2 via Dolphin/Slippi",
        )
        or capture.get("stage") != live_source.get("stage", "BATTLEFIELD")
        or capture.get("fighter") != live_source.get("fighter", "CPTFALCON")
        or capture.get("opponent") != live_source.get("opponent", "FOX")
        or capture.get("dolphin_version") != live_source.get("dolphin_version")
        or capture.get("libmelee_version") != live_source.get("libmelee_version")
        or not isinstance(execution, dict)
        or execution.get("mode")
        != live_source.get(
            "execution_mode", "exiai-headless-null-fast-forward"
        )
        or execution.get("release_artifact_sha256")
        != live_source.get("release_artifact_sha256")
        or execution.get("launcher_sha256")
        != live_source.get("launcher_sha256")
        or not isinstance(disc, dict)
        or disc.get("game_id") != "GALE01"
        or disc.get("revision") != 2
        or disc.get("sha256") != live_source.get("disc_sha256")
        or not isinstance(rows, list)
        or len(rows) != live_source.get("row_count")
    ):
        raise NaturalMovementDomainError(f"capture-provenance path={path}")
    if expected_policy is not None:
        if (
            not isinstance(expected_policy, dict)
            or not isinstance(gameplay_policy, dict)
            or gameplay_policy.get("runtime_verified") is not True
            or any(
                gameplay_policy.get(key) != value
                for key, value in expected_policy.items()
            )
        ):
            raise NaturalMovementDomainError(
                f"capture-gameplay-policy path={path}"
            )
    if require_zero_damage and any(
        row.get("damage_percent") != 0.0 for row in rows
    ):
        raise NaturalMovementDomainError(f"capture-damage-contamination path={path}")
    return capture


def _case_rows(
    rows: list[dict[str, Any]],
    case: dict[str, Any],
) -> list[dict[str, Any]]:
    prefix = case.get("source_label_prefix")
    if prefix is None:
        return rows
    if not isinstance(prefix, str) or not prefix:
        raise NaturalMovementDomainError(
            f"source-label-prefix case={case.get('id')}"
        )
    return [
        row
        for row in rows
        if str(row.get("label", "")).startswith(prefix)
    ]


def _source_action_ticks(
    rows: list[dict[str, Any]],
    sample_index: int,
) -> int | None:
    row = rows[sample_index]
    action = str(row["action"])
    action_ticks = expected_action_ticks(action, float(row["action_frame"]))
    if action not in CHARACTER_AERIAL_LANDING_ACTIONS:
        return action_ticks
    elapsed = 0
    previous_index = sample_index - 1
    while (
        previous_index >= 0
        and str(rows[previous_index].get("action", "")) == action
    ):
        elapsed += 1
        previous_index -= 1
    return elapsed


def _action_mapping(
    raw: object,
    context: str,
) -> dict[str, tuple[int, int | None]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise NaturalMovementDomainError(f"action-mapping context={context}")
    result: dict[str, tuple[int, int | None]] = {}
    for action, config in raw.items():
        if (
            not isinstance(action, str)
            or not action
            or not isinstance(config, dict)
            or set(config) != {"action_state", "action_tick_offset"}
        ):
            raise NaturalMovementDomainError(
                f"action-mapping context={context} action={action!r}"
            )
        action_state = config["action_state"]
        tick_offset = config["action_tick_offset"]
        if (
            not isinstance(action_state, int)
            or isinstance(action_state, bool)
            or not 0 <= action_state <= 65535
            or (
                tick_offset is not None
                and (
                    not isinstance(tick_offset, int)
                    or isinstance(tick_offset, bool)
                    or not -4096 <= tick_offset <= 4096
                )
            )
        ):
            raise NaturalMovementDomainError(
                f"action-mapping context={context} action={action!r}"
            )
        result[action] = (action_state, tick_offset)
    return result


def canonical_capture(
    capture: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    all_rows = capture["rows"]
    stored = coverage["stored_oracle"]
    cases = stored.get("cases")
    fields = stored.get("serialized_fields")
    if not isinstance(cases, list) or not cases or not isinstance(fields, list):
        raise NaturalMovementDomainError("stored-case-schema")
    source_prefixes = [
        (str(case.get("id")), case.get("source_label_prefix"))
        for case in cases
        if isinstance(case, dict)
        and isinstance(case.get("source_label_prefix"), str)
    ]
    for index, (case_id, prefix) in enumerate(source_prefixes):
        for other_id, other_prefix in source_prefixes[index + 1 :]:
            if prefix.startswith(other_prefix) or other_prefix.startswith(prefix):
                raise NaturalMovementDomainError(
                    "source-label-prefix-overlap "
                    f"cases={case_id},{other_id}"
                )
    domain_action_mapping = _action_mapping(
        stored.get("action_mapping"),
        "stored-oracle",
    )

    canonical_cases: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise NaturalMovementDomainError("stored-case-schema")
        case_id = str(case.get("id"))
        case_fields = case.get("serialized_fields", fields)
        if not isinstance(case_fields, list) or not case_fields:
            raise NaturalMovementDomainError(
                f"serialized-fields case={case_id}"
            )
        action_mapping = {
            **domain_action_mapping,
            **_action_mapping(
                case.get("action_mapping"),
                f"case={case_id}",
            ),
        }
        rows = _case_rows(all_rows, case)
        if len(rows) != case.get("sample_count"):
            raise NaturalMovementDomainError(
                f"sample-count case={case_id} expected={case.get('sample_count')} "
                f"actual={len(rows)}"
            )
        inputs = expand_case_samples(case, case_id, len(rows), "inputs")
        raw_main_presence = [
            isinstance(sample.get("lanes"), list)
            and len(sample["lanes"]) == 2
            and isinstance(sample["lanes"][0], dict)
            and "raw_main" in sample["lanes"][0]
            for sample in inputs
        ]
        if any(raw_main_presence) and not all(raw_main_presence):
            raise NaturalMovementDomainError(
                f"raw-main-partial case={case_id}"
            )
        raw_c_presence = [
            isinstance(sample.get("lanes"), list)
            and len(sample["lanes"]) == 2
            and isinstance(sample["lanes"][0], dict)
            and "raw_c" in sample["lanes"][0]
            for sample in inputs
        ]
        if any(raw_c_presence) and not all(raw_c_presence):
            raise NaturalMovementDomainError(f"raw-c-partial case={case_id}")
        if any(raw_c_presence) and not all(raw_main_presence):
            raise NaturalMovementDomainError(
                f"raw-c-without-main case={case_id}"
            )
        include_raw_main = all(raw_main_presence)
        include_raw_c = all(raw_c_presence)
        if include_raw_c:
            input_memory_probe = capture.get("input_memory_probe")
            if (
                not isinstance(input_memory_probe, dict)
                or input_memory_probe.get("schema") != 2
            ):
                raise NaturalMovementDomainError(
                    f"raw-c-probe-schema case={case_id}"
                )
        stored_input_lines = [
            native_csv_input_line(
                sample,
                case_id,
                sample_index,
                include_raw_main=include_raw_main,
                include_raw_c=include_raw_c,
            )
            for sample_index, sample in enumerate(inputs)
        ]
        live_input_lines = [
            native_input_line(
                row,
                include_raw_main=include_raw_main,
                include_raw_c=include_raw_c,
            )
            for row in rows
        ]
        if stored_input_lines != live_input_lines:
            mismatch = next(
                index
                for index, (stored_line, live_line) in enumerate(
                    zip(stored_input_lines, live_input_lines, strict=True)
                )
                if stored_line != live_line
            )
            raise NaturalMovementDomainError(
                f"input case={case_id} sample={mismatch}"
            )

        exclusions = case.get("field_exclusions", {})
        if not isinstance(exclusions, dict):
            raise NaturalMovementDomainError(
                f"field-exclusions case={case_id}"
            )
        origin_y = float(rows[0]["position_y"])
        samples: list[dict[str, int]] = []
        for sample_index, row in enumerate(rows):
            action = str(row["action"])
            action_frame = float(row["action_frame"])
            mapped_action = action_mapping.get(action)
            if mapped_action is None:
                action_state = expected_action_state(action, action_frame)
                action_ticks = _source_action_ticks(rows, sample_index)
            else:
                action_state, tick_offset = mapped_action
                action_ticks = (
                    None
                    if tick_offset is None
                    else round(action_frame) + tick_offset
                )
            selected_fields = selected_trace_fields(
                case_fields,
                exclusions,
                sample_index,
            )
            if not isinstance(action_state, int):
                raise NaturalMovementDomainError(
                    f"action-state case={case_id} sample={sample_index}"
                )
            if action_ticks is None and "action_ticks" in selected_fields:
                raise NaturalMovementDomainError(
                    f"action-tick-mask case={case_id} sample={sample_index}"
                )
            values = common_movement_source_sample(
                row,
                action_state=action_state,
                action_ticks=action_ticks if action_ticks is not None else 0,
                origin_y=origin_y,
            )
            missing_fields = [
                field for field in selected_fields if field not in values
            ]
            if missing_fields:
                raise NaturalMovementDomainError(
                    f"source-field case={case_id} sample={sample_index} "
                    f"missing={','.join(missing_fields)}"
                )
            samples.append(
                {field: values[field] for field in selected_fields}
            )
        canonical_cases.append({"id": case_id, "samples": samples})
    return {
        "schema": 1,
        "domain": str(coverage["domain"]),
        "cases": canonical_cases,
    }
