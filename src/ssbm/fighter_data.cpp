#include "fighter_data.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    return static_cast<std::uint32_t>(
               std::to_integer<std::uint8_t>(bytes[native_offset])) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 1])) << 8U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 2])) << 16U) |
        (static_cast<std::uint32_t>(
             std::to_integer<std::uint8_t>(bytes[native_offset + 3])) << 24U);
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
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

bool FighterAttributesView::open(SectionView section) noexcept
{
    section_ = {};
    count_ = 0;
    records_offset_ = 0;
    if (section.kind != SectionKind::fighter_data ||
        section.schema_version != fighter_attributes_schema ||
        section.stride != fighter_attribute_record_bytes ||
        section.bytes.size() < 32 ||
        read_u32(section.bytes, 0) != fighter_attributes_schema ||
        read_u32(section.bytes, 8) != fighter_attribute_words ||
        read_u32(section.bytes, 12) != fighter_attribute_record_bytes) {
        return false;
    }
    const auto count = read_u32(section.bytes, 4);
    const auto records_offset = read_u64(section.bytes, 16);
    const auto payload_offset = read_u64(section.bytes, 24);
    const auto records_size =
        static_cast<std::uint64_t>(count) * fighter_attribute_record_bytes;
    if (count != section.count ||
        !range_fits(records_offset, records_size, section.bytes.size()) ||
        payload_offset < records_offset + records_size ||
        payload_offset > section.bytes.size()) {
        return false;
    }
    for (std::uint32_t index = 0; index < count; ++index) {
        const auto offset = records_offset +
            static_cast<std::uint64_t>(index) * fighter_attribute_record_bytes;
        const auto words_offset = read_u64(
            section.bytes,
            static_cast<std::size_t>(offset + 16));
        const auto words = read_u32(
            section.bytes,
            static_cast<std::size_t>(offset + 24));
        if (words != fighter_attribute_words ||
            (words_offset & 3U) != 0U ||
            !range_fits(
                words_offset,
                static_cast<std::uint64_t>(words) * sizeof(std::uint32_t),
                section.bytes.size())) {
            return false;
        }
    }
    section_ = section;
    count_ = count;
    records_offset_ = records_offset;
    return true;
}

bool FighterAttributesView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint32_t FighterAttributesView::count() const noexcept
{
    return count_;
}

FighterAttributeRecord FighterAttributesView::record(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) {
        return {};
    }
    const auto offset = records_offset_ +
        static_cast<std::uint64_t>(index) * fighter_attribute_record_bytes;
    return {
        read_u64(section_.bytes, static_cast<std::size_t>(offset)),
        read_u64(section_.bytes, static_cast<std::size_t>(offset + 8)),
        read_u64(section_.bytes, static_cast<std::size_t>(offset + 16)),
        read_u32(section_.bytes, static_cast<std::size_t>(offset + 24)),
    };
}

FighterAttributeRecord FighterAttributesView::find(
    std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto candidate = record(index);
        if (candidate.file_name_hash == file_name_hash) {
            return candidate;
        }
    }
    return {};
}

std::uint32_t FighterAttributesView::word(
    const FighterAttributeRecord& fighter,
    std::uint32_t index) const noexcept
{
    if (!valid() || fighter.word_count != fighter_attribute_words ||
        index >= fighter.word_count) {
        return 0;
    }
    return read_u32(
        section_.bytes,
        static_cast<std::size_t>(fighter.words_offset) + index * sizeof(std::uint32_t));
}

float FighterAttributesView::scalar(
    const FighterAttributeRecord& fighter,
    std::uint32_t byte_offset) const noexcept
{
    if ((byte_offset & 3U) != 0U ||
        byte_offset >= fighter_attribute_words * sizeof(std::uint32_t)) {
        return std::numeric_limits<float>::quiet_NaN();
    }
    return std::bit_cast<float>(word(fighter, byte_offset / sizeof(std::uint32_t)));
}

} // namespace pf::ssbm
