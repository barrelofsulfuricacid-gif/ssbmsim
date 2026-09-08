#include "stage_joint_animations.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint64_t header_bytes = 80;

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

} // namespace

bool StageJointAnimationNodeRecord::aobj_present() const noexcept
{
    return (presence_flags & (1U << 0U)) != 0U;
}

bool StageJointAnimationNodeRecord::robj_animation_present() const noexcept
{
    return (presence_flags & (1U << 1U)) != 0U;
}

bool StageJointAnimationNodeRecord::object_reference_present() const noexcept
{
    return (presence_flags & (1U << 2U)) != 0U;
}

float StageJointAnimationNodeRecord::end_frame() const noexcept
{
    return std::bit_cast<float>(end_frame_bits);
}

float StageJointAnimationTrackRecord::start_frame() const noexcept
{
    return std::bit_cast<float>(start_frame_bits);
}

bool StageJointAnimationsView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::animation_data ||
        section.schema_version != stage_joint_animation_schema ||
        section.stride != stage_joint_animation_set_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != stage_joint_animation_schema ||
        read_u32(section.bytes, 16) != stage_joint_animation_set_record_bytes ||
        read_u32(section.bytes, 20) != stage_joint_animation_node_record_bytes ||
        read_u32(section.bytes, 24) != stage_joint_animation_track_record_bytes ||
        read_u32(section.bytes, 28) != 0U ||
        read_u64(section.bytes, 72) != 0U) {
        return false;
    }
    set_count_ = read_u32(section.bytes, 4);
    node_count_ = read_u32(section.bytes, 8);
    track_count_ = read_u32(section.bytes, 12);
    sets_offset_ = read_u64(section.bytes, 32);
    nodes_offset_ = read_u64(section.bytes, 40);
    tracks_offset_ = read_u64(section.bytes, 48);
    blob_offset_ = read_u64(section.bytes, 56);
    blob_size_ = read_u64(section.bytes, 64);
    std::uint64_t set_bytes = 0;
    std::uint64_t node_bytes = 0;
    std::uint64_t track_bytes = 0;
    if (set_count_ != section.count ||
        !multiply_fits(set_count_, stage_joint_animation_set_record_bytes,
            set_bytes) ||
        !multiply_fits(node_count_, stage_joint_animation_node_record_bytes,
            node_bytes) ||
        !multiply_fits(track_count_, stage_joint_animation_track_record_bytes,
            track_bytes) ||
        sets_offset_ < header_bytes ||
        nodes_offset_ < sets_offset_ + set_bytes ||
        tracks_offset_ < nodes_offset_ + node_bytes ||
        blob_offset_ < tracks_offset_ + track_bytes ||
        !range_fits(blob_offset_, blob_size_, section.bytes.size()) ||
        blob_offset_ + blob_size_ != section.bytes.size()) {
        *this = {};
        return false;
    }
    section_ = section;

    std::uint32_t expected_node = 0;
    std::uint32_t expected_track = 0;
    std::uint64_t expected_data = blob_offset_;
    for (std::uint32_t set_index = 0; set_index < set_count_; ++set_index) {
        const auto candidate = set(set_index);
        const auto set_offset = sets_offset_ +
            static_cast<std::uint64_t>(set_index) *
                stage_joint_animation_set_record_bytes;
        if (candidate.file_name_hash == 0 ||
            candidate.map_root_name_hash == 0 ||
            candidate.first_node != expected_node ||
            !index_range_fits(candidate.first_node, candidate.node_count,
                node_count_) ||
            candidate.root_present != (candidate.node_count != 0) ||
            read_u32(section.bytes, set_offset + 32) > 1U ||
            read_u64(section.bytes, set_offset + 36) != 0U ||
            read_u32(section.bytes, set_offset + 44) != 0U) {
            *this = {};
            return false;
        }
        const auto node_end = candidate.first_node + candidate.node_count;
        for (std::uint32_t item = candidate.first_node; item < node_end; ++item) {
            const auto candidate_node = node(item);
            const auto node_offset = nodes_offset_ +
                static_cast<std::uint64_t>(item) *
                    stage_joint_animation_node_record_bytes;
            const auto valid_edge = [item, node_end](std::int32_t edge) {
                return edge == -1 ||
                    (edge > static_cast<std::int32_t>(item) &&
                     edge < static_cast<std::int32_t>(node_end));
            };
            if (!valid_edge(candidate_node.child) ||
                !valid_edge(candidate_node.next) ||
                (candidate_node.presence_flags & ~0x7U) != 0U ||
                candidate_node.first_track != expected_track ||
                !index_range_fits(candidate_node.first_track,
                    candidate_node.track_count, track_count_) ||
                (!candidate_node.aobj_present() &&
                 (candidate_node.aobj_flags != 0 ||
                  candidate_node.end_frame_bits != 0 ||
                  candidate_node.track_count != 0)) ||
                (candidate_node.object_reference_present() !=
                 (candidate_node.object_tree_name_hash != 0)) ||
                candidate_node.object_model_joint < -1 ||
                (!candidate_node.object_reference_present() &&
                 candidate_node.object_model_joint != -1) ||
                read_u32(section.bytes, node_offset + 44) != 0U) {
                *this = {};
                return false;
            }
            for (std::uint32_t local = 0;
                 local < candidate_node.track_count;
                 ++local) {
                const auto candidate_track = track(
                    candidate_node.first_track + local);
                const auto track_offset = tracks_offset_ +
                    static_cast<std::uint64_t>(candidate_node.first_track + local) *
                        stage_joint_animation_track_record_bytes;
                if (candidate_track.data_length != candidate_track.buffer_size ||
                    candidate_track.data_offset != expected_data ||
                    !range_fits(candidate_track.data_offset,
                        candidate_track.buffer_size, section.bytes.size()) ||
                    read_u32(section.bytes, track_offset + 12) != 0U ||
                    read_u64(section.bytes, track_offset + 28) != 0U ||
                    read_u32(section.bytes, track_offset + 36) != 0U) {
                    *this = {};
                    return false;
                }
                expected_data += candidate_track.buffer_size;
            }
            expected_track += candidate_node.track_count;
        }
        expected_node = node_end;
    }
    if (expected_node != node_count_ || expected_track != track_count_ ||
        expected_data != blob_offset_ + blob_size_) {
        *this = {};
        return false;
    }
    return true;
}

bool StageJointAnimationsView::valid() const noexcept
{
    return !section_.bytes.empty();
}
std::uint32_t StageJointAnimationsView::set_count() const noexcept
{
    return set_count_;
}
std::uint32_t StageJointAnimationsView::node_count() const noexcept
{
    return node_count_;
}
std::uint32_t StageJointAnimationsView::track_count() const noexcept
{
    return track_count_;
}

StageJointAnimationSetRecord StageJointAnimationsView::set(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= set_count_) return {};
    const auto offset = sets_offset_ +
        static_cast<std::uint64_t>(index) *
            stage_joint_animation_set_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u32(section_.bytes, offset + 32) != 0U,
    };
}

StageJointAnimationSetRecord StageJointAnimationsView::find(
    std::uint64_t file_name_hash,
    std::uint64_t map_root_name_hash,
    std::uint32_t group_index,
    std::uint32_t state_index) const noexcept
{
    for (std::uint32_t index = 0; index < set_count_; ++index) {
        const auto candidate = set(index);
        if (candidate.file_name_hash == file_name_hash &&
            candidate.map_root_name_hash == map_root_name_hash &&
            candidate.group_index == group_index &&
            candidate.state_index == state_index)
            return candidate;
    }
    return {};
}

StageJointAnimationNodeRecord StageJointAnimationsView::node(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= node_count_) return {};
    const auto offset = nodes_offset_ +
        static_cast<std::uint64_t>(index) *
            stage_joint_animation_node_record_bytes;
    return {
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 4)),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u64(section_.bytes, offset + 32),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 40)),
    };
}

StageJointAnimationTrackRecord StageJointAnimationsView::track(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= track_count_) return {};
    const auto offset = tracks_offset_ +
        static_cast<std::uint64_t>(index) *
            stage_joint_animation_track_record_bytes;
    return {
        read_u32(section_.bytes, offset),
        read_u32(section_.bytes, offset + 4),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 8)]),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 9)]),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 10)]),
        read_u64(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 24),
    };
}

std::span<const std::byte> StageJointAnimationsView::track_data(
    const StageJointAnimationTrackRecord& candidate) const noexcept
{
    if (!valid() || !range_fits(candidate.data_offset,
            candidate.buffer_size, section_.bytes.size()))
        return {};
    return section_.bytes.subspan(
        static_cast<std::size_t>(candidate.data_offset),
        candidate.buffer_size);
}

} // namespace pf::ssbm
