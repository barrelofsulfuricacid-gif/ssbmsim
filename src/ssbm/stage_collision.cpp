#include "stage_collision.h"

#include <bit>
#include <cstddef>

namespace pf::ssbm {
namespace {

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    return static_cast<std::uint32_t>(
               std::to_integer<std::uint8_t>(bytes[native_offset])) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 1])) << 8U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 2])) << 16U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 3])) << 24U);
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    return static_cast<std::uint64_t>(read_u32(bytes, offset)) |
        (static_cast<std::uint64_t>(read_u32(bytes, offset + 4)) << 32U);
}

[[nodiscard]] std::int16_t read_i16(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    const auto value = static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[native_offset]) |
        (static_cast<std::uint16_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 1])) << 8U));
    return std::bit_cast<std::int16_t>(value);
}

[[nodiscard]] StageCollisionRange read_range(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    return {read_i16(bytes, offset), read_i16(bytes, offset + 2)};
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t capacity) noexcept
{
    const auto cap = static_cast<std::uint64_t>(capacity);
    return offset <= cap && size <= cap - offset;
}

[[nodiscard]] bool indexed_range_fits(
    StageCollisionRange range,
    std::uint32_t count) noexcept
{
    return range.offset >= 0 && range.count >= 0 &&
        static_cast<std::uint32_t>(range.offset) <= count &&
        static_cast<std::uint32_t>(range.count) <=
            count - static_cast<std::uint32_t>(range.offset);
}

} // namespace

float StageCollisionVertex::x() const noexcept
{
    return std::bit_cast<float>(x_bits);
}

float StageCollisionVertex::y() const noexcept
{
    return std::bit_cast<float>(y_bits);
}

float StageCollisionGroup::x_min() const noexcept
{
    return std::bit_cast<float>(x_min_bits);
}

float StageCollisionGroup::y_min() const noexcept
{
    return std::bit_cast<float>(y_min_bits);
}

float StageCollisionGroup::x_max() const noexcept
{
    return std::bit_cast<float>(x_max_bits);
}

float StageCollisionGroup::y_max() const noexcept
{
    return std::bit_cast<float>(y_max_bits);
}

bool StageCollisionView::open(SectionView section) noexcept
{
    section_ = {};
    count_ = 0;
    records_offset_ = 0;
    if (section.kind != SectionKind::stage_data ||
        section.schema_version != stage_collision_schema ||
        section.stride != stage_collision_record_bytes ||
        section.bytes.size() < 48 ||
        read_u32(section.bytes, 0) != stage_collision_schema ||
        read_u32(section.bytes, 8) != stage_collision_record_bytes ||
        read_u32(section.bytes, 12) != stage_collision_vertex_bytes ||
        read_u32(section.bytes, 16) != stage_collision_line_bytes ||
        read_u32(section.bytes, 20) != stage_collision_group_bytes ||
        read_u64(section.bytes, 40) != 0) {
        return false;
    }
    const auto count = read_u32(section.bytes, 4);
    const auto records_offset = read_u64(section.bytes, 24);
    const auto payload_offset = read_u64(section.bytes, 32);
    const auto records_size =
        static_cast<std::uint64_t>(count) * stage_collision_record_bytes;
    if (count != section.count ||
        !range_fits(records_offset, records_size, section.bytes.size()) ||
        payload_offset < records_offset + records_size ||
        payload_offset > section.bytes.size()) {
        return false;
    }

    section_ = section;
    count_ = count;
    records_offset_ = records_offset;
    for (std::uint32_t index = 0; index < count; ++index) {
        const auto stage = record(index);
        if (stage.file_name_hash == 0 ||
            read_u32(section.bytes, static_cast<std::size_t>(records_offset +
                static_cast<std::uint64_t>(index) * stage_collision_record_bytes + 28)) != 0 ||
            read_u32(section.bytes, static_cast<std::size_t>(records_offset +
                static_cast<std::uint64_t>(index) * stage_collision_record_bytes + 44)) != 0 ||
            read_u32(section.bytes, static_cast<std::size_t>(records_offset +
                static_cast<std::uint64_t>(index) * stage_collision_record_bytes + 60)) != 0 ||
            read_u32(section.bytes, static_cast<std::size_t>(records_offset +
                static_cast<std::uint64_t>(index) * stage_collision_record_bytes + 84)) != 0 ||
            read_u64(section.bytes, static_cast<std::size_t>(records_offset +
                static_cast<std::uint64_t>(index) * stage_collision_record_bytes + 88)) != 0 ||
            !range_fits(stage.vertices_offset,
                static_cast<std::uint64_t>(stage.vertex_count) * stage_collision_vertex_bytes,
                section.bytes.size()) ||
            !range_fits(stage.lines_offset,
                static_cast<std::uint64_t>(stage.line_count) * stage_collision_line_bytes,
                section.bytes.size()) ||
            !range_fits(stage.groups_offset,
                static_cast<std::uint64_t>(stage.group_count) * stage_collision_group_bytes,
                section.bytes.size()) ||
            !indexed_range_fits(stage.top, stage.line_count) ||
            !indexed_range_fits(stage.bottom, stage.line_count) ||
            !indexed_range_fits(stage.right, stage.line_count) ||
            !indexed_range_fits(stage.left, stage.line_count) ||
            !indexed_range_fits(stage.dynamic, stage.line_count)) {
            section_ = {};
            count_ = 0;
            records_offset_ = 0;
            return false;
        }
        for (std::uint32_t line_index = 0; line_index < stage.line_count; ++line_index) {
            const auto candidate = line(stage, line_index);
            if (candidate.vertex_1 < 0 || candidate.vertex_2 < 0 ||
                static_cast<std::uint32_t>(candidate.vertex_1) >= stage.vertex_count ||
                static_cast<std::uint32_t>(candidate.vertex_2) >= stage.vertex_count) {
                section_ = {};
                count_ = 0;
                records_offset_ = 0;
                return false;
            }
        }
        for (std::uint32_t group_index = 0; group_index < stage.group_count; ++group_index) {
            const auto candidate = group(stage, group_index);
            if (!indexed_range_fits(candidate.top, stage.line_count) ||
                !indexed_range_fits(candidate.bottom, stage.line_count) ||
                !indexed_range_fits(candidate.right, stage.line_count) ||
                !indexed_range_fits(candidate.left, stage.line_count) ||
                !indexed_range_fits(candidate.dynamic, stage.line_count) ||
                !indexed_range_fits(candidate.vertices, stage.vertex_count)) {
                section_ = {};
                count_ = 0;
                records_offset_ = 0;
                return false;
            }
        }
    }
    return true;
}

bool StageCollisionView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint32_t StageCollisionView::count() const noexcept
{
    return count_;
}

StageCollisionRecord StageCollisionView::record(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) {
        return {};
    }
    const auto offset = records_offset_ +
        static_cast<std::uint64_t>(index) * stage_collision_record_bytes;
    const auto base = static_cast<std::size_t>(offset);
    return {
        read_u64(section_.bytes, base),
        read_u64(section_.bytes, base + 8),
        read_u64(section_.bytes, base + 16),
        read_u32(section_.bytes, base + 24),
        read_u64(section_.bytes, base + 32),
        read_u32(section_.bytes, base + 40),
        read_u64(section_.bytes, base + 48),
        read_u32(section_.bytes, base + 56),
        read_range(section_.bytes, base + 64),
        read_range(section_.bytes, base + 68),
        read_range(section_.bytes, base + 72),
        read_range(section_.bytes, base + 76),
        read_range(section_.bytes, base + 80),
    };
}

StageCollisionRecord StageCollisionView::find(std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto candidate = record(index);
        if (candidate.file_name_hash == file_name_hash) {
            return candidate;
        }
    }
    return {};
}

StageCollisionVertex StageCollisionView::vertex(
    const StageCollisionRecord& stage,
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= stage.vertex_count) {
        return {};
    }
    const auto offset = static_cast<std::size_t>(stage.vertices_offset) +
        index * stage_collision_vertex_bytes;
    return {read_u32(section_.bytes, offset), read_u32(section_.bytes, offset + 4)};
}

StageCollisionLine StageCollisionView::line(
    const StageCollisionRecord& stage,
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= stage.line_count) {
        return {};
    }
    const auto offset = static_cast<std::size_t>(stage.lines_offset) +
        index * stage_collision_line_bytes;
    return {
        read_i16(section_.bytes, offset),
        read_i16(section_.bytes, offset + 2),
        read_i16(section_.bytes, offset + 4),
        read_i16(section_.bytes, offset + 6),
        read_i16(section_.bytes, offset + 8),
        read_i16(section_.bytes, offset + 10),
        read_i16(section_.bytes, offset + 12),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 14)]),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 15)]),
    };
}

StageCollisionGroup StageCollisionView::group(
    const StageCollisionRecord& stage,
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= stage.group_count) {
        return {};
    }
    const auto offset = static_cast<std::size_t>(stage.groups_offset) +
        index * stage_collision_group_bytes;
    return {
        read_range(section_.bytes, offset),
        read_range(section_.bytes, offset + 4),
        read_range(section_.bytes, offset + 8),
        read_range(section_.bytes, offset + 12),
        read_range(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u32(section_.bytes, offset + 32),
        read_range(section_.bytes, offset + 36),
    };
}

} // namespace pf::ssbm
