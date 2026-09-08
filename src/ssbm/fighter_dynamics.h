#ifndef PF_SSBM_FIGHTER_DYNAMICS_H
#define PF_SSBM_FIGHTER_DYNAMICS_H

#include "asset_pack.h"

#include <array>
#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t fighter_dynamics_schema = 1;
inline constexpr std::uint32_t fighter_dynamics_record_bytes = 64;
inline constexpr std::uint32_t fighter_dynamic_descriptor_bytes = 32;
inline constexpr std::uint32_t fighter_dynamic_parameter_bytes = 60;
inline constexpr std::uint32_t fighter_dynamic_bubble_bytes = 20;
inline constexpr std::uint32_t fighter_dynamic_apply_table_bytes = 16;

struct FighterDynamicsRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    bool present{};
    std::uint32_t first_descriptor{};
    std::uint32_t descriptor_count{};
    std::uint32_t first_bubble{};
    std::uint32_t bubble_count{};
    std::uint32_t first_apply_table{};
    std::uint32_t apply_table_count{};
};

struct FighterDynamicDescriptorRecord {
    std::int32_t bone_index{};
    std::uint32_t first_parameter{};
    std::uint32_t parameter_count{};
    std::uint32_t drag_bits{};
    std::uint32_t stiffness_bits{};
    std::uint32_t gravity_bits{};
};

struct FighterDynamicParameterRecord {
    std::array<std::uint32_t, 15> value_bits{};
};

struct FighterDynamicBubbleRecord {
    std::int32_t bone_index{};
    std::array<std::uint32_t, 4> value_bits{};
};

struct FighterDynamicApplyTableRecord {
    std::uint32_t first_value{};
    std::uint32_t value_count{};
    bool present{};
};

class FighterDynamicsView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t fighter_count() const noexcept;
    [[nodiscard]] std::uint32_t descriptor_count() const noexcept;
    [[nodiscard]] std::uint32_t parameter_count() const noexcept;
    [[nodiscard]] std::uint32_t bubble_count() const noexcept;
    [[nodiscard]] std::uint32_t apply_table_count() const noexcept;
    [[nodiscard]] std::uint32_t value_count() const noexcept;
    [[nodiscard]] FighterDynamicsRecord fighter(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterDynamicsRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] FighterDynamicDescriptorRecord descriptor(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterDynamicParameterRecord parameter(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterDynamicBubbleRecord bubble(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterDynamicApplyTableRecord apply_table(std::uint32_t index) const noexcept;
    [[nodiscard]] std::int32_t apply_value(std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t fighter_count_{};
    std::uint32_t descriptor_count_{};
    std::uint32_t parameter_count_{};
    std::uint32_t bubble_count_{};
    std::uint32_t table_count_{};
    std::uint32_t value_count_{};
    std::uint64_t fighters_offset_{};
    std::uint64_t descriptors_offset_{};
    std::uint64_t parameters_offset_{};
    std::uint64_t bubbles_offset_{};
    std::uint64_t tables_offset_{};
    std::uint64_t values_offset_{};
};

} // namespace pf::ssbm

#endif
