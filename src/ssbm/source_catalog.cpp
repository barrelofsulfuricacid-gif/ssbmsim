#include "source_catalog.h"

#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 32;

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

} // namespace

bool SourceCatalogView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::source_catalog ||
        section.schema_version != source_catalog_schema ||
        section.stride != source_catalog_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != source_catalog_schema) {
        return false;
    }
    count_ = read_u32(section.bytes, 4);
    records_offset_ = read_u64(section.bytes, 8);
    strings_offset_ = read_u64(section.bytes, 16);
    strings_size_ = read_u64(section.bytes, 24);
    const auto records_size = static_cast<std::uint64_t>(count_) *
        source_catalog_record_bytes;
    if (section.count != count_ || records_offset_ != header_bytes ||
        strings_offset_ != records_offset_ + records_size ||
        strings_offset_ > section.bytes.size() ||
        strings_size_ != section.bytes.size() - strings_offset_) {
        *this = {};
        return false;
    }
    std::uint64_t expected_name_offset = 0;
    std::string_view previous_path{};
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto offset = records_offset_ +
            static_cast<std::uint64_t>(index) * source_catalog_record_bytes;
        const auto name_offset = read_u64(section.bytes, offset);
        const auto name_size = read_u64(section.bytes, offset + 8);
        const auto source_size = read_u64(section.bytes, offset + 16);
        const auto empty = read_u32(section.bytes, offset + 64);
        if (name_offset != expected_name_offset || name_size == 0U ||
            name_size > strings_size_ - name_offset || empty > 1U ||
            (empty != 0U) != (source_size == 0U) ||
            read_u32(section.bytes, offset + 68) != 0U) {
            *this = {};
            return false;
        }
        const std::string_view path{
            reinterpret_cast<const char*>(section.bytes.data() + strings_offset_ +
                name_offset),
            static_cast<std::size_t>(name_size)};
        if ((index != 0U && path <= previous_path) ||
            path.find('\\') != std::string_view::npos) {
            *this = {};
            return false;
        }
        previous_path = path;
        expected_name_offset += name_size;
    }
    if (expected_name_offset != strings_size_) {
        *this = {};
        return false;
    }
    section_ = section;
    return true;
}

bool SourceCatalogView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t SourceCatalogView::count() const noexcept { return count_; }

SourceCatalogRecord SourceCatalogView::source(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) return {};
    const auto offset = records_offset_ +
        static_cast<std::uint64_t>(index) * source_catalog_record_bytes;
    const auto name_offset = read_u64(section_.bytes, offset);
    const auto name_size = read_u64(section_.bytes, offset + 8);
    return {
        {reinterpret_cast<const char*>(section_.bytes.data() + strings_offset_ +
             name_offset),
         static_cast<std::size_t>(name_size)},
        read_u64(section_.bytes, offset + 16),
        section_.bytes.subspan(static_cast<std::size_t>(offset + 24), 32),
        read_u32(section_.bytes, offset + 56),
        read_u32(section_.bytes, offset + 60),
        read_u32(section_.bytes, offset + 64) != 0U,
    };
}

SourceCatalogRecord SourceCatalogView::find(std::uint64_t path_hash) const noexcept
{
    for (std::uint32_t index = 0; index < count_; ++index) {
        const auto candidate = source(index);
        if (stable_name_hash(std::as_bytes(std::span(candidate.path))) == path_hash) {
            return candidate;
        }
    }
    return {};
}

} // namespace pf::ssbm
