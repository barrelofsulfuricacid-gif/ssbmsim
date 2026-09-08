#include "effect_particles.h"

#include <bit>
#include <cstddef>

namespace pf::ssbm {
namespace {

[[nodiscard]] std::uint16_t read_u16(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native = static_cast<std::size_t>(offset);
    return static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[native]) |
        (static_cast<std::uint16_t>(
             std::to_integer<std::uint8_t>(bytes[native + 1])) << 8U));
}

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    return static_cast<std::uint32_t>(read_u16(bytes, offset)) |
        (static_cast<std::uint32_t>(read_u16(bytes, offset + 2)) << 16U);
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
    return std::bit_cast<std::int16_t>(read_u16(bytes, offset));
}

[[nodiscard]] std::int32_t read_i32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    return std::bit_cast<std::int32_t>(read_u32(bytes, offset));
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t capacity) noexcept
{
    const auto cap = static_cast<std::uint64_t>(capacity);
    return offset <= cap && size <= cap - offset;
}

[[nodiscard]] bool indexed_range_fits(
    std::uint32_t offset,
    std::uint32_t count,
    std::uint32_t capacity) noexcept
{
    return offset <= capacity && count <= capacity - offset;
}

[[nodiscard]] bool zero_range(
    std::span<const std::byte> bytes,
    std::uint64_t offset,
    std::uint64_t size) noexcept
{
    for (std::uint64_t index = 0; index < size; ++index) {
        if (bytes[static_cast<std::size_t>(offset + index)] != std::byte{0}) {
            return false;
        }
    }
    return true;
}

} // namespace

bool EffectParticleView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::effect_data ||
        section.schema_version != effect_particle_schema ||
        section.stride != effect_particle_bank_bytes ||
        section.bytes.size() < 64 ||
        read_u32(section.bytes, 0) != effect_particle_schema ||
        read_u32(section.bytes, 16) != effect_particle_bank_bytes ||
        read_u32(section.bytes, 20) != effect_particle_generator_bytes ||
        read_u32(section.bytes, 24) != effect_particle_texture_bytes ||
        read_u32(section.bytes, 28) != 0) {
        return false;
    }

    bank_count_ = read_u32(section.bytes, 4);
    generator_count_ = read_u32(section.bytes, 8);
    texture_count_ = read_u32(section.bytes, 12);
    bank_offset_ = read_u64(section.bytes, 32);
    generator_offset_ = read_u64(section.bytes, 40);
    texture_offset_ = read_u64(section.bytes, 48);
    blob_offset_ = read_u64(section.bytes, 56);
    if (bank_count_ != section.count ||
        !range_fits(bank_offset_,
            static_cast<std::uint64_t>(bank_count_) *
                effect_particle_bank_bytes,
            section.bytes.size()) ||
        !range_fits(generator_offset_,
            static_cast<std::uint64_t>(generator_count_) *
                effect_particle_generator_bytes,
            section.bytes.size()) ||
        !range_fits(texture_offset_,
            static_cast<std::uint64_t>(texture_count_) *
                effect_particle_texture_bytes,
            section.bytes.size()) ||
        generator_offset_ < bank_offset_ +
            static_cast<std::uint64_t>(bank_count_) *
                effect_particle_bank_bytes ||
        texture_offset_ < generator_offset_ +
            static_cast<std::uint64_t>(generator_count_) *
                effect_particle_generator_bytes ||
        blob_offset_ < texture_offset_ +
            static_cast<std::uint64_t>(texture_count_) *
                effect_particle_texture_bytes ||
        blob_offset_ > section.bytes.size()) {
        *this = {};
        return false;
    }

    section_ = section;
    for (std::uint32_t index = 0; index < bank_count_; ++index) {
        const auto candidate = bank(index);
        const auto record = bank_offset_ +
            static_cast<std::uint64_t>(index) * effect_particle_bank_bytes;
        if (candidate.file_name_hash == 0 || candidate.root_name_hash == 0 ||
            !indexed_range_fits(candidate.generator_index,
                candidate.generator_count, generator_count_) ||
            !indexed_range_fits(candidate.texture_index,
                candidate.texture_count, texture_count_) ||
            (candidate.presence_flags & ~3U) != 0 ||
            ((candidate.presence_flags & 1U) == 0 &&
                candidate.generator_count != 0) ||
            ((candidate.presence_flags & 2U) == 0 &&
                candidate.texture_count != 0) ||
            !zero_range(section.bytes, record + 48, 16)) {
            *this = {};
            return false;
        }
        for (std::uint32_t generator_index = 0;
             generator_index < candidate.generator_count;
             ++generator_index) {
            const auto item = generator(candidate, generator_index);
            const auto global = candidate.generator_index + generator_index;
            const auto generator_record = generator_offset_ +
                static_cast<std::uint64_t>(global) *
                    effect_particle_generator_bytes;
            const auto state = read_u32(section.bytes, generator_record);
            if ((state != 0 && state != 1) ||
                (state == 0 && !zero_range(section.bytes,
                    generator_record, effect_particle_generator_bytes)) ||
                (state == 1 && (!item.present || item.bytecode.empty() || (
                    item.bytecode.back() != std::byte{0xFD} &&
                    item.bytecode.back() != std::byte{0xFE} &&
                    item.bytecode.back() != std::byte{0xFF}))) ||
                read_u32(section.bytes, generator_record + 76) != 0) {
                *this = {};
                return false;
            }
        }
        for (std::uint32_t texture_index = 0;
             texture_index < candidate.texture_count;
             ++texture_index) {
            const auto global = candidate.texture_index + texture_index;
            const auto texture_record = texture_offset_ +
                static_cast<std::uint64_t>(global) *
                    effect_particle_texture_bytes;
            if (!zero_range(section.bytes, texture_record + 24, 8)) {
                *this = {};
                return false;
            }
        }
    }
    return true;
}

bool EffectParticleView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint32_t EffectParticleView::bank_count() const noexcept
{
    return bank_count_;
}

std::uint32_t EffectParticleView::generator_count() const noexcept
{
    return generator_count_;
}

std::uint32_t EffectParticleView::texture_count() const noexcept
{
    return texture_count_;
}

EffectParticleBankRecord EffectParticleView::bank(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= bank_count_) {
        return {};
    }
    const auto record = bank_offset_ +
        static_cast<std::uint64_t>(index) * effect_particle_bank_bytes;
    return {
        read_u64(section_.bytes, record),
        read_u64(section_.bytes, record + 8),
        read_i16(section_.bytes, record + 16),
        read_i16(section_.bytes, record + 18),
        read_i32(section_.bytes, record + 20),
        read_u32(section_.bytes, record + 24),
        read_u32(section_.bytes, record + 28),
        read_u32(section_.bytes, record + 32),
        read_u32(section_.bytes, record + 36),
        read_u32(section_.bytes, record + 40),
        read_u32(section_.bytes, record + 44),
    };
}

EffectParticleBankRecord EffectParticleView::find(
    std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < bank_count_; ++index) {
        const auto candidate = bank(index);
        if (candidate.file_name_hash == file_name_hash) {
            return candidate;
        }
    }
    return {};
}

EffectParticleGeneratorRecord EffectParticleView::generator(
    const EffectParticleBankRecord& source_bank,
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= source_bank.generator_count ||
        !indexed_range_fits(source_bank.generator_index,
            source_bank.generator_count, generator_count_)) {
        return {};
    }
    const auto global = source_bank.generator_index + index;
    const auto record = generator_offset_ +
        static_cast<std::uint64_t>(global) * effect_particle_generator_bytes;
    const auto state = read_u32(section_.bytes, record);
    if (state != 1) {
        return {};
    }
    EffectParticleGeneratorRecord result{
        true,
        read_u16(section_.bytes, record + 4),
        read_i16(section_.bytes, record + 6),
        read_i16(section_.bytes, record + 8),
        read_i16(section_.bytes, record + 10),
        read_u32(section_.bytes, record + 12),
    };
    for (std::uint32_t scalar = 0;
         scalar < effect_particle_scalar_count;
         ++scalar) {
        result.scalar_bits[scalar] =
            read_u32(section_.bytes, record + 16 + scalar * sizeof(std::uint32_t));
    }
    const auto bytecode_offset = read_u64(section_.bytes, record + 64);
    const auto bytecode_size = read_u32(section_.bytes, record + 72);
    if (bytecode_offset < blob_offset_ ||
        !range_fits(bytecode_offset, bytecode_size, section_.bytes.size())) {
        return {};
    }
    result.bytecode = section_.bytes.subspan(
        static_cast<std::size_t>(bytecode_offset), bytecode_size);
    return result;
}

EffectParticleTextureRecord EffectParticleView::texture(
    const EffectParticleBankRecord& source_bank,
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= source_bank.texture_count ||
        !indexed_range_fits(source_bank.texture_index,
            source_bank.texture_count, texture_count_)) {
        return {};
    }
    const auto global = source_bank.texture_index + index;
    const auto record = texture_offset_ +
        static_cast<std::uint64_t>(global) * effect_particle_texture_bytes;
    return {
        read_u32(section_.bytes, record),
        read_u32(section_.bytes, record + 4),
        read_u32(section_.bytes, record + 8),
        read_u32(section_.bytes, record + 12),
        read_u32(section_.bytes, record + 16),
        read_u16(section_.bytes, record + 20),
        read_u16(section_.bytes, record + 22),
    };
}

} // namespace pf::ssbm
