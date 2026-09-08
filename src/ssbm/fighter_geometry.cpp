#include "fighter_geometry.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 48;
constexpr std::uint32_t known_presence = (1U << 10U) - 1U;

[[nodiscard]] std::uint16_t read_u16(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    return static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[native_offset]) |
        static_cast<std::uint16_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + 1])) << 8U);
}

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint32_t value = 0;
    for (std::uint32_t byte = 0; byte < 4; ++byte) {
        value |= static_cast<std::uint32_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint64_t value = 0;
    for (std::uint32_t byte = 0; byte < 8; ++byte) {
        value |= static_cast<std::uint64_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t total) noexcept
{
    return offset <= total && size <= total - offset;
}

[[nodiscard]] bool multiply_fits(
    std::uint64_t count,
    std::uint64_t stride,
    std::uint64_t& result) noexcept
{
    if (count != 0 && stride > std::numeric_limits<std::uint64_t>::max() / count) {
        return false;
    }
    result = count * stride;
    return true;
}

} // namespace

bool FighterGeometryView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::fighter_data ||
        section.schema_version != fighter_geometry_schema ||
        section.stride != fighter_geometry_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != fighter_geometry_schema ||
        read_u32(section.bytes, 8) != fighter_geometry_record_bytes ||
        read_u32(section.bytes, 12) != fighter_hurtbox_record_bytes ||
        read_u32(section.bytes, 16) != fighter_coin_sphere_record_bytes) {
        return false;
    }
    count_ = read_u32(section.bytes, 4);
    fighters_offset_ = read_u64(section.bytes, 24);
    hurtboxes_offset_ = read_u64(section.bytes, 32);
    coins_offset_ = read_u64(section.bytes, 40);
    std::uint64_t fighter_bytes = 0;
    if (section.count != count_ ||
        !multiply_fits(count_, fighter_geometry_record_bytes, fighter_bytes) ||
        !range_fits(fighters_offset_, fighter_bytes, section.bytes.size()) ||
        fighters_offset_ < header_bytes ||
        hurtboxes_offset_ < fighters_offset_ + fighter_bytes ||
        coins_offset_ < hurtboxes_offset_ ||
        (coins_offset_ - hurtboxes_offset_) % fighter_hurtbox_record_bytes != 0U ||
        (section.bytes.size() - coins_offset_) %
            fighter_coin_sphere_record_bytes != 0U) {
        *this = {};
        return false;
    }
    hurtbox_count_ = static_cast<std::uint32_t>(
        (coins_offset_ - hurtboxes_offset_) / fighter_hurtbox_record_bytes);
    coin_sphere_count_ = static_cast<std::uint32_t>(
        (section.bytes.size() - coins_offset_) / fighter_coin_sphere_record_bytes);
    section_ = section;

    std::uint32_t expected_hurtbox = 0;
    std::uint32_t expected_coin = 0;
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto offset = fighters_offset_ +
            static_cast<std::uint64_t>(index) * fighter_geometry_record_bytes;
        const auto presence = read_u32(section.bytes, offset + 16);
        const auto hurt_count = read_u32(section.bytes, offset + 20);
        const auto hurt_offset = read_u64(section.bytes, offset + 24);
        const auto coin_count = read_u32(section.bytes, offset + 32);
        const auto coin_offset = read_u64(section.bytes, offset + 40);
        if ((presence & ~known_presence) != 0U ||
            hurt_offset < hurtboxes_offset_ ||
            (hurt_offset - hurtboxes_offset_) % fighter_hurtbox_record_bytes != 0U ||
            coin_offset < coins_offset_ ||
            (coin_offset - coins_offset_) % fighter_coin_sphere_record_bytes != 0U ||
            (hurt_offset - hurtboxes_offset_) / fighter_hurtbox_record_bytes !=
                expected_hurtbox ||
            (coin_offset - coins_offset_) / fighter_coin_sphere_record_bytes !=
                expected_coin ||
            hurt_count > hurtbox_count_ - expected_hurtbox ||
            coin_count > coin_sphere_count_ - expected_coin ||
            ((presence & geometry_has_hurtboxes) == 0U && hurt_count != 0U) ||
            ((presence & geometry_has_coin_spheres) == 0U && coin_count != 0U)) {
            *this = {};
            return false;
        }
        expected_hurtbox += hurt_count;
        expected_coin += coin_count;
    }
    if (expected_hurtbox != hurtbox_count_ ||
        expected_coin != coin_sphere_count_) {
        *this = {};
        return false;
    }
    return true;
}

bool FighterGeometryView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t FighterGeometryView::count() const noexcept { return count_; }
std::uint32_t FighterGeometryView::hurtbox_count() const noexcept { return hurtbox_count_; }
std::uint32_t FighterGeometryView::coin_sphere_count() const noexcept { return coin_sphere_count_; }

FighterGeometryRecord FighterGeometryView::fighter(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) return {};
    const auto offset = fighters_offset_ +
        static_cast<std::uint64_t>(index) * fighter_geometry_record_bytes;
    FighterGeometryRecord result{};
    result.file_name_hash = read_u64(section_.bytes, offset);
    result.root_name_hash = read_u64(section_.bytes, offset + 8);
    result.presence = read_u32(section_.bytes, offset + 16);
    result.hurtbox_count = read_u32(section_.bytes, offset + 20);
    result.first_hurtbox = static_cast<std::uint32_t>(
        (read_u64(section_.bytes, offset + 24) - hurtboxes_offset_) /
        fighter_hurtbox_record_bytes);
    result.coin_sphere_count = read_u32(section_.bytes, offset + 32);
    result.first_coin_sphere = static_cast<std::uint32_t>(
        (read_u64(section_.bytes, offset + 40) - coins_offset_) /
        fighter_coin_sphere_record_bytes);
    result.center_bone = std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 48));
    result.center_size_bits = read_u32(section_.bytes, offset + 52);
    for (std::size_t i = 0; i < result.jostle_bits.size(); ++i)
        result.jostle_bits[i] = read_u32(section_.bytes, offset + 56 + i * 4);
    for (std::size_t i = 0; i < result.environment.bones.size(); ++i)
        result.environment.bones[i] = std::bit_cast<std::int16_t>(
            read_u16(section_.bytes, offset + 64 + i * 2));
    for (std::size_t i = 0; i < result.environment.value_bits.size(); ++i)
        result.environment.value_bits[i] = read_u32(section_.bytes, offset + 76 + i * 4);
    for (std::size_t i = 0; i < result.camera_bits.size(); ++i)
        result.camera_bits[i] = read_u32(section_.bytes, offset + 92 + i * 4);
    for (std::size_t i = 0; i < result.item_pickup_bits.size(); ++i)
        result.item_pickup_bits[i] = read_u32(section_.bytes, offset + 116 + i * 4);
    for (std::size_t i = 0; i < result.bone_ids.size(); ++i)
        result.bone_ids[i] = std::bit_cast<std::int32_t>(
            read_u32(section_.bytes, offset + 164 + i * 4));
    for (std::size_t i = 0; i < result.model_bones.size(); ++i)
        result.model_bones[i] = std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 184 + i)]);
    const std::array<std::size_t, 10> joint_offsets{0, 1, 8, 9, 16, 17, 28, 29, 36, 37};
    for (std::size_t i = 0; i < result.ik.joints.size(); ++i)
        result.ik.joints[i] = std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(
                offset + 192 + joint_offsets[i])]);
    const std::array<std::size_t, 8> ik_offsets{4, 12, 20, 24, 32, 40, 44, 48};
    for (std::size_t i = 0; i < result.ik.value_bits.size(); ++i)
        result.ik.value_bits[i] = read_u32(section_.bytes, offset + 192 + ik_offsets[i]);
    return result;
}

FighterGeometryRecord FighterGeometryView::find(std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto candidate = fighter(index);
        if (candidate.file_name_hash == file_name_hash) return candidate;
    }
    return {};
}

FighterHurtboxRecord FighterGeometryView::hurtbox(std::uint32_t index) const noexcept
{
    if (!valid() || index >= hurtbox_count_) return {};
    const auto offset = hurtboxes_offset_ +
        static_cast<std::uint64_t>(index) * fighter_hurtbox_record_bytes;
    FighterHurtboxRecord result{
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 4)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 8)),
        {}};
    for (std::size_t i = 0; i < result.value_bits.size(); ++i)
        result.value_bits[i] = read_u32(section_.bytes, offset + 12 + i * 4);
    return result;
}

FighterCoinSphereRecord FighterGeometryView::coin_sphere(std::uint32_t index) const noexcept
{
    if (!valid() || index >= coin_sphere_count_) return {};
    const auto offset = coins_offset_ +
        static_cast<std::uint64_t>(index) * fighter_coin_sphere_record_bytes;
    FighterCoinSphereRecord result{
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)), {}};
    for (std::size_t i = 0; i < result.value_bits.size(); ++i)
        result.value_bits[i] = read_u32(section_.bytes, offset + 4 + i * 4);
    return result;
}

} // namespace pf::ssbm
