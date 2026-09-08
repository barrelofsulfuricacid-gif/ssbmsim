#include "stage_map_heads.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint64_t header_bytes = 96;

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native = static_cast<std::size_t>(offset);
    return static_cast<std::uint32_t>(
               std::to_integer<std::uint8_t>(bytes[native])) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native + 1])) << 8U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native + 2])) << 16U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native + 3])) << 24U);
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
    const auto native = static_cast<std::size_t>(offset);
    const auto bits = static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[native]) |
        (static_cast<std::uint16_t>(
             std::to_integer<std::uint8_t>(bytes[native + 1])) << 8U));
    return std::bit_cast<std::int16_t>(bits);
}

[[nodiscard]] std::int32_t read_i32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    return std::bit_cast<std::int32_t>(read_u32(bytes, offset));
}

[[nodiscard]] bool multiply_fits(
    std::uint64_t count,
    std::uint64_t stride,
    std::uint64_t& result) noexcept
{
    if (count != 0 && stride > std::numeric_limits<std::uint64_t>::max() / count)
        return false;
    result = count * stride;
    return true;
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t capacity) noexcept
{
    return offset <= capacity && size <= capacity - offset;
}

[[nodiscard]] bool index_range_fits(
    std::uint32_t first,
    std::uint32_t count,
    std::uint32_t capacity) noexcept
{
    return first <= capacity && count <= capacity - first;
}

[[nodiscard]] std::uint64_t align8(std::uint64_t value) noexcept
{
    return (value + 7U) & ~std::uint64_t{7U};
}

} // namespace

bool StageModelGroupRecord::root_node_present() const noexcept
{
    return (presence_flags & (1U << 0U)) != 0U;
}

bool StageModelGroupRecord::camera_present() const noexcept
{
    return (presence_flags & (1U << 1U)) != 0U;
}

bool StageModelGroupRecord::fog_present() const noexcept
{
    return (presence_flags & (1U << 2U)) != 0U;
}

bool StageMapHeadsView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::stage_data ||
        section.schema_version != stage_map_head_schema ||
        section.stride != stage_map_head_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != stage_map_head_schema ||
        read_u32(section.bytes, 24) != stage_map_head_record_bytes ||
        read_u32(section.bytes, 28) != stage_general_group_record_bytes ||
        read_u32(section.bytes, 32) != stage_general_point_record_bytes ||
        read_u32(section.bytes, 36) != stage_model_group_record_bytes ||
        read_u32(section.bytes, 40) != stage_map_collision_link_record_bytes) {
        return false;
    }

    count_ = read_u32(section.bytes, 4);
    general_group_count_ = read_u32(section.bytes, 8);
    general_point_count_ = read_u32(section.bytes, 12);
    model_group_count_ = read_u32(section.bytes, 16);
    collision_link_count_ = read_u32(section.bytes, 20);
    jobj_link_count_ = read_u32(section.bytes, 44);
    maps_offset_ = read_u64(section.bytes, 48);
    general_groups_offset_ = read_u64(section.bytes, 56);
    general_points_offset_ = read_u64(section.bytes, 64);
    model_groups_offset_ = read_u64(section.bytes, 72);
    collision_links_offset_ = read_u64(section.bytes, 80);
    jobj_links_offset_ = read_u64(section.bytes, 88);
    std::uint64_t map_bytes = 0;
    std::uint64_t general_group_bytes = 0;
    std::uint64_t general_point_bytes = 0;
    std::uint64_t model_group_bytes = 0;
    std::uint64_t collision_link_bytes = 0;
    std::uint64_t jobj_link_bytes = 0;
    if (count_ != section.count ||
        !multiply_fits(count_, stage_map_head_record_bytes, map_bytes) ||
        !multiply_fits(general_group_count_, stage_general_group_record_bytes,
            general_group_bytes) ||
        !multiply_fits(general_point_count_, stage_general_point_record_bytes,
            general_point_bytes) ||
        !multiply_fits(model_group_count_, stage_model_group_record_bytes,
            model_group_bytes) ||
        !multiply_fits(collision_link_count_,
            stage_map_collision_link_record_bytes, collision_link_bytes) ||
        !multiply_fits(jobj_link_count_, stage_map_jobj_link_record_bytes,
            jobj_link_bytes) ||
        maps_offset_ < header_bytes ||
        general_groups_offset_ < maps_offset_ + map_bytes ||
        general_points_offset_ < general_groups_offset_ + general_group_bytes ||
        model_groups_offset_ < general_points_offset_ + general_point_bytes ||
        collision_links_offset_ < model_groups_offset_ + model_group_bytes ||
        jobj_links_offset_ < collision_links_offset_ + collision_link_bytes ||
        !range_fits(jobj_links_offset_, jobj_link_bytes,
            section.bytes.size())) {
        *this = {};
        return false;
    }
    section_ = section;

    std::uint32_t expected_general_group = 0;
    std::uint32_t expected_model_group = 0;
    std::uint32_t expected_general_point = 0;
    std::uint32_t expected_collision_link = 0;
    std::uint32_t expected_jobj_link = 0;
    std::uint64_t expected_animation_flag = align8(
        jobj_links_offset_ + jobj_link_bytes);
    for (std::uint32_t map_index = 0; map_index < count_; ++map_index) {
        const auto candidate = map(map_index);
        const auto raw_offset = maps_offset_ +
            static_cast<std::uint64_t>(map_index) * stage_map_head_record_bytes;
        if (candidate.file_name_hash == 0 || candidate.root_name_hash == 0 ||
            candidate.first_general_group != expected_general_group ||
            candidate.first_model_group != expected_model_group ||
            !index_range_fits(candidate.first_general_group,
                candidate.general_group_count, general_group_count_) ||
            !index_range_fits(candidate.first_model_group,
                candidate.model_group_count, model_group_count_) ||
            read_u64(section.bytes, raw_offset + 48) != 0U ||
            read_u64(section.bytes, raw_offset + 56) != 0U) {
            *this = {};
            return false;
        }
        for (std::uint32_t local = 0; local < candidate.general_group_count; ++local) {
            const auto group = general_group(candidate.first_general_group + local);
            const auto group_offset = general_groups_offset_ +
                static_cast<std::uint64_t>(candidate.first_general_group + local) *
                    stage_general_group_record_bytes;
            if (group.joint_tree_name_hash == 0 ||
                group.first_point != expected_general_point ||
                !index_range_fits(group.first_point, group.point_count,
                    general_point_count_) ||
                read_u32(section.bytes, group_offset + 16) > 1U ||
                group.linked_model_group < -1 ||
                group.linked_model_group >=
                    static_cast<std::int32_t>(candidate.model_group_count) ||
                read_u32(section.bytes, group_offset + 24) != 0U ||
                read_u32(section.bytes, group_offset + 28) != 0U) {
                *this = {};
                return false;
            }
            for (std::uint32_t point = 0; point < group.point_count; ++point) {
                const auto point_offset = general_points_offset_ +
                    static_cast<std::uint64_t>(group.first_point + point) *
                        stage_general_point_record_bytes;
                if (read_u32(section.bytes, point_offset + 4) != 0U) {
                    *this = {};
                    return false;
                }
            }
            expected_general_point += group.point_count;
        }
        for (std::uint32_t local = 0; local < candidate.model_group_count; ++local) {
            const auto group = model_group(candidate.first_model_group + local);
            const auto group_offset = model_groups_offset_ +
                static_cast<std::uint64_t>(candidate.first_model_group + local) *
                    stage_model_group_record_bytes;
            if (group.joint_tree_name_hash == 0 ||
                group.first_collision_link != expected_collision_link ||
                !index_range_fits(group.first_collision_link,
                    group.collision_link_count, collision_link_count_) ||
                group.first_jobj_link != expected_jobj_link ||
                !index_range_fits(group.first_jobj_link,
                    group.jobj_link_count, jobj_link_count_) ||
                (group.presence_flags & ~0x1FU) != 0U ||
                read_u32(section.bytes, group_offset + 44) != 0U ||
                group.animation_flags_offset != expected_animation_flag ||
                !range_fits(group.animation_flags_offset,
                    group.animation_flag_count, section.bytes.size()) ||
                read_u32(section.bytes, group_offset + 60) != 0U) {
                *this = {};
                return false;
            }
            const auto link_end = group.first_collision_link +
                group.collision_link_count;
            for (auto link = group.first_collision_link; link < link_end; ++link) {
                const auto link_offset = collision_links_offset_ +
                    static_cast<std::uint64_t>(link) *
                        stage_map_collision_link_record_bytes;
                if (read_u32(section.bytes, link_offset + 4) >> 16U != 0U) {
                    *this = {};
                    return false;
                }
            }
            expected_collision_link = link_end;
            expected_jobj_link += group.jobj_link_count;
            expected_animation_flag += group.animation_flag_count;
        }
        expected_general_group += candidate.general_group_count;
        expected_model_group += candidate.model_group_count;
    }
    if (expected_general_group != general_group_count_ ||
        expected_general_point != general_point_count_ ||
        expected_model_group != model_group_count_ ||
        expected_collision_link != collision_link_count_ ||
        expected_jobj_link != jobj_link_count_ ||
        expected_animation_flag != section.bytes.size()) {
        *this = {};
        return false;
    }
    return true;
}

bool StageMapHeadsView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t StageMapHeadsView::count() const noexcept { return count_; }
std::uint32_t StageMapHeadsView::general_group_count() const noexcept
{
    return general_group_count_;
}
std::uint32_t StageMapHeadsView::general_point_count() const noexcept
{
    return general_point_count_;
}
std::uint32_t StageMapHeadsView::model_group_count() const noexcept
{
    return model_group_count_;
}
std::uint32_t StageMapHeadsView::collision_link_count() const noexcept
{
    return collision_link_count_;
}
std::uint32_t StageMapHeadsView::jobj_link_count() const noexcept
{
    return jobj_link_count_;
}

StageMapHeadRecord StageMapHeadsView::map(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) return {};
    const auto offset = maps_offset_ +
        static_cast<std::uint64_t>(index) * stage_map_head_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u32(section_.bytes, offset + 32),
        read_u32(section_.bytes, offset + 36),
        read_u32(section_.bytes, offset + 40),
        read_u32(section_.bytes, offset + 44),
    };
}

StageMapHeadRecord StageMapHeadsView::find(
    std::uint64_t file_name_hash,
    std::uint64_t root_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto candidate = map(index);
        if (candidate.file_name_hash == file_name_hash &&
            (root_name_hash == 0 || candidate.root_name_hash == root_name_hash))
            return candidate;
    }
    return {};
}

StageGeneralGroupRecord StageMapHeadsView::general_group(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= general_group_count_) return {};
    const auto offset = general_groups_offset_ +
        static_cast<std::uint64_t>(index) * stage_general_group_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16) != 0U,
        read_i32(section_.bytes, offset + 20),
    };
}

StageGeneralPointRecord StageMapHeadsView::general_point(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= general_point_count_) return {};
    const auto offset = general_points_offset_ +
        static_cast<std::uint64_t>(index) * stage_general_point_record_bytes;
    return {read_i16(section_.bytes, offset), read_i16(section_.bytes, offset + 2)};
}

StageModelGroupRecord StageMapHeadsView::model_group(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= model_group_count_) return {};
    const auto offset = model_groups_offset_ +
        static_cast<std::uint64_t>(index) * stage_model_group_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u32(section_.bytes, offset + 32),
        read_u32(section_.bytes, offset + 36),
        read_u32(section_.bytes, offset + 40),
        read_u64(section_.bytes, offset + 48),
        read_u32(section_.bytes, offset + 56),
    };
}

StageMapCollisionLinkRecord StageMapHeadsView::collision_link(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= collision_link_count_) return {};
    const auto offset = collision_links_offset_ +
        static_cast<std::uint64_t>(index) *
            stage_map_collision_link_record_bytes;
    return {
        read_i16(section_.bytes, offset),
        read_i16(section_.bytes, offset + 2),
        read_i16(section_.bytes, offset + 4),
    };
}

std::int16_t StageMapHeadsView::jobj_link(std::uint32_t index) const noexcept
{
    if (!valid() || index >= jobj_link_count_) return {};
    return read_i16(section_.bytes, jobj_links_offset_ +
        static_cast<std::uint64_t>(index) * stage_map_jobj_link_record_bytes);
}

std::span<const std::byte> StageMapHeadsView::animation_flags(
    const StageModelGroupRecord& group) const noexcept
{
    if (!valid() || !range_fits(group.animation_flags_offset,
            group.animation_flag_count, section_.bytes.size()))
        return {};
    return section_.bytes.subspan(
        static_cast<std::size_t>(group.animation_flags_offset),
        group.animation_flag_count);
}

} // namespace pf::ssbm
