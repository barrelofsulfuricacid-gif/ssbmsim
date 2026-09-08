#ifndef PF_SSBM_STAGE_JOINT_ANIMATIONS_H
#define PF_SSBM_STAGE_JOINT_ANIMATIONS_H

#include "asset_pack.h"

#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t stage_joint_animation_schema = 2;
inline constexpr std::uint32_t stage_joint_animation_set_record_bytes = 48;
inline constexpr std::uint32_t stage_joint_animation_node_record_bytes = 48;
inline constexpr std::uint32_t stage_joint_animation_track_record_bytes = 40;

struct StageJointAnimationSetRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t map_root_name_hash{};
    std::uint32_t group_index{};
    std::uint32_t state_index{};
    std::uint32_t first_node{};
    std::uint32_t node_count{};
    bool root_present{};
};

struct StageJointAnimationNodeRecord {
    std::int32_t child{};
    std::int32_t next{};
    std::uint32_t flags{};
    std::uint32_t presence_flags{};
    std::uint32_t aobj_flags{};
    std::uint32_t end_frame_bits{};
    std::uint32_t first_track{};
    std::uint32_t track_count{};
    std::uint64_t object_tree_name_hash{};
    std::int32_t object_model_joint{-1};

    [[nodiscard]] bool aobj_present() const noexcept;
    [[nodiscard]] bool robj_animation_present() const noexcept;
    [[nodiscard]] bool object_reference_present() const noexcept;
    [[nodiscard]] float end_frame() const noexcept;
};

struct StageJointAnimationTrackRecord {
    std::uint32_t data_length{};
    std::uint32_t start_frame_bits{};
    std::uint8_t track_type{};
    std::uint8_t value_flags{};
    std::uint8_t tangent_flags{};
    std::uint64_t data_offset{};
    std::uint32_t buffer_size{};

    [[nodiscard]] float start_frame() const noexcept;
};

class StageJointAnimationsView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t set_count() const noexcept;
    [[nodiscard]] std::uint32_t node_count() const noexcept;
    [[nodiscard]] std::uint32_t track_count() const noexcept;
    [[nodiscard]] StageJointAnimationSetRecord set(
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageJointAnimationSetRecord find(
        std::uint64_t file_name_hash,
        std::uint64_t map_root_name_hash,
        std::uint32_t group_index,
        std::uint32_t state_index) const noexcept;
    [[nodiscard]] StageJointAnimationNodeRecord node(
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageJointAnimationTrackRecord track(
        std::uint32_t index) const noexcept;
    [[nodiscard]] std::span<const std::byte> track_data(
        const StageJointAnimationTrackRecord& track) const noexcept;

private:
    SectionView section_{};
    std::uint32_t set_count_{};
    std::uint32_t node_count_{};
    std::uint32_t track_count_{};
    std::uint64_t sets_offset_{};
    std::uint64_t nodes_offset_{};
    std::uint64_t tracks_offset_{};
    std::uint64_t blob_offset_{};
    std::uint64_t blob_size_{};
};

} // namespace pf::ssbm

#endif
