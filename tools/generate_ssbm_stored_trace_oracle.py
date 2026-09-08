#!/usr/bin/env python3
"""Generate a binding for a manifest-owned stored SSBM trace domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


BUTTONS = {
    "attack": "PF_INPUT_BUTTON_ATTACK",
    "strong_attack": "PF_INPUT_BUTTON_STRONG_ATTACK",
    "special": "PF_INPUT_BUTTON_SPECIAL",
    "jump": "PF_INPUT_BUTTON_JUMP",
    "taunt": "PF_INPUT_BUTTON_TAUNT",
}

BUTTON_MASKS = {
    "jump": 1 << 0,
    "attack": 1 << 1,
    "strong_attack": 1 << 2,
    "special": 1 << 3,
    "taunt": 1 << 4,
}

NATIVE_CSV_TRACE_FIELDS = {
    "action_state",
    "action_ticks",
    "facing",
    "tilt_x_age",
    "tilt_y_age",
    "ucf_tilt_x_age",
    "ucf_tilt_y_age",
    "ucf_pad_buffer_count",
    "effective_main_x_q15",
    "effective_main_y_q15",
    "effective_c_x_q15",
    "effective_c_y_q15",
    "grounded",
    "support",
    "surface_normal_source_x_f32",
    "surface_normal_source_y_f32",
    "position_x_f32_from_origin",
    "position_y_f32_from_origin",
    "velocity_x_f32",
    "velocity_y_f32",
    "shield_health_f32",
    "shield_strength",
    "hitlag_ticks",
    "tumble",
    "invulnerable",
    "opponent_action_state",
    "opponent_action_ticks",
    "opponent_hitlag_ticks",
    "opponent_hitstun_ticks",
    "opponent_facing",
    "opponent_grounded",
    "opponent_position_x_f32_from_origin",
    "opponent_position_y_f32_from_origin",
    "opponent_velocity_x_f32",
    "opponent_velocity_y_f32",
    "opponent_damage_f32",
}

TRACE_FIELDS = {
    "position_x": "PF_SSBM_TRACE_POSITION_X",
    "position_y": "PF_SSBM_TRACE_POSITION_Y",
    "self_velocity_x": "PF_SSBM_TRACE_SELF_VELOCITY_X",
    "self_velocity_y": "PF_SSBM_TRACE_SELF_VELOCITY_Y",
    "knockback_velocity_x": "PF_SSBM_TRACE_KNOCKBACK_VELOCITY_X",
    "knockback_velocity_y": "PF_SSBM_TRACE_KNOCKBACK_VELOCITY_Y",
    "ground_knockback_velocity": "PF_SSBM_TRACE_GROUND_KNOCKBACK_VELOCITY",
    "damage": "PF_SSBM_TRACE_DAMAGE",
    "action_ticks": "PF_SSBM_TRACE_ACTION_TICKS",
    "hitlag_ticks": "PF_SSBM_TRACE_HITLAG_TICKS",
    "hitstun_ticks": "PF_SSBM_TRACE_HITSTUN_TICKS",
    "action_state": "PF_SSBM_TRACE_ACTION_STATE",
    "hitlag_resume_action": "PF_SSBM_TRACE_HITLAG_RESUME_ACTION",
    "grounded": "PF_SSBM_TRACE_GROUNDED",
    "tumble": "PF_SSBM_TRACE_TUMBLE",
    "invulnerable": "PF_SSBM_TRACE_INVULNERABLE",
    "tech_direction": "PF_SSBM_TRACE_TECH_DIRECTION",
    "prone_orientation": "PF_SSBM_TRACE_PRONE_ORIENTATION",
    "facing": "PF_SSBM_TRACE_FACING",
    "ledge_regrab_lockout": "PF_SSBM_TRACE_LEDGE_REGRAB_LOCKOUT",
}


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", value
    ) is None:
        raise ValueError(f"{field} must be a C identifier")
    return value


def digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def axis(value: Any, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not -32767 <= value <= 32767
    ):
        raise ValueError(f"{field} must be a signed controller axis")
    return value


def raw_axis(value: Any, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not -128 <= value <= 127
    ):
        raise ValueError(f"{field} must be a signed raw controller byte")
    return value


def unsigned_16(value: Any, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 65535
    ):
        raise ValueError(f"{field} must be an unsigned 16-bit integer")
    return value


def buttons(value: Any, field: str) -> str:
    if value is None:
        return "UINT64_C(0)"
    if not isinstance(value, list) or any(name not in BUTTONS for name in value):
        raise ValueError(f"{field} contains an unsupported button")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} contains duplicate buttons")
    return " | ".join(BUTTONS[name] for name in value) or "UINT64_C(0)"


def button_mask(value: Any, field: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, list) or any(name not in BUTTON_MASKS for name in value):
        raise ValueError(f"{field} contains an unsupported button")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} contains duplicate buttons")
    return sum(BUTTON_MASKS[name] for name in value)


def stick(
    value: Any,
    field: str,
    *,
    invert_y: bool,
) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must contain two controller axes")
    x = axis(value[0], f"{field}[0]")
    y = axis(value[1], f"{field}[1]")
    return x, -y if invert_y else y


def expand_case_samples(
    case: dict[str, Any],
    case_id: str,
    sample_count: int,
    sample_key: str,
) -> list[dict[str, Any]]:
    samples = case.get(sample_key)
    if samples is not None or sample_key != "inputs":
        if not isinstance(samples, list) or len(samples) != sample_count:
            raise ValueError(f"invalid trace samples for {case_id!r}")
        return samples
    raw_phases = case.get("input_phases")
    if raw_phases is None:
        return [{} for _ in range(sample_count)]
    if not isinstance(raw_phases, list) or not raw_phases:
        raise ValueError(f"{case_id}.input_phases must be a list")
    samples = []
    for phase_index, phase in enumerate(raw_phases):
        if (
            not isinstance(phase, dict)
            or set(phase) != {"ticks", "lanes"}
            or not isinstance(phase.get("ticks"), int)
            or isinstance(phase.get("ticks"), bool)
            or not 1 <= phase["ticks"] <= sample_count
        ):
            raise ValueError(f"{case_id}.input_phases[{phase_index}] is invalid")
        samples.extend({"lanes": phase["lanes"]} for _ in range(phase["ticks"]))
    if len(samples) != sample_count:
        raise ValueError(
            f"{case_id}.input_phases expand to {len(samples)}, expected {sample_count}"
        )
    return samples


def generate_numeric_c(manifest: dict[str, Any]) -> str:
    if manifest.get("schema") != 1:
        raise ValueError("unsupported trace coverage schema")
    stored = manifest.get("stored_oracle")
    checkpoint_pack = manifest.get("checkpoint_pack")
    if not isinstance(stored, dict) or stored.get("kind") != "numeric-trace-v1":
        raise ValueError("stored_oracle.kind must be numeric-trace-v1")
    if not isinstance(checkpoint_pack, dict):
        raise ValueError("checkpoint_pack must be an object")
    capture_plan = checkpoint_pack.get("capture_plan")
    if not isinstance(capture_plan, dict):
        raise ValueError("checkpoint_pack.capture_plan must be an object")
    raw_cases = stored.get("cases")
    sample_key = "inputs"
    if raw_cases is None:
        # Backward-compatible route for the first numeric domain. New domains
        # keep their simulator input sequence under stored_oracle so this
        # generic generator is independent of the live-capture choreography.
        raw_cases = capture_plan.get("damage_response_cases")
        sample_key = "hitlag"
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("stored trace cases must be a non-empty list")
    c_config = stored.get("c")
    if not isinstance(c_config, dict):
        raise ValueError("stored_oracle.c must be an object")
    symbol_prefix = identifier(
        c_config.get("symbol_prefix"),
        "stored_oracle.c.symbol_prefix",
    )
    macro_prefix = identifier(
        c_config.get("macro_prefix"),
        "stored_oracle.c.macro_prefix",
    )
    samples_per_case = stored.get("samples_per_case")
    if (
        not isinstance(samples_per_case, int)
        or isinstance(samples_per_case, bool)
        or not 1 <= samples_per_case <= 128
    ):
        raise ValueError("samples_per_case must be in [1, 128]")
    lanes_per_sample = stored.get("lanes_per_sample", 1)
    if (
        not isinstance(lanes_per_sample, int)
        or isinstance(lanes_per_sample, bool)
        or not 1 <= lanes_per_sample <= 2
    ):
        raise ValueError("lanes_per_sample must be in [1, 2]")
    raw_fields = stored.get("serialized_fields")
    if raw_fields is None:
        serialized_fields = "PF_SSBM_STORED_TRACE_FIELDS_V1"
    else:
        if (
            not isinstance(raw_fields, list)
            or not raw_fields
            or any(field not in TRACE_FIELDS for field in raw_fields)
            or len(set(raw_fields)) != len(raw_fields)
        ):
            raise ValueError("serialized_fields contains an unsupported field")
        serialized_fields = " | ".join(TRACE_FIELDS[field] for field in raw_fields)
    source_digest = digest(
        stored.get("source_trace_sha256"),
        "stored_oracle.source_trace_sha256",
    )
    production_digest = digest(
        stored.get("production_trace_sha256"),
        "stored_oracle.production_trace_sha256",
    )

    rows: list[str] = []
    case_rows: list[str] = []
    ids: set[str] = set()
    maximum_samples_per_case = 0
    total_sample_count = 0
    for case_index, case in enumerate(raw_cases):
        if not isinstance(case, dict):
            raise ValueError(f"damage_response_cases[{case_index}] is invalid")
        case_id = case.get("id")
        case_sample_count = case.get("sample_count", samples_per_case)
        if (
            not isinstance(case_sample_count, int)
            or isinstance(case_sample_count, bool)
            or not 1 <= case_sample_count <= samples_per_case
        ):
            raise ValueError(
                f"{case_id}.sample_count must be in [1, {samples_per_case}]"
            )
        maximum_samples_per_case = max(
            maximum_samples_per_case, case_sample_count
        )
        total_sample_count += case_sample_count * lanes_per_sample
        samples = expand_case_samples(
            case,
            str(case_id),
            case_sample_count,
            sample_key,
        )
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in ids
            or not isinstance(samples, list)
            or len(samples) != case_sample_count
        ):
            raise ValueError(f"invalid trace case {case_id!r}")
        ids.add(case_id)
        initial_state_variant = case.get("initial_state_variant", 0)
        initial_facing = case.get("initial_facing", 0)
        case_raw_fields = case.get("serialized_fields")
        if (
            not isinstance(initial_state_variant, int)
            or isinstance(initial_state_variant, bool)
            or not 0 <= initial_state_variant <= 255
        ):
            raise ValueError(
                f"{case_id}.initial_state_variant must be an unsigned byte"
            )
        if (
            not isinstance(initial_facing, int)
            or isinstance(initial_facing, bool)
            or initial_facing not in (-1, 0, 1)
        ):
            raise ValueError(
                f"{case_id}.initial_facing must be -1, 0, or 1"
            )
        if case_raw_fields is None:
            case_fields = None
        elif (
            not isinstance(case_raw_fields, list)
            or not case_raw_fields
            or any(field not in TRACE_FIELDS for field in case_raw_fields)
            or len(set(case_raw_fields)) != len(case_raw_fields)
        ):
            raise ValueError(
                f"{case_id}.serialized_fields contains an unsupported field"
            )
        else:
            case_fields = " | ".join(
                TRACE_FIELDS[field] for field in case_raw_fields
            )
        input_symbol = f"{symbol_prefix}_{case_id}_inputs"
        rows.extend(
            [
                "static const pf_ssbm_stored_trace_input",
                f"{input_symbol}[] = {{",
            ]
        )
        for sample_index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise ValueError(
                    f"{case_id}.{sample_key}[{sample_index}] must be an object"
                )
            raw_lanes = sample.get("lanes")
            if lanes_per_sample == 1 and raw_lanes is None:
                lanes = [sample]
            elif (
                isinstance(raw_lanes, list)
                and len(raw_lanes) == lanes_per_sample
                and all(isinstance(lane, dict) for lane in raw_lanes)
            ):
                lanes = raw_lanes
            else:
                raise ValueError(
                    f"{case_id}.{sample_key}[{sample_index}].lanes must contain "
                    f"{lanes_per_sample} input objects"
                )
            for lane_index, lane in enumerate(lanes):
                lane_field = (
                    f"{case_id}.{sample_key}[{sample_index}].lanes[{lane_index}]"
                )
                main_x, main_y = stick(
                    lane.get("main", [0, 0]),
                    f"{lane_field}.main",
                    invert_y=True,
                )
                c_x, c_y = stick(
                    lane.get("c_stick", [0, 0]),
                    f"{lane_field}.c_stick",
                    invert_y=True,
                )
                button_bits = buttons(
                    lane.get("buttons"),
                    f"{lane_field}.buttons",
                )
                left_trigger = unsigned_16(
                    lane.get("left_trigger", 0),
                    f"{lane_field}.left_trigger",
                )
                right_trigger = unsigned_16(
                    lane.get("right_trigger", 0),
                    f"{lane_field}.right_trigger",
                )
                advance_ticks = unsigned_16(
                    lane.get("advance_ticks", 1),
                    f"{lane_field}.advance_ticks",
                )
                if advance_ticks == 0:
                    raise ValueError(
                        f"{lane_field}.advance_ticks must be positive"
                    )
                rows.append(
                    "    { "
                    f"INT16_C({main_x}), INT16_C({main_y}), "
                    f"INT16_C({c_x}), INT16_C({c_y}), "
                    f"{button_bits}, UINT16_C({left_trigger}), "
                    f"UINT16_C({right_trigger}), UINT16_C({advance_ticks})"
                    " },"
                )
        rows.extend(
            [
                "};",
                "_Static_assert(",
                f"    sizeof({input_symbol}) / sizeof({input_symbol}[0]) ==",
                f"        UINT16_C({case_sample_count * lanes_per_sample}),",
                f'    "stored trace input lanes are incomplete for {case_id}");',
                "",
            ]
        )
        explicit_case_fields = (
            "UINT32_C(0)" if case_fields is None else f"({case_fields})"
        )
        case_rows.append(
            f'    {{ {json.dumps(case_id)}, {input_symbol}, '
            f'UINT8_C({initial_state_variant}), '
            f'INT8_C({initial_facing}), {explicit_case_fields}, '
            f'UINT8_C({case_sample_count}) }},'
        )

    return "\n".join(
        [
            "/* Generated by tools/generate_ssbm_stored_trace_oracle.py. */",
            f"#ifndef {macro_prefix}_ORACLE_INC",
            f"#define {macro_prefix}_ORACLE_INC",
            "",
            *rows,
            "static const pf_ssbm_stored_trace_case",
            f"{symbol_prefix}_cases[] = {{",
            *case_rows,
            "};",
            "",
            f"#define {macro_prefix}_CASE_COUNT UINT16_C({len(case_rows)})",
            f"#define {macro_prefix}_SAMPLES_PER_CASE "
            f"UINT8_C({maximum_samples_per_case})",
            f"#define {macro_prefix}_TOTAL_SAMPLE_COUNT "
            f"UINT16_C({total_sample_count})",
            f"#define {macro_prefix}_LANES_PER_SAMPLE "
            f"UINT8_C({lanes_per_sample})",
            f"#define {macro_prefix}_SERIALIZED_FIELDS \\",
            f"    ({serialized_fields})",
            f"#define {macro_prefix}_SOURCE_TRACE_SHA256 \\",
            f"    {json.dumps(source_digest)}",
            f"#define {macro_prefix}_PRODUCTION_TRACE_SHA256 \\",
            f"    {json.dumps(production_digest)}",
            "",
            "_Static_assert(",
            f"    sizeof({symbol_prefix}_cases) /",
            f"            sizeof({symbol_prefix}_cases[0]) ==",
            f"        {macro_prefix}_CASE_COUNT,",
            '    "stored trace case manifest is incomplete");',
            "",
            f"#endif /* {macro_prefix}_ORACLE_INC */",
            "",
        ]
    )


def native_csv_fields(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(name not in NATIVE_CSV_TRACE_FIELDS for name in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{field} contains an unsupported field")
    return list(value)


def native_csv_field_exclusions(
    value: Any,
    fields: list[str],
    sample_count: int,
    field: str,
) -> dict[str, list[list[int]]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(name not in fields for name in value):
        raise ValueError(f"{field} contains an unsupported field")
    result: dict[str, list[list[int]]] = {}
    for name, ranges in value.items():
        if not isinstance(ranges, list) or not ranges:
            raise ValueError(f"{field}.{name} must be a non-empty list")
        normalized: list[list[int]] = []
        previous_end = 0
        for range_index, sample_range in enumerate(ranges):
            if (
                not isinstance(sample_range, list)
                or len(sample_range) != 2
                or any(
                    not isinstance(bound, int) or isinstance(bound, bool)
                    for bound in sample_range
                )
            ):
                raise ValueError(f"{field}.{name}[{range_index}] is invalid")
            start, end = sample_range
            if not 0 <= start < end <= sample_count or start < previous_end:
                raise ValueError(f"{field}.{name}[{range_index}] is invalid")
            normalized.append([start, end])
            previous_end = end
        result[name] = normalized
    return result


def native_csv_input_line(
    sample: dict[str, Any],
    case_id: str,
    sample_index: int,
    *,
    include_raw_main: bool = False,
    include_raw_c: bool = False,
) -> str:
    if include_raw_c and not include_raw_main:
        raise ValueError(f"{case_id} raw C-stick input requires raw main input")
    raw_lanes = sample.get("lanes")
    if (
        not isinstance(raw_lanes, list)
        or len(raw_lanes) != 2
        or any(not isinstance(lane, dict) for lane in raw_lanes)
    ):
        raise ValueError(
            f"{case_id}.inputs[{sample_index}].lanes must contain two inputs"
        )
    player = raw_lanes[0]
    opponent = raw_lanes[1]
    player_field = f"{case_id}.inputs[{sample_index}].lanes[0]"
    opponent_field = f"{case_id}.inputs[{sample_index}].lanes[1]"
    main_x, main_y = stick(
        player.get("main", [0, 0]),
        f"{player_field}.main",
        invert_y=True,
    )
    c_x, c_y = stick(
        player.get("c_stick", [0, 0]),
        f"{player_field}.c_stick",
        invert_y=True,
    )
    opponent_x, opponent_y = stick(
        opponent.get("main", [0, 0]),
        f"{opponent_field}.main",
        invert_y=True,
    )
    opponent_c_x, opponent_c_y = stick(
        opponent.get("c_stick", [0, 0]),
        f"{opponent_field}.c_stick",
        invert_y=True,
    )
    if opponent_y != 0 or opponent_c_x != 0 or opponent_c_y != 0:
        raise ValueError(
            f"{opponent_field} uses axes unsupported by the native CSV runner"
        )
    if opponent.get("left_trigger", 0) != 0 or opponent.get("right_trigger", 0) != 0:
        raise ValueError(
            f"{opponent_field} uses triggers unsupported by the native CSV runner"
        )
    player_buttons = button_mask(player.get("buttons"), f"{player_field}.buttons")
    opponent_buttons = button_mask(
        opponent.get("buttons"),
        f"{opponent_field}.buttons",
    )
    left_trigger = unsigned_16(
        player.get("left_trigger", 0),
        f"{player_field}.left_trigger",
    )
    right_trigger = unsigned_16(
        player.get("right_trigger", 0),
        f"{player_field}.right_trigger",
    )
    line = (
        f"{main_x},{main_y},{c_x},{c_y},{left_trigger},{right_trigger},"
        f"{player_buttons},{opponent_x},{opponent_buttons}"
    )
    raw_main_value = player.get("raw_main")
    if not include_raw_main:
        if raw_main_value is not None:
            raise ValueError(
                f"{player_field}.raw_main requires an exact-raw input case"
            )
        return line
    if not isinstance(raw_main_value, list) or len(raw_main_value) != 2:
        raise ValueError(f"{player_field}.raw_main must contain two raw axes")
    raw_main_x = raw_axis(raw_main_value[0], f"{player_field}.raw_main[0]")
    raw_main_y = raw_axis(raw_main_value[1], f"{player_field}.raw_main[1]")
    raw_c_value = player.get("raw_c")
    if not include_raw_c:
        if raw_c_value is not None:
            raise ValueError(f"{player_field}.raw_c requires a full raw-pad case")
        return f"{line},{raw_main_x},{raw_main_y},3"
    if not isinstance(raw_c_value, list) or len(raw_c_value) != 2:
        raise ValueError(f"{player_field}.raw_c must contain two raw axes")
    raw_c_x = raw_axis(raw_c_value[0], f"{player_field}.raw_c[0]")
    raw_c_y = raw_axis(raw_c_value[1], f"{player_field}.raw_c[1]")
    return f"{line},{raw_main_x},{raw_main_y},{raw_c_x},{raw_c_y},15"


def generate_native_csv(manifest: dict[str, Any]) -> str:
    if manifest.get("schema") != 1:
        raise ValueError("unsupported trace coverage schema")
    domain = manifest.get("domain")
    stored = manifest.get("stored_oracle")
    if not isinstance(domain, str) or not domain:
        raise ValueError("domain must be a non-empty string")
    if not isinstance(stored, dict) or stored.get("kind") != "native-csv-trace-v1":
        raise ValueError("stored_oracle.kind must be native-csv-trace-v1")
    fields = native_csv_fields(
        stored.get("serialized_fields"),
        "stored_oracle.serialized_fields",
    )
    source_digest = digest(
        stored.get("source_trace_sha256"),
        "stored_oracle.source_trace_sha256",
    )
    production_digest = digest(
        stored.get("production_trace_sha256"),
        "stored_oracle.production_trace_sha256",
    )
    raw_cases = stored.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("stored trace cases must be a non-empty list")
    cases: list[dict[str, Any]] = []
    ids: set[str] = set()
    for case_index, case in enumerate(raw_cases):
        if not isinstance(case, dict):
            raise ValueError(f"stored_oracle.cases[{case_index}] is invalid")
        case_id = case.get("id")
        sample_count = case.get("sample_count")
        runner_arguments = case.get("runner_arguments")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in ids
            or not isinstance(sample_count, int)
            or isinstance(sample_count, bool)
            or not 1 <= sample_count <= 4096
            or not isinstance(runner_arguments, list)
            or any(
                not isinstance(value, str) or not value
                for value in runner_arguments
            )
        ):
            raise ValueError(f"invalid native CSV trace case {case_id!r}")
        ids.add(case_id)
        case_fields = native_csv_fields(
            case.get("serialized_fields", fields),
            f"{case_id}.serialized_fields",
        )
        field_exclusions = native_csv_field_exclusions(
            case.get("field_exclusions"),
            case_fields,
            sample_count,
            f"{case_id}.field_exclusions",
        )
        samples = expand_case_samples(case, case_id, sample_count, "inputs")
        raw_main_presence = [
            isinstance(sample.get("lanes"), list)
            and len(sample["lanes"]) == 2
            and isinstance(sample["lanes"][0], dict)
            and "raw_main" in sample["lanes"][0]
            for sample in samples
        ]
        if any(raw_main_presence) and not all(raw_main_presence):
            raise ValueError(
                f"{case_id}.inputs must declare raw_main on every sample"
            )
        raw_c_presence = [
            isinstance(sample.get("lanes"), list)
            and len(sample["lanes"]) == 2
            and isinstance(sample["lanes"][0], dict)
            and "raw_c" in sample["lanes"][0]
            for sample in samples
        ]
        if any(raw_c_presence) and not all(raw_c_presence):
            raise ValueError(
                f"{case_id}.inputs must declare raw_c on every sample"
            )
        if any(raw_c_presence) and not all(raw_main_presence):
            raise ValueError(f"{case_id}.inputs raw_c requires raw_main")
        include_raw_main = all(raw_main_presence)
        include_raw_c = all(raw_c_presence)
        lines = [
            native_csv_input_line(
                sample,
                case_id,
                sample_index,
                include_raw_main=include_raw_main,
                include_raw_c=include_raw_c,
            )
            for sample_index, sample in enumerate(samples)
        ]
        runs: list[dict[str, Any]] = []
        for line in lines:
            if runs and runs[-1]["input"] == line:
                runs[-1]["ticks"] += 1
            else:
                runs.append({"ticks": 1, "input": line})
        cases.append(
            {
                "id": case_id,
                "runner_arguments": runner_arguments,
                "sample_count": sample_count,
                "serialized_fields": case_fields,
                "field_exclusions": field_exclusions,
                "input_runs": runs,
            }
        )
    generated = {
        "schema": 1,
        "kind": "native-csv-trace-v1",
        "domain": domain,
        "source_trace_sha256": source_digest,
        "production_trace_sha256": production_digest,
        "cases": cases,
    }
    return json.dumps(generated, indent=2, sort_keys=True) + "\n"


def generate(manifest: dict[str, Any]) -> str:
    stored = manifest.get("stored_oracle")
    kind = stored.get("kind") if isinstance(stored, dict) else None
    if kind == "numeric-trace-v1":
        return generate_numeric_c(manifest)
    if kind == "native-csv-trace-v1":
        return generate_native_csv(manifest)
    raise ValueError(f"unsupported stored_oracle.kind: {kind!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    generated = generate(manifest)
    if args.check:
        if not args.output.is_file() or args.output.read_text(
            encoding="utf-8"
        ) != generated:
            raise SystemExit(f"stored trace oracle is stale: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(generated, encoding="utf-8", newline="\n")
    print(
        "ssbm-stored-trace-generation=pass "
        f"domain={manifest['domain']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
