"""Shared, allocation-bounded routines for pinned SSBM data importers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class TimelineEvent:
    """One validated action-script command at its absolute script frame."""

    frame: int
    command_id: int
    encoded: bytes


def action_script_timeline(events: Iterable[dict[str, Any]]) -> tuple[TimelineEvent, ...]:
    """Return validated action-script commands with absolute frame ownership.

    Command 0x08 sets the absolute frame and command 0x04 advances it.  Keeping
    this primitive character-independent prevents each importer from growing a
    subtly different interpretation of FigaTree action clocks.
    """

    frame = 0
    result: list[TimelineEvent] = []
    for event_index, event in enumerate(events):
        command_id = int(str(event["commandId"]), 16)
        encoded = bytes.fromhex(str(event["bytes"]))
        byte_count = int(event["length"])
        if (
            byte_count == 0
            or byte_count != len(encoded)
            or byte_count % 4 != 0
            or byte_count > 0xFF
        ):
            raise ValueError(
                f"action-script event {event_index}: invalid encoded length"
            )
        if command_id < 0 or command_id > 0xFF or encoded[0] & 0xFC != command_id:
            raise ValueError(
                f"action-script event {event_index}: opcode does not match bytes"
            )
        argument = int.from_bytes(encoded, "big") & 0xFFFFFF
        if command_id == 0x08:
            frame = argument
        elif command_id == 0x04:
            frame += argument
        if frame > 0xFFFF:
            raise ValueError(
                f"action-script event {event_index}: frame exceeds uint16_t"
            )
        result.append(TimelineEvent(frame, command_id, encoded))
    return tuple(result)
