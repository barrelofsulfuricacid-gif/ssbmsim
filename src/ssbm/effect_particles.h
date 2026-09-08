#ifndef PF_SSBM_EFFECT_PARTICLES_H
#define PF_SSBM_EFFECT_PARTICLES_H

#include "asset_pack.h"

#include <array>
#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t effect_particle_schema = 2;
inline constexpr std::uint32_t effect_particle_bank_bytes = 64;
inline constexpr std::uint32_t effect_particle_generator_bytes = 80;
inline constexpr std::uint32_t effect_particle_texture_bytes = 32;
inline constexpr std::uint32_t effect_particle_scalar_count = 12;

struct EffectParticleBankRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::int16_t unknown_1{};
    std::int16_t unknown_2{};
    std::int32_t effect_id_start{};
    std::uint32_t generator_index{};
    std::uint32_t generator_count{};
    std::uint32_t texture_index{};
    std::uint32_t texture_count{};
    std::uint32_t model_count{};
    std::uint32_t presence_flags{};
};

struct EffectParticleGeneratorRecord {
    bool present{};
    std::uint16_t type_flags{};
    std::int16_t texture_group{};
    std::int16_t generator_life{};
    std::int16_t particle_life{};
    std::uint32_t kind{};
    std::array<std::uint32_t, effect_particle_scalar_count> scalar_bits{};
    std::span<const std::byte> bytecode{};
};

struct EffectParticleTextureRecord {
    std::uint32_t image_count{};
    std::uint32_t format{};
    std::uint32_t palette_format{};
    std::uint32_t width{};
    std::uint32_t height{};
    std::uint16_t palette_count{};
    std::uint16_t palette_flags{};
};

class EffectParticleView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t bank_count() const noexcept;
    [[nodiscard]] std::uint32_t generator_count() const noexcept;
    [[nodiscard]] std::uint32_t texture_count() const noexcept;
    [[nodiscard]] EffectParticleBankRecord bank(
        std::uint32_t index) const noexcept;
    [[nodiscard]] EffectParticleBankRecord find(
        std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] EffectParticleGeneratorRecord generator(
        const EffectParticleBankRecord& bank,
        std::uint32_t index) const noexcept;
    [[nodiscard]] EffectParticleTextureRecord texture(
        const EffectParticleBankRecord& bank,
        std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t bank_count_{};
    std::uint32_t generator_count_{};
    std::uint32_t texture_count_{};
    std::uint64_t bank_offset_{};
    std::uint64_t generator_offset_{};
    std::uint64_t texture_offset_{};
    std::uint64_t blob_offset_{};
};

} // namespace pf::ssbm

#endif
