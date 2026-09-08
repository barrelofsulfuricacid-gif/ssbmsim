#ifndef PF_SSBM_FIGHTER_GEOMETRY_H
#define PF_SSBM_FIGHTER_GEOMETRY_H

#include "asset_pack.h"

#include <array>
#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t fighter_geometry_schema = 1;
inline constexpr std::uint32_t fighter_geometry_record_bytes = 256;
inline constexpr std::uint32_t fighter_hurtbox_record_bytes = 40;
inline constexpr std::uint32_t fighter_coin_sphere_record_bytes = 20;

enum FighterGeometryPresence : std::uint32_t {
    geometry_has_hurtboxes = 1U << 0U,
    geometry_has_center_bubble = 1U << 1U,
    geometry_has_coin_spheres = 1U << 2U,
    geometry_has_camera_box = 1U << 3U,
    geometry_has_item_pickup = 1U << 4U,
    geometry_has_environment_collision = 1U << 5U,
    geometry_has_jostle_box = 1U << 6U,
    geometry_has_bone_ids = 1U << 7U,
    geometry_has_ik = 1U << 8U,
    geometry_has_model_bones = 1U << 9U,
};

struct FighterHurtboxRecord {
    std::int32_t bone_index{};
    std::int32_t position_type{};
    std::int32_t grabbable{};
    std::array<std::uint32_t, 7> value_bits{};
};

struct FighterCoinSphereRecord {
    std::int32_t bone_index{};
    std::array<std::uint32_t, 4> value_bits{};
};

struct FighterEnvironmentCollisionRecord {
    std::array<std::int16_t, 6> bones{};
    std::array<std::uint32_t, 4> value_bits{};
};

struct FighterIkRecord {
    std::array<std::uint8_t, 10> joints{};
    std::array<std::uint32_t, 8> value_bits{};
};

struct FighterGeometryRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t presence{};
    std::uint32_t first_hurtbox{};
    std::uint32_t hurtbox_count{};
    std::uint32_t first_coin_sphere{};
    std::uint32_t coin_sphere_count{};
    std::int32_t center_bone{};
    std::uint32_t center_size_bits{};
    std::array<std::uint32_t, 2> jostle_bits{};
    FighterEnvironmentCollisionRecord environment{};
    std::array<std::uint32_t, 6> camera_bits{};
    std::array<std::uint32_t, 12> item_pickup_bits{};
    std::array<std::int32_t, 5> bone_ids{};
    std::array<std::uint8_t, 5> model_bones{};
    FighterIkRecord ik{};
};

class FighterGeometryView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] std::uint32_t hurtbox_count() const noexcept;
    [[nodiscard]] std::uint32_t coin_sphere_count() const noexcept;
    [[nodiscard]] FighterGeometryRecord fighter(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterGeometryRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] FighterHurtboxRecord hurtbox(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterCoinSphereRecord coin_sphere(std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint32_t hurtbox_count_{};
    std::uint32_t coin_sphere_count_{};
    std::uint64_t fighters_offset_{};
    std::uint64_t hurtboxes_offset_{};
    std::uint64_t coins_offset_{};
};

} // namespace pf::ssbm

#endif
