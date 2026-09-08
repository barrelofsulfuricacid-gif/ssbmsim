#ifndef PF_SSBM_JOINT_TREES_H
#define PF_SSBM_JOINT_TREES_H

#include "asset_pack.h"

#include <array>
#include <cstdint>
#include <span>
#include <string_view>

namespace pf::ssbm {

inline constexpr std::uint32_t joint_trees_schema = 2;
inline constexpr std::uint32_t joint_tree_record_bytes = 32;
inline constexpr std::uint32_t joint_record_bytes = 184;
inline constexpr std::uint32_t joint_reference_record_bytes = 32;
inline constexpr std::uint32_t joint_rvalue_record_bytes = 16;

struct JointTreeRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t first_joint{};
    std::uint32_t joint_count{};
};

struct JointRecord {
    std::int32_t parent{};
    std::int32_t first_child{};
    std::int32_t next_sibling{};
    std::uint32_t flags{};
    std::string_view class_name{};
    bool inverse_present{};
    std::array<std::uint32_t, 9> srt_bits{};
    std::array<std::uint32_t, 12> inverse_bits{};
    bool display_object_present{};
    std::uint32_t first_reference{};
    std::uint32_t reference_count{};
    bool spline_present{};
    std::uint32_t spline_type{};
    std::int32_t spline_num_cv{};
    std::uint32_t spline_tension_bits{};
    std::uint32_t spline_total_length_bits{};
    std::span<const std::byte> spline_cv_bytes{};
    std::span<const std::byte> spline_length_bytes{};
    std::span<const std::byte> spline_segment_bytes{};
};

struct JointReferenceRecord {
    std::int32_t flags{};
    std::uint32_t reference_type{};
    std::uint32_t first_rvalue{};
    std::uint32_t rvalue_count{};
    std::uint32_t payload_bits{};
    std::int32_t target_joint{};
    std::uint32_t ik_bone_length_bits{};
    std::uint32_t ik_rotate_x_bits{};
};

struct JointRvalueRecord {
    std::int32_t flags{};
    std::int32_t target_joint{};
};

class JointTreesView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t tree_count() const noexcept;
    [[nodiscard]] std::uint32_t joint_count() const noexcept;
    [[nodiscard]] std::uint32_t reference_count() const noexcept;
    [[nodiscard]] std::uint32_t rvalue_count() const noexcept;
    [[nodiscard]] JointTreeRecord tree(std::uint32_t index) const noexcept;
    [[nodiscard]] JointTreeRecord find(
        std::uint64_t file_name_hash,
        std::uint64_t root_name_hash = 0) const noexcept;
    [[nodiscard]] JointRecord joint(std::uint32_t index) const noexcept;
    [[nodiscard]] JointReferenceRecord reference(std::uint32_t index) const noexcept;
    [[nodiscard]] JointRvalueRecord rvalue(std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t tree_count_{};
    std::uint32_t joint_count_{};
    std::uint32_t reference_count_{};
    std::uint32_t rvalue_count_{};
    std::uint64_t trees_offset_{};
    std::uint64_t joints_offset_{};
    std::uint64_t references_offset_{};
    std::uint64_t rvalues_offset_{};
    std::uint64_t blob_offset_{};
};

} // namespace pf::ssbm

#endif
