#!/usr/bin/env python3
"""Small, strict readers shared by SSBM DAT importers."""

from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class HsdArchive:
    """The immutable data block and named roots of one HSD archive."""

    data: bytes
    roots: dict[str, int]
    references: dict[str, int]

    def root(self, name: str) -> int:
        try:
            return self.roots[name]
        except KeyError as error:
            raise ValueError(f"missing HSD archive root {name!r}") from error


@dataclass(frozen=True)
class FighterWaitAnimation:
    """One weighted ftData wait-animation entry and its HSD blend bytes."""

    animation_id: int
    weight: int
    blend_frames: int
    blend_parameter: int


def fighter_wait_animations(
    archive: HsdArchive,
    fighter_root: str,
) -> tuple[FighterWaitAnimation, ...]:
    """Decode FighterData wait weights and x10 blend bytes."""

    root = archive.root(fighter_root)
    if root + 0x28 > len(archive.data):
        raise ValueError("truncated FighterData wait-animation fields")
    blend_offset = struct.unpack_from(">I", archive.data, root + 0x10)[0]
    wait_offset = struct.unpack_from(">I", archive.data, root + 0x24)[0]
    if wait_offset == 0 or blend_offset == 0:
        return ()
    if wait_offset >= len(archive.data) or blend_offset >= len(archive.data):
        raise ValueError("FighterData wait-animation pointer is out of bounds")

    rows: list[FighterWaitAnimation] = []
    seen: set[int] = set()
    for index in range(256):
        entry_offset = wait_offset + index * 8
        if entry_offset + 8 > len(archive.data):
            raise ValueError("unterminated FighterData wait-animation table")
        animation_id, weight = struct.unpack_from(">2i", archive.data, entry_offset)
        if animation_id == -1 or weight == -1:
            if animation_id != -1 or weight != -1:
                raise ValueError("malformed FighterData wait-animation sentinel")
            break
        if animation_id < 0 or animation_id in seen or weight <= 0:
            raise ValueError("invalid FighterData wait-animation entry")
        blend_entry = blend_offset + animation_id * 2
        if blend_entry + 2 > len(archive.data):
            raise ValueError("wait-animation blend entry is out of bounds")
        seen.add(animation_id)
        rows.append(
            FighterWaitAnimation(
                animation_id=animation_id,
                weight=weight,
                blend_frames=archive.data[blend_entry],
                blend_parameter=archive.data[blend_entry + 1],
            )
        )
    else:
        raise ValueError("FighterData wait-animation table is too large")
    return tuple(rows)


def _archive_name(raw: bytes, string_table: int, relative_offset: int) -> str:
    start = string_table + relative_offset
    if start < string_table or start >= len(raw):
        raise ValueError("HSD archive name offset is out of bounds")
    end = raw.find(b"\0", start)
    if end < 0:
        raise ValueError("unterminated HSD archive name")
    try:
        return raw[start:end].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII HSD archive name") from error


def read_hsd_archive(raw: bytes) -> HsdArchive:
    """Decode and validate the common HSD archive header/root tables.

    Offsets in the root and relocation tables are relative to the data block
    beginning at archive offset 0x20. Relocations are validated here even when
    a caller only needs named roots, so truncated or malformed source input
    fails before character-specific decoding begins.
    """

    if len(raw) < 0x20:
        raise ValueError("truncated HSD archive header")
    (
        file_size,
        data_size,
        relocation_count,
        root_count,
        reference_count,
    ) = struct.unpack_from(">5I", raw, 0)
    if file_size != len(raw):
        raise ValueError(
            f"HSD archive size mismatch: header={file_size} actual={len(raw)}"
        )
    data_end = 0x20 + data_size
    relocation_end = data_end + relocation_count * 4
    root_end = relocation_end + root_count * 8
    reference_end = root_end + reference_count * 8
    if not (0x20 <= data_end <= relocation_end <= root_end <= reference_end <= len(raw)):
        raise ValueError("HSD archive tables are out of bounds")

    data = raw[0x20:data_end]
    for relocation_index in range(relocation_count):
        relocation = struct.unpack_from(
            ">I", raw, data_end + relocation_index * 4
        )[0]
        if relocation + 4 > len(data):
            raise ValueError(
                f"HSD relocation {relocation_index} is out of bounds"
            )

    string_table = reference_end

    def named_entries(offset: int, count: int, kind: str) -> dict[str, int]:
        entries: dict[str, int] = {}
        for index in range(count):
            data_offset, name_offset = struct.unpack_from(
                ">2I", raw, offset + index * 8
            )
            if data_offset >= len(data):
                raise ValueError(f"HSD {kind} {index} data offset is out of bounds")
            name = _archive_name(raw, string_table, name_offset)
            if name in entries:
                raise ValueError(f"duplicate HSD {kind} name {name!r}")
            entries[name] = data_offset
        return entries

    return HsdArchive(
        data=data,
        roots=named_entries(relocation_end, root_count, "root"),
        references=named_entries(root_end, reference_count, "reference"),
    )


def ft_common_data(raw: bytes) -> tuple[bytes, tuple[int, ...]]:
    """Return PlCo.dat's data block and complete ftLoadCommonData pointers."""

    archive = read_hsd_archive(raw)
    if archive.references:
        raise ValueError("unexpected PlCo.dat reference table")
    if set(archive.roots) != {"ftLoadCommonData"}:
        raise ValueError("unexpected PlCo.dat root table")
    root_offset = archive.root("ftLoadCommonData")
    pointer_count = 23
    if root_offset + pointer_count * 4 > len(archive.data):
        raise ValueError("truncated ftLoadCommonData pointer table")
    pointers = struct.unpack_from(
        f">{pointer_count}I", archive.data, root_offset
    )
    if any(pointer >= len(archive.data) for pointer in pointers):
        raise ValueError("ftLoadCommonData pointer is out of bounds")
    return archive.data, pointers
