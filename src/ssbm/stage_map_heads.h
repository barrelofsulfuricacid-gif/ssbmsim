#ifndef PF_SSBM_STAGE_MAP_HEADS_H
#define PF_SSBM_STAGE_MAP_HEADS_H

#include "asset_pack.h"

#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t stage_map_head_schema = 2;
inline constexpr std::uint32_t stage_map_head_record_bytes = 64;
inline constexpr std::uint32_t stage_general_group_record_bytes = 32;
inline constexpr std::uint32_t stage_general_point_record_bytes = 8;
inline constexpr std::uint32_t stage_model_group_record_bytes = 64;
inline constexpr std::uint32_t stage_map_collision_link_record_bytes = 8;
inline constexpr std::uint32_t stage_map_jobj_link_record_bytes = 2;

struct StageMapHeadRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t first_general_group{};
    std::uint32_t general_group_count{};
    std::uint32_t first_model_group{};
    std::uint32_t model_group_count{};
    std::uint32_t spline_count{};
    std::uint32_t light_count{};
    std::uint32_t spline_desc_count{};
    std::uint32_t mobj_count{};
};

struct StageGeneralGroupRecord {
    std::uint64_t joint_tree_name_hash{};
    std::uint32_t first_point{};
    std::uint32_t point_count{};
    bool root_node_present{};
    std::int32_t linked_model_group{-1};
};

struct StageGeneralPointRecord {
    std::int16_t joint_index{};
    std::int16_t type{};
};

struct StageModelGroupRecord {
    std::uint64_t joint_tree_name_hash{};
    std::uint32_t joint_animation_count{};
    std::uint32_t material_animation_count{};
    std::uint32_t shape_animation_count{};
    std::uint32_t light_count{};
    std::uint32_t first_collision_link{};
    std::uint32_t collision_link_count{};
    std::uint32_t first_jobj_link{};
    std::uint32_t jobj_link_count{};
    std::uint32_t presence_flags{};
    std::uint64_t animation_flags_offset{};
    std::uint32_t animation_flag_count{};

    [[nodiscard]] bool root_node_present() const noexcept;
    [[nodiscard]] bool camera_present() const noexcept;
    [[nodiscard]] bool fog_present() const noexcept;
};

struct StageMapCollisionLinkRecord {
    std::int16_t collision_index{};
    std::int16_t unknown_index{};
    std::int16_t joint_index{};
};

class StageMapHeadsView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] std::uint32_t general_group_count() const noexcept;
    [[nodiscard]] std::uint32_t general_point_count() const noexcept;
    [[nodiscard]] std::uint32_t model_group_count() const noexcept;
    [[nodiscard]] std::uint32_t collision_link_count() const noexcept;
    [[nodiscard]] std::uint32_t jobj_link_count() const noexcept;
    [[nodiscard]] StageMapHeadRecord map(std::uint32_t index) const noexcept;
    [[nodiscard]] StageMapHeadRecord find(
        std::uint64_t file_name_hash,
        std::uint64_t root_name_hash = 0) const noexcept;
    [[nodiscard]] StageGeneralGroupRecord general_group(
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageGeneralPointRecord general_point(
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageModelGroupRecord model_group(
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageMapCollisionLinkRecord collision_link(
        std::uint32_t index) const noexcept;
    [[nodiscard]] std::int16_t jobj_link(std::uint32_t index) const noexcept;
    [[nodiscard]] std::span<const std::byte> animation_flags(
        const StageModelGroupRecord& group) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint32_t general_group_count_{};
    std::uint32_t general_point_count_{};
    std::uint32_t model_group_count_{};
    std::uint32_t collision_link_count_{};
    std::uint32_t jobj_link_count_{};
    std::uint64_t maps_offset_{};
    std::uint64_t general_groups_offset_{};
    std::uint64_t general_points_offset_{};
    std::uint64_t model_groups_offset_{};
    std::uint64_t collision_links_offset_{};
    std::uint64_t jobj_links_offset_{};
};

} // namespace pf::ssbm

#endif
