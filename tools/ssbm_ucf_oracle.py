#!/usr/bin/env python3
"""Fail-closed NTSC 1.02 + UCF 0.84 live-oracle policy.

Slippi's netplay configuration contains UCF alongside unrelated gameplay
patches.  Equivalence captures retain the eight pinned UCF 0.84 hooks and the
two recording initializers needed by the observer, then restore every other
``[affects-gameplay]`` hook to the owner-supplied disc instruction.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import re
import struct
from typing import Any


POLICY_SCHEMA = "ssbm-ntsc102-ucf084-oracle-v2"
LIBMELEE_VERSION = "0.47.2"
LIBMELEE_TEMPLATE_SHA256 = (
    "6ec648b95f1b9b18a0a984c64482d2c0e0f8ae8eef8418e22d05bef0701a5ab6"
)
EXIAI_DOLPHIN_REVISION = "bf1aec4de4856eab412996137287f447daa8ae17"
EXIAI_GAME_SETTINGS_REVISION = "a144bd0f77d4193b322427fc7d359ae1da0092c3"
UCF_OFFICIAL_RELEASE_TAG = "ucf0.84_2024-06-27"
UCF_OFFICIAL_RELEASE_REVISION = "01122231ea97683cf7adea43d732ce0a4784c849"
GLOBAL_CONFIG_SHA256 = (
    "2097aba3d629401e669bf4461e6d4dc591011330270e46c6778713c4dfe64cf0"
)
NETPLAY_INVENTORY_SHA256 = (
    "0cb411a3c49a652a9d26933cdc5358c1cfe85c6f4d402613011bdea08b6622cb"
)
UCF_084_INVENTORY_SHA256 = (
    "9defe647d99cf3338ef304febbd8bf5323d8a2619ddbb5d2b0503bd63d7bf66b"
)

UCF_084_GAMEPLAY_ADDRESSES = frozenset(
    {
        0x800D65EC,  # DBOOC SquatRv fix
        0x800C9A44,  # dashback
        0x8006B460,  # hardware-pad history and 1.0 cardinals
        0x8008E54C,  # SDI
        0x8009A0B8,  # extended shield-drop cardinal handling
        0x800998A4,  # shield drop
        0x80093294,  # shield SDI
        0x800908F4,  # tumble wiggle
    }
)
# Three UCF blocks intentionally keep mutable scratch/ring-buffer state at the
# beginning of their C2 allocation. Runtime proof starts at the first immutable
# instruction of each body; the remaining hooks are immutable from byte zero.
UCF_RUNTIME_PROOF_OFFSETS = {
    0x800D65EC: 0x3C,  # DBOOC embedded vector scratch occupies +0x04..+0x37
    0x800C9A44: 0x00,
    0x8006B460: 0xB0,  # four-port raw-pad history occupies +0x04..+0x33
    0x8008E54C: 0x00,
    0x8009A0B8: 0x00,
    0x800998A4: 0x3C,  # shield-drop vector scratch occupies +0x04..+0x37
    0x80093294: 0x00,
    0x800908F4: 0x00,
}
OBSERVER_INITIALIZER_ADDRESSES = frozenset(
    {
        0x801C154C,  # Slippi Init Stage Data
        0x80068EEC,  # Slippi Init Player Data
    }
)
REQUIRED_ENABLED_GROUPS = frozenset(
    {
        "$Required: General Codes",
        "$Required: Slippi Recording",
        "$Required: Slippi Online",
    }
)

EXTRACT_MENU_GROUP = "$Optional: Extract Menu Info"
BOT_INPUT_GROUP = "$Optional: Allow Bot Input Overrides"
FAST_FORWARD_GROUP = "$Optional: FFW VS Mode"
NATIVE_CAPSULE_GROUP = "$Oracle: Native Capsule Spawning"
FORBIDDEN_LOCAL_GROUPS = frozenset(
    {
        "$Optional: Infinite Time Mode",
        "$Optional: Instant Match",
    }
)

# These hooks are capture transport/observation/acceleration machinery, not
# simulation semantics. Pinning their complete source payloads prevents a
# nominally UCF capture from silently using a different input or clock path.
CAPTURE_GROUP_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    EXTRACT_MENU_GROUP: (
        {
            "address": 0x801A4FA4,
            "code_type": "C2",
            "annotation": "Common/ExtractMenuInfo/SendMenuFrame.asm",
            "payload_sha256": (
                "79f2a1434c0be394103b050ecaa0b71d433bca7aec457a2fe550a73564ae5dfc"
            ),
            "runtime_proof_offset": 0,
            "runtime_proof_size": 32,
        },
    ),
    BOT_INPUT_GROUP: (
        {
            "address": 0x80377598,
            "code_type": "C2",
            "annotation": "AI/OverwriteInputs/OverwriteInputs.asm",
            "payload_sha256": (
                "589826780e193e2e536aff0a217cd03d2a3e564350078db399bde79b12fb14ea"
            ),
            # +0x08/+0x0c are mutable private state. The leading branch pair is
            # immutable and the complete source payload is pinned statically.
            "runtime_proof_offset": 0,
            "runtime_proof_size": 8,
        },
    ),
    FAST_FORWARD_GROUP: (
        {
            "address": 0x801A500C,
            "code_type": "C2",
            "annotation": "AI/LoopMainEngine/ForceContinueLoop.asm",
            "payload_sha256": (
                "e04c94953fb0eda751c1b9718c78e5affb11ef8ee34273eb45fde1589dc1e153"
            ),
        },
        {
            "address": 0x801A4DA8,
            "code_type": "C2",
            "annotation": "AI/LoopMainEngine/ForceStartLoop.asm",
            "payload_sha256": (
                "a411b4c795d3b7290bb16443da4a649cb13c0c7fab87b715c4f99356be1d4a5e"
            ),
        },
        {
            "address": 0x80377544,
            "code_type": "C2",
            "annotation": "AI/LoopMainEngine/IncrementPadIndex.asm",
            "payload_sha256": (
                "21d96b544882044adeb71eb4fcb53f7875e7801bd8e116d2443217ce3dfa565d"
            ),
        },
        {
            "address": 0x80376A88,
            "code_type": "04",
            "annotation": "AI/LoopMainEngine/PadAlwaysUseMasterIndex.asm",
            "payload_sha256": (
                "33eb0c588f465290c49617ccc59c705aa484c06101005e5d4b7637558b28fc23"
            ),
        },
        {
            "address": 0x8001960C,
            "code_type": "C2",
            "annotation": "AI/LoopMainEngine/PreventControllerReads.asm",
            "payload_sha256": (
                "38e0296355d2a83b96a1cafeb384055a44685ec604f720c36c728786a3da2d8a"
            ),
        },
        {
            "address": 0x8038D00C,
            "code_type": "C2",
            "annotation": "AI/LoopMainEngine/SkipSounds.asm",
            "payload_sha256": (
                "ab8bf3c4a30c755e50b1e202c529458a08ff001eda39a28f6d82f8d475849d69"
            ),
        },
    ),
    NATIVE_CAPSULE_GROUP: (
        {
            "address": 0x8016AE80,
            "code_type": "04",
            "annotation": "Oracle/Items/NativeFrequencyVeryHigh.asm",
            "payload": "38600004",
        },
        {
            "address": 0x8016AE84,
            "code_type": "04",
            "annotation": "",
            "payload": "4e800020",
        },
        {
            "address": 0x8016AEA4,
            "code_type": "04",
            "annotation": "Oracle/Items/NativeMaskCapsuleHi.asm",
            "payload": "38600000",
        },
        {
            "address": 0x8016AEA8,
            "code_type": "04",
            "annotation": "",
            "payload": "38800001",
        },
        {
            "address": 0x8016AEAC,
            "code_type": "04",
            "annotation": "",
            "payload": "4e800020",
        },
    ),
}

_HEX_WORD = re.compile(r"^[0-9A-Fa-f]{8}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_text(path: Path) -> str:
    return path.read_text(encoding="ascii").replace("\r\n", "\n").replace("\r", "\n")


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _group_identity(value: str) -> str:
    return value.split("[", 1)[0].rstrip()


def _section(text: str, name: str) -> str:
    marker = f"[{name}]\n"
    if marker not in text:
        raise RuntimeError(f"missing [{name}] section")
    body = text.split(marker, 1)[1]
    return body.split("\n[", 1)[0]


def parse_gecko_config(path: Path) -> tuple[set[str], dict[str, list[dict[str, Any]]]]:
    """Parse the 04/C2 records emitted by Slippi's pinned Gecko generator."""

    text = _normalized_text(path)
    enabled = {
        line.strip()
        for line in _section(text, "Gecko_Enabled").splitlines()
        if line.strip().startswith("$")
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    current_group: str | None = None
    lines = _section(text, "Gecko").splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith(("*", "#")):
            index += 1
            continue
        if stripped.startswith("$"):
            current_group = _group_identity(stripped)
            if current_group in groups:
                raise RuntimeError(f"duplicate Gecko group: {current_group}")
            groups[current_group] = []
            index += 1
            continue
        if current_group is None:
            raise RuntimeError(f"Gecko record outside a group: {stripped!r}")
        record_text, _, annotation = stripped.partition("#")
        words = record_text.split()
        if len(words) != 2 or any(_HEX_WORD.fullmatch(word) is None for word in words):
            raise RuntimeError(f"invalid Gecko record: {stripped!r}")
        first = int(words[0], 16)
        code_type = first >> 24
        address = 0x80000000 | (first & 0x01FFFFFF)
        if code_type == 0x04:
            groups[current_group].append(
                {
                    "address": address,
                    "code_type": "04",
                    "annotation": annotation.strip(),
                    "payload": bytes.fromhex(words[1]),
                }
            )
            index += 1
            continue
        if code_type != 0xC2:
            raise RuntimeError(
                f"unsupported Gecko codetype 0x{code_type:02x} in {current_group}"
            )
        payload_rows = int(words[1], 16)
        if payload_rows <= 0:
            raise RuntimeError(f"invalid C2 row count: {stripped!r}")
        payload = bytearray()
        payload_index = index + 1
        parsed_rows = 0
        while parsed_rows < payload_rows:
            if payload_index >= len(lines):
                raise RuntimeError(f"truncated C2 Gecko record: {stripped!r}")
            payload_line = lines[payload_index].strip()
            payload_index += 1
            if not payload_line or payload_line.startswith(("*", "#")):
                continue
            payload_words = payload_line.split("#", 1)[0].split()
            if (
                len(payload_words) != 2
                or any(_HEX_WORD.fullmatch(word) is None for word in payload_words)
            ):
                raise RuntimeError(
                    f"invalid C2 payload: {payload_line!r}"
                )
            payload.extend(bytes.fromhex("".join(payload_words)))
            parsed_rows += 1
        groups[current_group].append(
            {
                "address": address,
                "code_type": "C2",
                "annotation": annotation.strip(),
                "payload": bytes(payload),
            }
        )
        index = payload_index
    return enabled, groups


def _runtime_proof_fields(
    record: dict[str, Any],
    *,
    offset: int = 0,
    requested_size: int = 32,
) -> dict[str, Any]:
    payload = bytes(record["payload"])
    if record["code_type"] == "04":
        return {
            "runtime_proof_offset": 0,
            "runtime_proof_bytes": payload.hex(),
        }
    if record["code_type"] != "C2":
        raise RuntimeError(f"unsupported runtime-proof codetype: {record['code_type']}")
    # Gecko owns and rewrites the final C2 row with its return branch.
    proof_end = min(len(payload) - 8, offset + requested_size)
    if offset < 0 or requested_size < 8 or proof_end - offset < 8:
        raise RuntimeError(
            f"C2 runtime proof span is too short: 0x{int(record['address']):08x}"
        )
    return {
        "runtime_proof_offset": offset,
        "runtime_proof_bytes": payload[offset:proof_end].hex(),
    }


def _enrich_exact_group(
    groups: dict[str, list[dict[str, Any]]],
    group: str,
) -> list[dict[str, Any]]:
    specs = CAPTURE_GROUP_SPECS[group]
    records = groups.get(group)
    if records is None:
        raise RuntimeError(f"missing authorized capture Gecko group: {group}")
    if len(records) != len(specs):
        raise RuntimeError(
            f"authorized capture group {group} has {len(records)} records; "
            f"expected {len(specs)}"
        )
    enriched: list[dict[str, Any]] = []
    for record, spec in zip(records, specs, strict=True):
        payload = bytes(record["payload"])
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        expected_payload = spec.get("payload")
        if (
            int(record["address"]) != int(spec["address"])
            or record["code_type"] != spec["code_type"]
            or record["annotation"] != spec["annotation"]
            or (
                "payload_sha256" in spec
                and payload_sha256 != spec["payload_sha256"]
            )
            or (
                expected_payload is not None
                and payload.hex() != str(expected_payload).lower()
            )
        ):
            raise RuntimeError(
                f"authorized capture Gecko payload drifted: {group} "
                f"0x{int(record['address']):08x}"
            )
        proof = _runtime_proof_fields(
            record,
            offset=int(spec.get("runtime_proof_offset", 0)),
            requested_size=int(spec.get("runtime_proof_size", 32)),
        )
        enriched.append(
            {
                "group": group,
                "address": int(record["address"]),
                "code_type": str(record["code_type"]),
                "annotation": str(record["annotation"]),
                "source_payload_sha256": payload_sha256,
                **proof,
            }
        )
    return enriched


def _expected_local_config(
    template: str,
    *,
    enable_fast_forward: bool,
    allow_native_capsule_spawning: bool,
) -> str:
    if template.count("{extra_codes}") != 1:
        raise RuntimeError("libmelee Gecko template placeholder drifted")
    extra_codes = BOT_INPUT_GROUP
    if enable_fast_forward:
        extra_codes += "\n" + FAST_FORWARD_GROUP
    expected = template.format(extra_codes=extra_codes)
    if not allow_native_capsule_spawning:
        return expected
    enabled_header = "[Gecko_Enabled]\n"
    gecko_header = "[Gecko]\n"
    if expected.count(enabled_header) != 1 or expected.count(gecko_header) != 1:
        raise RuntimeError("libmelee Gecko template sections drifted")
    native_lines = []
    for spec in CAPTURE_GROUP_SPECS[NATIVE_CAPSULE_GROUP]:
        first = 0x04000000 | (int(spec["address"]) & 0x01FFFFFF)
        line = f"{first:08X} {str(spec['payload']).upper()}"
        if spec["annotation"]:
            line += f" # {spec['annotation']}"
        native_lines.append(line)
    expected = expected.replace(
        enabled_header,
        enabled_header + NATIVE_CAPSULE_GROUP + "\n",
        1,
    )
    expected = expected.replace(
        gecko_header,
        gecko_header + NATIVE_CAPSULE_GROUP + "\n" + "\n".join(native_lines) + "\n",
        1,
    )
    return expected


def _inventory(path: Path, expected_sha256: str) -> list[dict[str, Any]]:
    actual_sha256 = _sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"Slippi injection inventory drifted: {path} sha256={actual_sha256}"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    details = document.get("Details") if isinstance(document, dict) else None
    if not isinstance(details, list):
        raise RuntimeError(f"invalid Slippi injection inventory: {path}")
    return details


def _gameplay_inventory_rows(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in details:
        if not isinstance(raw, dict) or raw.get("Tags") != "[affects-gameplay]":
            continue
        address_text = raw.get("InjectionAddress")
        if not isinstance(address_text, str) or _HEX_WORD.fullmatch(address_text) is None:
            raise RuntimeError(f"invalid gameplay-hook address: {address_text!r}")
        rows.append(
            {
                "address": int(address_text, 16),
                "annotation": str(raw.get("Annotation", "")),
                "group": "$" + str(raw.get("Name", "")),
                "metadata_codetype": str(raw.get("Codetype", "")),
            }
        )
    if len({int(row["address"]) for row in rows}) != len(rows):
        raise RuntimeError("duplicate gameplay-hook address in Slippi inventory")
    return rows


def dol_word_at_address(iso: Path, address: int) -> bytes:
    """Read one uniquely mapped word from all 7 text and 11 data DOL sections."""

    if not 0x80000000 <= address <= 0x817FFFFC or address % 4 != 0:
        raise ValueError(f"invalid DOL address: 0x{address:08x}")
    with iso.open("rb") as source:
        source.seek(0x420)
        dol_offset_bytes = source.read(4)
        if len(dol_offset_bytes) != 4:
            raise RuntimeError("disc image does not contain a main.dol offset")
        dol_offset = int.from_bytes(dol_offset_bytes, "big")
        source.seek(dol_offset)
        header = source.read(0x100)
        if len(header) != 0x100:
            raise RuntimeError("disc image contains a truncated main.dol header")
        file_offsets = (
            *struct.unpack_from(">7I", header, 0x00),
            *struct.unpack_from(">11I", header, 0x1C),
        )
        memory_addresses = (
            *struct.unpack_from(">7I", header, 0x48),
            *struct.unpack_from(">11I", header, 0x64),
        )
        section_sizes = (
            *struct.unpack_from(">7I", header, 0x90),
            *struct.unpack_from(">11I", header, 0xAC),
        )
        matches = [
            (file_offset, memory_address)
            for file_offset, memory_address, section_size in zip(
                file_offsets, memory_addresses, section_sizes, strict=True
            )
            if section_size != 0
            and memory_address <= address
            and address + 4 <= memory_address + section_size
        ]
        if len(matches) != 1:
            raise ValueError(
                f"DOL address maps to {len(matches)} executable sections: "
                f"0x{address:08x}"
            )
        file_offset, memory_address = matches[0]
        source.seek(dol_offset + file_offset + address - memory_address)
        word = source.read(4)
        if len(word) != 4:
            raise RuntimeError(f"disc image truncated at DOL address 0x{address:08x}")
        return word


def _append_gecko_group(path: Path, name: str, records: list[str]) -> None:
    text = path.read_text(encoding="ascii").replace("\r\n", "\n")
    if name in text:
        raise RuntimeError(f"duplicate local Gecko policy group: {name}")

    def append_to_section(source: str, section_name: str, payload: str) -> str:
        marker = f"[{section_name}]\n"
        start = source.find(marker)
        if start < 0:
            raise RuntimeError(f"missing local [{section_name}] section")
        body_start = start + len(marker)
        next_section = source.find("\n[", body_start)
        body_end = len(source) if next_section < 0 else next_section
        body = source[body_start:body_end].rstrip("\n")
        replacement = (body + "\n" if body else "") + payload.rstrip("\n") + "\n"
        return source[:body_start] + replacement + source[body_end:]

    text = append_to_section(text, "Gecko_Enabled", name)
    text = append_to_section(text, "Gecko", name + "\n" + "\n".join(records))
    path.write_text(text, encoding="ascii", newline="\n")


def configure_ucf084_oracle(
    console: object,
    dolphin: Path,
    iso: Path,
    *,
    allow_native_capsule_spawning: bool = False,
) -> dict[str, Any]:
    """Install exact UCF gameplay plus pinned capture-only Gecko machinery."""

    sys_root = dolphin.parent / "Sys"
    global_config = sys_root / "GameSettings" / "GALE01r2.ini"
    netplay_inventory = sys_root / "Slippi" / "InjectionLists" / "list_netplay.json"
    ucf_inventory = (
        sys_root / "Slippi" / "InjectionLists" / "list_console_UCF_084.json"
    )
    local_config = (
        Path(console._get_dolphin_home_path()) / "GameSettings" / "GALE01r2.ini"
    )
    for required in (global_config, netplay_inventory, ucf_inventory, local_config):
        if not required.is_file():
            raise FileNotFoundError(f"missing UCF oracle policy input: {required}")
    if not dolphin.is_file():
        raise FileNotFoundError(f"missing UCF oracle Dolphin executable: {dolphin}")

    libmelee_version = importlib.metadata.version("melee")
    if libmelee_version != LIBMELEE_VERSION:
        raise RuntimeError(
            f"unsupported libmelee version {libmelee_version}; "
            f"expected {LIBMELEE_VERSION}"
        )
    required_console_flags = {
        "setup_gecko_codes": True,
        "use_exi_inputs": True,
        "infinite_time": False,
        "instant_match_restart": False,
    }
    for attribute, expected in required_console_flags.items():
        actual = getattr(console, attribute, None)
        if actual is not expected:
            raise RuntimeError(
                f"UCF oracle requires console.{attribute}={expected}; got {actual}"
            )
    enable_fast_forward = getattr(console, "enable_ffw", None)
    if not isinstance(enable_fast_forward, bool):
        raise RuntimeError("UCF oracle requires an explicit console.enable_ffw flag")

    libmelee_template = Path(inspect.getfile(type(console))).with_name("GALE01r2.ini")
    if not libmelee_template.is_file():
        raise FileNotFoundError(
            f"missing libmelee Gecko template beside Console: {libmelee_template}"
        )
    template_sha256 = _sha256(libmelee_template)
    if template_sha256 != LIBMELEE_TEMPLATE_SHA256:
        raise RuntimeError(
            "pinned libmelee Gecko template drifted: "
            f"sha256={template_sha256}"
        )
    expected_local_text = _expected_local_config(
        _normalized_text(libmelee_template),
        enable_fast_forward=enable_fast_forward,
        allow_native_capsule_spawning=allow_native_capsule_spawning,
    )
    actual_local_text = _normalized_text(local_config)
    if actual_local_text != expected_local_text:
        raise RuntimeError(
            "generated libmelee Gecko config drifted: "
            f"expected_sha256={_text_sha256(expected_local_text)} "
            f"actual_sha256={_text_sha256(actual_local_text)}"
        )
    local_config_sha256_before_policy = _sha256(local_config)
    local_config_normalized_sha256_before_policy = _text_sha256(actual_local_text)
    local_enabled, local_groups = parse_gecko_config(local_config)
    expected_local_enabled = {EXTRACT_MENU_GROUP, BOT_INPUT_GROUP}
    if enable_fast_forward:
        expected_local_enabled.add(FAST_FORWARD_GROUP)
    if allow_native_capsule_spawning:
        expected_local_enabled.add(NATIVE_CAPSULE_GROUP)
    if local_enabled != expected_local_enabled:
        raise RuntimeError(
            "unexpected enabled libmelee Gecko groups: "
            f"expected={sorted(expected_local_enabled)!r} "
            f"actual={sorted(local_enabled)!r}"
        )
    if local_enabled & FORBIDDEN_LOCAL_GROUPS:
        raise RuntimeError("gameplay-changing libmelee convenience group is enabled")

    actual_config_sha256 = _sha256(global_config)
    if actual_config_sha256 != GLOBAL_CONFIG_SHA256:
        raise RuntimeError(
            "pinned Slippi Gecko config drifted: "
            f"sha256={actual_config_sha256}"
        )

    gameplay_rows = _gameplay_inventory_rows(
        _inventory(netplay_inventory, NETPLAY_INVENTORY_SHA256)
    )
    ucf_rows = _gameplay_inventory_rows(
        _inventory(ucf_inventory, UCF_084_INVENTORY_SHA256)
    )
    gameplay_addresses = {int(row["address"]) for row in gameplay_rows}
    ucf_addresses = {int(row["address"]) for row in ucf_rows}
    if len(gameplay_rows) != 27:
        raise RuntimeError("expected exactly 27 distinct Slippi gameplay hooks")
    if ucf_addresses != set(UCF_084_GAMEPLAY_ADDRESSES):
        raise RuntimeError("pinned UCF 0.84 gameplay-hook inventory drifted")
    if not (
        set(UCF_084_GAMEPLAY_ADDRESSES) | set(OBSERVER_INITIALIZER_ADDRESSES)
    ).issubset(gameplay_addresses):
        raise RuntimeError("UCF/observer hook is absent from netplay inventory")

    enabled, groups = parse_gecko_config(global_config)
    if not REQUIRED_ENABLED_GROUPS.issubset(enabled):
        raise RuntimeError("required Slippi Gecko groups are not enabled")
    records_by_address: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    for group, records in groups.items():
        if group not in enabled:
            continue
        for record in records:
            records_by_address.setdefault(int(record["address"]), []).append(
                (group, record)
            )

    enriched: list[dict[str, Any]] = []
    for row in gameplay_rows:
        address = int(row["address"])
        matches = records_by_address.get(address, [])
        if len(matches) != 1:
            raise RuntimeError(
                f"gameplay hook has {len(matches)} enabled Gecko records: "
                f"0x{address:08x}"
            )
        group, record = matches[0]
        if group != row["group"] or record["annotation"] != row["annotation"]:
            raise RuntimeError(
                f"gameplay-hook metadata/config mismatch: 0x{address:08x}"
            )
        original = dol_word_at_address(iso, address)
        payload = bytes(record["payload"])
        proof_offset = UCF_RUNTIME_PROOF_OFFSETS.get(address, 0)
        proof = (
            _runtime_proof_fields(record, offset=proof_offset)
            if record["code_type"] == "C2"
            else {"runtime_proof_offset": 0, "runtime_proof_bytes": ""}
        )
        enriched.append(
            {
                **row,
                "code_type": str(record["code_type"]),
                "original_word": original.hex(),
                "source_payload_sha256": hashlib.sha256(payload).hexdigest(),
                **proof,
            }
        )
    if any(
        hook["code_type"] != "C2"
        for hook in enriched
        if int(hook["address"]) in UCF_084_GAMEPLAY_ADDRESSES
    ):
        raise RuntimeError("every pinned UCF 0.84 gameplay hook must be C2")

    observer_transport_hooks = [
        *_enrich_exact_group(local_groups, EXTRACT_MENU_GROUP),
        *_enrich_exact_group(groups, BOT_INPUT_GROUP),
    ]
    fast_forward_hooks = (
        _enrich_exact_group(groups, FAST_FORWARD_GROUP)
        if enable_fast_forward
        else []
    )
    scenario_setup_hooks = (
        _enrich_exact_group(local_groups, NATIVE_CAPSULE_GROUP)
        if allow_native_capsule_spawning
        else []
    )
    capture_hook_addresses = [
        int(hook["address"])
        for hook in (
            *observer_transport_hooks,
            *fast_forward_hooks,
            *scenario_setup_hooks,
        )
    ]
    if len(capture_hook_addresses) != len(set(capture_hook_addresses)):
        raise RuntimeError("authorized capture Gecko hooks overlap")
    if set(capture_hook_addresses) & gameplay_addresses:
        raise RuntimeError("capture-only Gecko hook overlaps gameplay inventory")

    retained = set(UCF_084_GAMEPLAY_ADDRESSES) | set(
        OBSERVER_INITIALIZER_ADDRESSES
    )
    restored_hooks = [
        hook for hook in enriched if int(hook["address"]) not in retained
    ]
    ucf_hooks = [
        hook
        for hook in enriched
        if int(hook["address"]) in UCF_084_GAMEPLAY_ADDRESSES
    ]
    observer_hooks = [
        hook
        for hook in enriched
        if int(hook["address"]) in OBSERVER_INITIALIZER_ADDRESSES
    ]
    if (len(restored_hooks), len(ucf_hooks), len(observer_hooks)) != (17, 8, 2):
        raise RuntimeError("unexpected UCF oracle policy partition")

    restore_records = [
        f"{0x04000000 | (int(hook['address']) & 0x01FFFFFF):08X} "
        f"{str(hook['original_word']).upper()} # Oracle/UCF-only: "
        f"{hook['annotation']}"
        for hook in restored_hooks
    ]
    policy_group = "$Oracle: NTSC 1.02 + UCF 0.84 Gameplay Only"
    _append_gecko_group(local_config, policy_group, restore_records)

    provenance: dict[str, Any] = {
        "schema": POLICY_SCHEMA,
        "target": "GALE01 NTSC-U revision 2 with UCF 0.84",
        "ucf_version": "0.84",
        "ucf_official_release_tag": UCF_OFFICIAL_RELEASE_TAG,
        "ucf_official_release_revision": UCF_OFFICIAL_RELEASE_REVISION,
        "slippi_asm_payload_mirror_revision": (
            "fcf47f10dc244152c2ebaa3a9dec142ea42243b7"
        ),
        "exiai_dolphin_revision": EXIAI_DOLPHIN_REVISION,
        "exiai_game_settings_revision": EXIAI_GAME_SETTINGS_REVISION,
        "dolphin_executable_sha256": _sha256(dolphin),
        "libmelee_version": libmelee_version,
        "libmelee_template_sha256": template_sha256,
        "global_config_sha256": actual_config_sha256,
        "netplay_inventory_sha256": NETPLAY_INVENTORY_SHA256,
        "ucf_inventory_sha256": UCF_084_INVENTORY_SHA256,
        "exi_input_transport_enabled": True,
        "fast_forward_enabled": enable_fast_forward,
        "authorized_local_groups": sorted(expected_local_enabled),
        "local_config_sha256_before_policy": local_config_sha256_before_policy,
        "local_config_normalized_sha256_before_policy": (
            local_config_normalized_sha256_before_policy
        ),
        "policy_group": policy_group,
        "restored_hooks": sorted(restored_hooks, key=lambda item: int(item["address"])),
        "ucf_hooks": sorted(ucf_hooks, key=lambda item: int(item["address"])),
        "observer_initializers": sorted(
            observer_hooks, key=lambda item: int(item["address"])
        ),
        "observer_transport_hooks": observer_transport_hooks,
        "fast_forward_hooks": fast_forward_hooks,
        "scenario_setup_hooks": scenario_setup_hooks,
        "local_config_sha256": _sha256(local_config),
        "runtime_verified": False,
    }
    provenance["policy_sha256"] = _canonical_sha256(
        {key: value for key, value in provenance.items() if key != "runtime_verified"}
    )
    return provenance


def _branch_target(address: int, instruction: int) -> int:
    if instruction >> 26 != 18:
        raise RuntimeError(
            f"expected PowerPC branch at 0x{address:08x}, got 0x{instruction:08x}"
        )
    displacement = instruction & 0x03FFFFFC
    if displacement & 0x02000000:
        displacement -= 0x04000000
    target = displacement if instruction & 0x2 else address + displacement
    if target % 4 != 0 or not 0x80000000 <= target < 0x81800000:
        raise RuntimeError(
            f"invalid Gecko branch target at 0x{address:08x}: 0x{target:08x}"
        )
    return target


def ucf084_runtime_hook_target(memory_engine: object, address: int) -> int:
    """Resolve one proven UCF 0.84 C2 entry to its live MEM1 body."""

    if address not in UCF_084_GAMEPLAY_ADDRESSES:
        raise ValueError(f"unknown UCF 0.84 gameplay hook: 0x{address:08x}")
    entry = int.from_bytes(bytes(memory_engine.read_bytes(address, 4)), "big")
    return _branch_target(address, entry)


def verify_ucf084_oracle(memory_engine: object, provenance: dict[str, Any]) -> None:
    """Prove exact UCF semantics and authorized capture machinery are active."""

    if provenance.get("schema") != POLICY_SCHEMA:
        raise RuntimeError("invalid UCF oracle policy provenance")
    for hook in provenance["restored_hooks"]:
        address = int(hook["address"])
        expected = bytes.fromhex(str(hook["original_word"]))
        actual = bytes(memory_engine.read_bytes(address, 4))
        if actual != expected:
            raise RuntimeError(
                "non-UCF gameplay hook remained active "
                f"address=0x{address:08x} annotation={hook['annotation']!r} "
                f"expected={expected.hex()} actual={actual.hex()}"
            )
    for category in (
        "ucf_hooks",
        "observer_initializers",
        "observer_transport_hooks",
        "fast_forward_hooks",
        "scenario_setup_hooks",
    ):
        for hook in provenance[category]:
            address = int(hook["address"])
            if hook["code_type"] == "04":
                expected = bytes.fromhex(str(hook["runtime_proof_bytes"]))
                actual = bytes(memory_engine.read_bytes(address, len(expected)))
                if actual != expected:
                    raise RuntimeError(
                        "authorized direct-write Gecko payload mismatch "
                        f"address=0x{address:08x} expected={expected.hex()} "
                        f"actual={actual.hex()}"
                    )
                continue
            if hook["code_type"] != "C2":
                raise RuntimeError(
                    f"retained hook has unsupported codetype: 0x{address:08x}"
                )
            entry = int.from_bytes(bytes(memory_engine.read_bytes(address, 4)), "big")
            target = _branch_target(address, entry)
            proof = bytes.fromhex(str(hook["runtime_proof_bytes"]))
            proof_offset = int(hook["runtime_proof_offset"])
            if not proof:
                raise RuntimeError(
                    f"retained hook is not C2: 0x{address:08x}"
                )
            actual_proof = bytes(
                memory_engine.read_bytes(target + proof_offset, len(proof))
            )
            if actual_proof != proof:
                raise RuntimeError(
                    "retained Gecko payload mismatch "
                    f"address=0x{address:08x} target=0x{target:08x} "
                    f"offset=0x{proof_offset:x} expected={proof.hex()} "
                    f"actual={actual_proof.hex()}"
                )
    provenance["runtime_verified"] = True
