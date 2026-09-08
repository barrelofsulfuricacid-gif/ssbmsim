#include "player_common.h"

#include <cstddef>

namespace pf::ssbm {
namespace {

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::size_t offset) noexcept
{
    return static_cast<std::uint32_t>(
               std::to_integer<std::uint8_t>(bytes[offset])) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[offset + 1])) << 8U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[offset + 2])) << 16U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[offset + 3])) << 24U);
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::size_t offset) noexcept
{
    return static_cast<std::uint64_t>(read_u32(bytes, offset)) |
        (static_cast<std::uint64_t>(read_u32(bytes, offset + 4)) << 32U);
}

} // namespace

bool PlayerCommonView::open(SectionView section) noexcept
{
    section_ = {};
    constexpr auto payload_bytes =
        player_common_word_count * sizeof(std::uint32_t);
    if (section.kind != SectionKind::player_data ||
        section.schema_version != player_common_schema ||
        section.count != player_common_word_count ||
        section.stride != sizeof(std::uint32_t) ||
        section.bytes.size() != player_common_header_bytes + payload_bytes ||
        read_u32(section.bytes, 0) != player_common_schema ||
        read_u32(section.bytes, 4) != player_common_word_count ||
        read_u32(section.bytes, 8) != sizeof(std::uint32_t) ||
        read_u32(section.bytes, 12) != player_common_header_bytes ||
        read_u64(section.bytes, 16) == 0 || read_u64(section.bytes, 24) == 0) {
        return false;
    }
    section_ = section;
    return true;
}

bool PlayerCommonView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint64_t PlayerCommonView::file_name_hash() const noexcept
{
    return valid() ? read_u64(section_.bytes, 16) : 0;
}

std::uint64_t PlayerCommonView::root_name_hash() const noexcept
{
    return valid() ? read_u64(section_.bytes, 24) : 0;
}

std::span<const std::byte> PlayerCommonView::data() const noexcept
{
    if (!valid()) {
        return {};
    }
    return section_.bytes.subspan(player_common_header_bytes);
}

} // namespace pf::ssbm
