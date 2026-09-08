#include "asset_pack.h"

#include <array>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::array<std::byte, 8> magic{
    std::byte{'P'}, std::byte{'F'}, std::byte{'S'}, std::byte{'A'},
    std::byte{'P'}, std::byte{'C'}, std::byte{'K'}, std::byte{0}};

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::size_t offset) noexcept
{
    return static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset])) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 1])) << 8U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 2])) << 16U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 3])) << 24U);
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::size_t offset) noexcept
{
    return static_cast<std::uint64_t>(read_u32(bytes, offset)) |
        (static_cast<std::uint64_t>(read_u32(bytes, offset + 4)) << 32U);
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t capacity) noexcept
{
    const auto cap = static_cast<std::uint64_t>(capacity);
    return offset <= cap && size <= cap - offset;
}

} // namespace

PackStatus AssetPackView::open(std::span<const std::byte> bytes) noexcept
{
    bytes_ = {};
    section_count_ = 0;
    directory_offset_ = 0;

    if (bytes.size() < pack_header_size) {
        return PackStatus::too_small;
    }
    for (std::size_t index = 0; index < magic.size(); ++index) {
        if (bytes[index] != magic[index]) {
            return PackStatus::bad_magic;
        }
    }
    if (read_u32(bytes, 8) != pack_format_version) {
        return PackStatus::unsupported_format;
    }
    if (read_u32(bytes, 12) != endian_marker) {
        return PackStatus::unsupported_endian;
    }
    if (read_u32(bytes, 16) != pack_header_size ||
        read_u32(bytes, 20) != section_record_size) {
        return PackStatus::bad_layout;
    }

    const auto section_count = read_u32(bytes, 24);
    const auto file_size = read_u64(bytes, 32);
    const auto directory_offset = read_u64(bytes, 40);
    const auto payload_offset = read_u64(bytes, 48);
    const auto directory_size =
        static_cast<std::uint64_t>(section_count) * section_record_size;
    if (file_size != bytes.size() ||
        !range_fits(directory_offset, directory_size, bytes.size()) ||
        payload_offset < directory_offset + directory_size ||
        payload_offset > file_size) {
        return PackStatus::bad_layout;
    }

    for (std::uint32_t left = 0; left < section_count; ++left) {
        const auto left_record = directory_offset +
            static_cast<std::uint64_t>(left) * section_record_size;
        const auto left_offset = read_u64(bytes, static_cast<std::size_t>(left_record + 16));
        const auto left_size = read_u64(bytes, static_cast<std::size_t>(left_record + 24));
        if (left_offset < payload_offset ||
            (left_offset & 7U) != 0U ||
            !range_fits(left_offset, left_size, bytes.size())) {
            return PackStatus::out_of_bounds;
        }
        const auto left_kind = read_u32(bytes, static_cast<std::size_t>(left_record));
        const auto left_name = read_u64(bytes, static_cast<std::size_t>(left_record + 8));
        for (std::uint32_t right = 0; right < left; ++right) {
            const auto right_record = directory_offset +
                static_cast<std::uint64_t>(right) * section_record_size;
            if (left_kind == read_u32(bytes, static_cast<std::size_t>(right_record)) &&
                left_name == read_u64(bytes, static_cast<std::size_t>(right_record + 8))) {
                return PackStatus::duplicate_section;
            }
        }
    }

    bytes_ = bytes;
    section_count_ = section_count;
    directory_offset_ = directory_offset;
    return PackStatus::ok;
}

bool AssetPackView::valid() const noexcept
{
    return !bytes_.empty();
}

std::uint32_t AssetPackView::section_count() const noexcept
{
    return section_count_;
}

SectionView AssetPackView::section(std::uint32_t index) const noexcept
{
    if (!valid() || index >= section_count_) {
        return {};
    }
    const auto record = directory_offset_ +
        static_cast<std::uint64_t>(index) * section_record_size;
    const auto offset = read_u64(bytes_, static_cast<std::size_t>(record + 16));
    const auto size = read_u64(bytes_, static_cast<std::size_t>(record + 24));
    return {
        static_cast<SectionKind>(read_u32(bytes_, static_cast<std::size_t>(record))),
        read_u32(bytes_, static_cast<std::size_t>(record + 4)),
        read_u64(bytes_, static_cast<std::size_t>(record + 8)),
        bytes_.subspan(static_cast<std::size_t>(offset), static_cast<std::size_t>(size)),
        read_u32(bytes_, static_cast<std::size_t>(record + 32)),
        read_u32(bytes_, static_cast<std::size_t>(record + 36)),
    };
}

SectionView AssetPackView::find(
    SectionKind kind,
    std::uint64_t name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < section_count_; ++index) {
        const auto candidate = section(index);
        if (candidate.kind == kind && candidate.name_hash == name_hash) {
            return candidate;
        }
    }
    return {};
}

std::span<const std::byte> AssetPackView::source_set_digest() const noexcept
{
    if (!valid()) {
        return {};
    }
    return {bytes_.data() + 56, 32};
}

std::uint64_t stable_name_hash(std::span<const std::byte> name) noexcept
{
    std::uint64_t value = 14695981039346656037ULL;
    for (const auto byte : name) {
        value ^= std::to_integer<std::uint8_t>(byte);
        value *= 1099511628211ULL;
    }
    return value;
}

} // namespace pf::ssbm
