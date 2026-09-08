#ifndef PF_SSBM_FIGHTER_ACTIONS_H
#define PF_SSBM_FIGHTER_ACTIONS_H

#include "asset_pack.h"

#include <cstdint>
#include <span>
#include <string_view>

namespace pf::ssbm {

inline constexpr std::uint32_t fighter_actions_schema = 1;
inline constexpr std::uint32_t fighter_action_record_bytes = 80;

struct FighterActionFileRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t first_action{};
    std::uint32_t action_count{};
};

struct FighterActionRecord {
    std::string_view name{};
    std::uint32_t flags{};
    std::int32_t animation_offset{};
    std::int32_t animation_size{};
    std::span<const std::byte> script{};
    bool has_animation{};
    std::int32_t animation_type{};
    std::uint32_t frame_count_bits{};
    std::uint64_t nodes_offset{};
    std::uint32_t node_count{};
    std::uint64_t tracks_offset{};
    std::uint32_t track_count{};
};

struct FighterAnimationNodeRecord {
    std::uint32_t first_track{};
    std::uint32_t track_count{};
};

struct FighterAnimationTrackRecord {
    std::uint16_t data_length{};
    std::int16_t start_frame{};
    std::uint8_t track_type{};
    std::uint8_t value_format{};
    std::uint8_t tangent_format{};
    std::uint32_t value_scale{};
    std::uint32_t tangent_scale{};
    std::span<const std::byte> buffer{};
};

class FighterActionsView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t fighter_count() const noexcept;
    [[nodiscard]] std::uint32_t action_count() const noexcept;
    [[nodiscard]] FighterActionFileRecord fighter(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterActionFileRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] FighterActionRecord action(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterAnimationNodeRecord node(
        const FighterActionRecord& action,
        std::uint32_t index) const noexcept;
    [[nodiscard]] FighterAnimationTrackRecord track(
        const FighterActionRecord& action,
        std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t fighter_count_{};
    std::uint32_t action_count_{};
    std::uint64_t fighters_offset_{};
    std::uint64_t actions_offset_{};
    std::uint64_t blob_offset_{};
    std::uint64_t blob_size_{};
};

} // namespace pf::ssbm

#endif
