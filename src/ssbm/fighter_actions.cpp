#include "fighter_actions.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 64;
constexpr std::uint32_t fighter_record_bytes = 32;
constexpr std::uint32_t node_record_bytes = 8;
constexpr std::uint32_t track_record_bytes = 32;

[[nodiscard]] std::uint16_t read_u16(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    return static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[native_offset]) |
        (static_cast<std::uint16_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 1])) << 8U));
}

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint32_t value = 0;
    for (std::uint32_t byte = 0; byte < 4; ++byte) {
        value |= static_cast<std::uint32_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint64_t value = 0;
    for (std::uint32_t byte = 0; byte < 8; ++byte) {
        value |= static_cast<std::uint64_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t total) noexcept
{
    return offset <= total && size <= total - offset;
}

[[nodiscard]] bool multiply_fits(
    std::uint64_t count,
    std::uint64_t stride,
    std::uint64_t& result) noexcept
{
    if (count != 0 && stride > std::numeric_limits<std::uint64_t>::max() / count) {
        return false;
    }
    result = count * stride;
    return true;
}

} // namespace

bool FighterActionsView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::animation_data ||
        section.schema_version != fighter_actions_schema ||
        section.stride != fighter_action_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != fighter_actions_schema ||
        read_u32(section.bytes, 12) != fighter_record_bytes ||
        read_u32(section.bytes, 16) != fighter_action_record_bytes ||
        read_u32(section.bytes, 20) != node_record_bytes ||
        read_u32(section.bytes, 24) != track_record_bytes) {
        return false;
    }
    fighter_count_ = read_u32(section.bytes, 4);
    action_count_ = read_u32(section.bytes, 8);
    fighters_offset_ = read_u64(section.bytes, 32);
    actions_offset_ = read_u64(section.bytes, 40);
    blob_offset_ = read_u64(section.bytes, 48);
    blob_size_ = read_u64(section.bytes, 56);
    std::uint64_t fighter_bytes = 0;
    std::uint64_t action_bytes = 0;
    if (section.count != action_count_ ||
        !multiply_fits(fighter_count_, fighter_record_bytes, fighter_bytes) ||
        !multiply_fits(action_count_, fighter_action_record_bytes, action_bytes) ||
        !range_fits(fighters_offset_, fighter_bytes, section.bytes.size()) ||
        !range_fits(actions_offset_, action_bytes, section.bytes.size()) ||
        !range_fits(blob_offset_, blob_size_, section.bytes.size()) ||
        fighters_offset_ < header_bytes ||
        actions_offset_ < fighters_offset_ + fighter_bytes ||
        blob_offset_ < actions_offset_ + action_bytes) {
        *this = {};
        return false;
    }
    section_ = section;

    std::uint32_t expected_first = 0;
    for (std::uint32_t fighter_index = 0;
         fighter_index < fighter_count_;
         ++fighter_index) {
        const auto fighter_offset = fighters_offset_ +
            static_cast<std::uint64_t>(fighter_index) * fighter_record_bytes;
        const auto raw_action_offset = read_u64(section.bytes, fighter_offset + 16);
        const auto candidate = fighter(fighter_index);
        if (raw_action_offset < actions_offset_ ||
            (raw_action_offset - actions_offset_) % fighter_action_record_bytes != 0U ||
            candidate.first_action != expected_first ||
            candidate.action_count > action_count_ - expected_first) {
            *this = {};
            return false;
        }
        expected_first += candidate.action_count;
    }
    if (expected_first != action_count_) {
        *this = {};
        return false;
    }

    for (std::uint32_t action_index = 0;
         action_index < action_count_;
         ++action_index) {
        const auto record_offset = actions_offset_ +
            static_cast<std::uint64_t>(action_index) * fighter_action_record_bytes;
        const auto name_offset = read_u64(section.bytes, record_offset);
        const auto name_size = read_u32(section.bytes, record_offset + 8);
        const auto script_offset = read_u64(section.bytes, record_offset + 24);
        const auto script_size = read_u32(section.bytes, record_offset + 32);
        const auto has_animation = read_u32(section.bytes, record_offset + 36);
        const auto nodes_offset = read_u64(section.bytes, record_offset + 48);
        const auto node_count = read_u32(section.bytes, record_offset + 56);
        const auto tracks_offset = read_u64(section.bytes, record_offset + 64);
        const auto track_count = read_u32(section.bytes, record_offset + 72);
        std::uint64_t node_bytes = 0;
        std::uint64_t track_bytes = 0;
        if (!range_fits(name_offset, name_size, section.bytes.size()) ||
            !range_fits(script_offset, script_size, section.bytes.size()) ||
            name_offset < blob_offset_ || script_offset < blob_offset_ ||
            name_offset + name_size > blob_offset_ + blob_size_ ||
            script_offset + script_size > blob_offset_ + blob_size_ ||
            has_animation > 1U ||
            !multiply_fits(node_count, node_record_bytes, node_bytes) ||
            !multiply_fits(track_count, track_record_bytes, track_bytes) ||
            (has_animation == 0U &&
             (node_count != 0U || track_count != 0U ||
              nodes_offset != 0U || tracks_offset != 0U)) ||
            (has_animation != 0U &&
             (!range_fits(nodes_offset, node_bytes, section.bytes.size()) ||
              !range_fits(tracks_offset, track_bytes, section.bytes.size()) ||
              nodes_offset < blob_offset_ || tracks_offset < blob_offset_ ||
              nodes_offset + node_bytes > blob_offset_ + blob_size_ ||
              tracks_offset + track_bytes > blob_offset_ + blob_size_))) {
            *this = {};
            return false;
        }
        for (std::uint32_t node_index = 0; node_index < node_count; ++node_index) {
            const auto offset = nodes_offset +
                static_cast<std::uint64_t>(node_index) * node_record_bytes;
            const auto first = read_u32(section.bytes, offset);
            const auto count = read_u32(section.bytes, offset + 4);
            if (first > track_count || count > track_count - first) {
                *this = {};
                return false;
            }
        }
        for (std::uint32_t track_index = 0; track_index < track_count; ++track_index) {
            const auto offset = tracks_offset +
                static_cast<std::uint64_t>(track_index) * track_record_bytes;
            const auto data_length = read_u16(section.bytes, offset);
            const auto buffer_offset = read_u64(section.bytes, offset + 16);
            const auto buffer_size = read_u32(section.bytes, offset + 24);
            if (buffer_size != data_length ||
                !range_fits(buffer_offset, buffer_size, section.bytes.size()) ||
                buffer_offset < blob_offset_ ||
                buffer_offset + buffer_size > blob_offset_ + blob_size_) {
                *this = {};
                return false;
            }
        }
    }
    return true;
}

bool FighterActionsView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint32_t FighterActionsView::fighter_count() const noexcept
{
    return fighter_count_;
}

std::uint32_t FighterActionsView::action_count() const noexcept
{
    return action_count_;
}

FighterActionFileRecord FighterActionsView::fighter(std::uint32_t index) const noexcept
{
    if (!valid() || index >= fighter_count_) {
        return {};
    }
    const auto offset = fighters_offset_ +
        static_cast<std::uint64_t>(index) * fighter_record_bytes;
    const auto action_offset = read_u64(section_.bytes, offset + 16);
    if (action_offset < actions_offset_) {
        return {};
    }
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        static_cast<std::uint32_t>(
            (action_offset - actions_offset_) / fighter_action_record_bytes),
        read_u32(section_.bytes, offset + 24),
    };
}

FighterActionFileRecord FighterActionsView::find(
    std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < fighter_count_; ++index) {
        const auto candidate = fighter(index);
        if (candidate.file_name_hash == file_name_hash) {
            return candidate;
        }
    }
    return {};
}

FighterActionRecord FighterActionsView::action(std::uint32_t index) const noexcept
{
    if (!valid() || index >= action_count_) {
        return {};
    }
    const auto offset = actions_offset_ +
        static_cast<std::uint64_t>(index) * fighter_action_record_bytes;
    const auto name_offset = read_u64(section_.bytes, offset);
    const auto name_size = read_u32(section_.bytes, offset + 8);
    const auto script_offset = read_u64(section_.bytes, offset + 24);
    const auto script_size = read_u32(section_.bytes, offset + 32);
    const auto nodes_offset = read_u64(section_.bytes, offset + 48);
    const auto tracks_offset = read_u64(section_.bytes, offset + 64);
    return {
        {reinterpret_cast<const char*>(section_.bytes.data() + name_offset), name_size},
        read_u32(section_.bytes, offset + 12),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 16)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 20)),
        section_.bytes.subspan(
            static_cast<std::size_t>(script_offset), script_size),
        read_u32(section_.bytes, offset + 36) != 0,
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 40)),
        read_u32(section_.bytes, offset + 44),
        nodes_offset,
        read_u32(section_.bytes, offset + 56),
        tracks_offset,
        read_u32(section_.bytes, offset + 72),
    };
}

FighterAnimationNodeRecord FighterActionsView::node(
    const FighterActionRecord& action_record,
    std::uint32_t index) const noexcept
{
    if (!valid() || !action_record.has_animation ||
        index >= action_record.node_count) {
        return {};
    }
    const auto offset = action_record.nodes_offset +
        static_cast<std::uint64_t>(index) * node_record_bytes;
    if (!range_fits(offset, node_record_bytes, section_.bytes.size())) {
        return {};
    }
    return {read_u32(section_.bytes, offset), read_u32(section_.bytes, offset + 4)};
}

FighterAnimationTrackRecord FighterActionsView::track(
    const FighterActionRecord& action_record,
    std::uint32_t index) const noexcept
{
    if (!valid() || !action_record.has_animation ||
        index >= action_record.track_count) {
        return {};
    }
    const auto offset = action_record.tracks_offset +
        static_cast<std::uint64_t>(index) * track_record_bytes;
    if (!range_fits(offset, track_record_bytes, section_.bytes.size())) {
        return {};
    }
    const auto buffer_offset = read_u64(section_.bytes, offset + 16);
    const auto buffer_size = read_u32(section_.bytes, offset + 24);
    return {
        read_u16(section_.bytes, offset),
        std::bit_cast<std::int16_t>(read_u16(section_.bytes, offset + 2)),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 4)]),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 5)]),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 6)]),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        section_.bytes.subspan(
            static_cast<std::size_t>(buffer_offset), buffer_size),
    };
}

} // namespace pf::ssbm
