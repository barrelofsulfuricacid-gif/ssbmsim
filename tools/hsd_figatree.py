#!/usr/bin/env python3
"""Read the numeric joint tracks in an HSD FigaTree animation archive.

The implementation is intentionally small: it parses only the archive,
FigaTree, and compressed scalar-track structures needed by the Falcon data
importer. The format interpretation is checked against HSDLib revision
29546ad77fdf9ebd9a9940ed44903ef309e810d6 and the pinned Melee decomp.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct


TRACK_TRANSLATE_X = 5
TRACK_TRANSLATE_Y = 6
TRACK_TRANSLATE_Z = 7

INTERPOLATION_CONSTANT = 1
INTERPOLATION_LINEAR = 2
INTERPOLATION_SPLINE_ZERO = 3
INTERPOLATION_SPLINE = 4
INTERPOLATION_SLOPE = 5
INTERPOLATION_KEY = 6

FORMAT_FLOAT = 0x00
FORMAT_S16 = 0x20
FORMAT_U16 = 0x40
FORMAT_S8 = 0x60
FORMAT_U8 = 0x80


@dataclass(frozen=True)
class Key:
    frame: float
    value: float
    tangent: float
    interpolation: int


@dataclass(frozen=True)
class Track:
    track_type: int
    start_frame: int
    keys: tuple[Key, ...]


@dataclass(frozen=True)
class FigaTree:
    frame_count: float
    nodes: tuple[tuple[Track, ...], ...]


class _BufferReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("truncated HSD animation track")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def packed(self) -> int:
        result = 0
        shift = 0
        while True:
            value = self._take(1)[0]
            result |= (value & 0x7F) << shift
            if value & 0x80 == 0:
                return result
            shift += 7
            if shift > 28:
                raise ValueError("oversized HSD packed integer")

    def scalar(self, value_format: int, scale: int) -> float:
        if value_format == FORMAT_FLOAT:
            return float(struct.unpack("<f", self._take(4))[0])
        if value_format == FORMAT_S16:
            return struct.unpack("<h", self._take(2))[0] / scale
        if value_format == FORMAT_U16:
            return struct.unpack("<H", self._take(2))[0] / scale
        if value_format == FORMAT_S8:
            return struct.unpack("<b", self._take(1))[0] / scale
        if value_format == FORMAT_U8:
            return self._take(1)[0] / scale
        raise ValueError(f"unsupported HSD scalar format 0x{value_format:02x}")


def _decode_track(
    buffer: bytes,
    track_type: int,
    start_frame: int,
    value_flags: int,
    tangent_flags: int,
) -> Track:
    reader = _BufferReader(buffer)
    value_format = value_flags & 0xE0
    tangent_format = tangent_flags & 0xE0
    value_scale = 1 << (value_flags & 0x1F)
    tangent_scale = 1 << (tangent_flags & 0x1F)
    clock = 0.0
    keys: list[Key] = []

    while reader.offset < len(buffer):
        header = reader.packed()
        interpolation = header & 0x0F
        if interpolation == 0:
            break
        key_count = (header >> 4) + 1
        for _ in range(key_count):
            value = 0.0
            tangent = 0.0
            duration = 0
            if interpolation in {
                INTERPOLATION_CONSTANT,
                INTERPOLATION_LINEAR,
                INTERPOLATION_SPLINE_ZERO,
            }:
                value = reader.scalar(value_format, value_scale)
                duration = reader.packed()
            elif interpolation == INTERPOLATION_SPLINE:
                value = reader.scalar(value_format, value_scale)
                tangent = reader.scalar(tangent_format, tangent_scale)
                duration = reader.packed()
            elif interpolation == INTERPOLATION_SLOPE:
                tangent = reader.scalar(tangent_format, tangent_scale)
            elif interpolation == INTERPOLATION_KEY:
                value = reader.scalar(value_format, value_scale)
            else:
                raise ValueError(
                    f"unsupported HSD interpolation {interpolation}"
                )
            keys.append(Key(clock, value, tangent, interpolation))
            clock += duration

    return Track(track_type, start_frame, tuple(keys))


def decode_figatree(archive: bytes) -> FigaTree:
    """Decode a standalone animation DAT sliced from ``PlCaAJ.dat``."""

    if len(archive) < 0x20:
        raise ValueError("truncated HSD archive header")
    (
        file_size,
        data_size,
        relocation_count,
        root_count,
        reference_count,
        _,
        _,
        _,
    ) = struct.unpack_from(">8I", archive, 0)
    if file_size > len(archive) or root_count + reference_count == 0:
        raise ValueError("invalid HSD animation archive")
    data = archive[0x20:0x20 + data_size]
    roots_offset = 0x20 + data_size + relocation_count * 4
    root_offset = struct.unpack_from(">I", archive, roots_offset)[0]
    if root_offset + 0x14 > len(data):
        raise ValueError("invalid HSD FigaTree root")
    _, _, frame_count, count_table_offset, track_table_offset = (
        struct.unpack_from(">2If2I", data, root_offset)
    )

    track_counts: list[int] = []
    cursor = count_table_offset
    while cursor < len(data) and data[cursor] != 0xFF:
        track_counts.append(data[cursor])
        cursor += 1
    if cursor >= len(data):
        raise ValueError("unterminated HSD FigaTree node table")

    nodes: list[tuple[Track, ...]] = []
    track_index = 0
    for track_count in track_counts:
        tracks: list[Track] = []
        for _ in range(track_count):
            offset = track_table_offset + track_index * 0x0C
            if offset + 0x0C > len(data):
                raise ValueError("truncated HSD FigaTree track table")
            (
                data_length,
                start_frame,
                track_type,
                value_flags,
                tangent_flags,
                _,
                buffer_offset,
            ) = struct.unpack_from(">Hh4BI", data, offset)
            end = buffer_offset + data_length
            if end > len(data):
                raise ValueError("invalid HSD FigaTree track buffer")
            tracks.append(
                _decode_track(
                    data[buffer_offset:end],
                    track_type,
                    start_frame,
                    value_flags,
                    tangent_flags,
                )
            )
            track_index += 1
        nodes.append(tuple(tracks))
    return FigaTree(float(frame_count), tuple(nodes))


def sample_track(track: Track, frame: float) -> float:
    """Evaluate a decoded scalar track with HSD's interpolation rules."""

    # HSD_FObjReqAnim initializes time to fobj->startframe + requested_frame.
    # This is an additive phase offset, not a delay.
    frame += track.start_frame
    keys = track.keys
    if not keys:
        return 0.0
    if len(keys) > 1 and frame >= keys[-1].frame:
        return keys[-1].value

    p0 = p1 = d0 = d1 = t0 = t1 = 0.0
    interpolation = previous_interpolation = INTERPOLATION_CONSTANT
    for key in keys:
        previous_interpolation = interpolation
        interpolation = key.interpolation
        if interpolation in {INTERPOLATION_CONSTANT, INTERPOLATION_LINEAR}:
            p0, p1 = p1, key.value
            if previous_interpolation != INTERPOLATION_SLOPE:
                d0, d1 = d1, 0.0
            t0, t1 = t1, key.frame
        elif interpolation == INTERPOLATION_SPLINE_ZERO:
            p0, d0, p1, d1 = p1, d1, key.value, 0.0
            t0, t1 = t1, key.frame
        elif interpolation == INTERPOLATION_SPLINE:
            p0, p1, d0, d1 = p1, key.value, d1, key.tangent
            t0, t1 = t1, key.frame
        elif interpolation == INTERPOLATION_SLOPE:
            d0, d1 = d1, key.tangent
        elif interpolation == INTERPOLATION_KEY:
            p0 = p1 = key.value
        if t1 > frame and interpolation != INTERPOLATION_SLOPE:
            break
        previous_interpolation = interpolation

    if frame <= t0:
        return p0
    if frame >= t1:
        return p1
    if t0 == t1 or previous_interpolation in {
        INTERPOLATION_CONSTANT,
        INTERPOLATION_KEY,
    }:
        return p0
    elapsed = frame - t0
    duration = t1 - t0
    if previous_interpolation == INTERPOLATION_LINEAR:
        return p0 + (p1 - p0) * elapsed / duration
    normalized = elapsed / duration
    h00 = 2 * normalized**3 - 3 * normalized**2 + 1
    h10 = normalized**3 - 2 * normalized**2 + normalized
    h01 = -2 * normalized**3 + 3 * normalized**2
    h11 = normalized**3 - normalized**2
    return h00 * p0 + h10 * duration * d0 + h01 * p1 + h11 * duration * d1
