#include "stage_ground_params.h"

#include <cstddef>

namespace pf::ssbm {
namespace {

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes, std::uint64_t offset) noexcept
{
    const auto index = static_cast<std::size_t>(offset);
    return static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[index])) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[index + 1])) << 8U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[index + 2])) << 16U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[index + 3])) << 24U);
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes, std::uint64_t offset) noexcept
{
    return static_cast<std::uint64_t>(read_u32(bytes, offset)) |
        (static_cast<std::uint64_t>(read_u32(bytes, offset + 4)) << 32U);
}

[[nodiscard]] bool range_fits(
    std::uint64_t offset, std::uint64_t size, std::size_t capacity) noexcept
{
    const auto cap = static_cast<std::uint64_t>(capacity);
    return offset <= cap && size <= cap - offset;
}

} // namespace

bool StageGroundParamView::open(SectionView section) noexcept
{
    section_ = {};
    count_ = 0;
    records_offset_ = 0;
    if (section.kind != SectionKind::stage_data ||
        section.schema_version != stage_ground_param_schema ||
        section.stride != stage_ground_param_record_bytes ||
        section.bytes.size() < 40 ||
        read_u32(section.bytes, 0) != stage_ground_param_schema ||
        read_u32(section.bytes, 8) != stage_ground_param_record_bytes ||
        read_u32(section.bytes, 12) != stage_ground_param_image_bytes ||
        read_u32(section.bytes, 16) != stage_param_row_bytes ||
        read_u32(section.bytes, 20) != 0) {
        return false;
    }
    const auto count = read_u32(section.bytes, 4);
    const auto records_offset = read_u64(section.bytes, 24);
    const auto payload_offset = read_u64(section.bytes, 32);
    const auto records_size =
        static_cast<std::uint64_t>(count) * stage_ground_param_record_bytes;
    if (count != section.count ||
        !range_fits(records_offset, records_size, section.bytes.size()) ||
        payload_offset < records_offset + records_size ||
        payload_offset > section.bytes.size()) {
        return false;
    }

    section_ = section;
    count_ = count;
    records_offset_ = records_offset;
    for (std::uint32_t index = 0; index < count; ++index) {
        const auto stage = record(index);
        const auto record_offset = records_offset +
            static_cast<std::uint64_t>(index) * stage_ground_param_record_bytes;
        if (stage.file_name_hash == 0 ||
            read_u32(section.bytes, record_offset + 36) != 0 ||
            read_u64(section.bytes, record_offset + 40) != 0 ||
            !range_fits(stage.image_offset, stage_ground_param_image_bytes,
                section.bytes.size()) ||
            !range_fits(stage.rows_offset,
                static_cast<std::uint64_t>(stage.row_count) * stage_param_row_bytes,
                section.bytes.size()) ||
            stage.rows_offset < stage.image_offset + stage_ground_param_image_bytes ||
            read_u32(section.bytes, stage.image_offset + 0xB0) != 0 ||
            read_u32(section.bytes, stage.image_offset + 0xB4) != stage.row_count) {
            section_ = {};
            count_ = 0;
            records_offset_ = 0;
            return false;
        }
    }
    return true;
}

bool StageGroundParamView::valid() const noexcept
{
    return !section_.bytes.empty();
}

std::uint32_t StageGroundParamView::count() const noexcept
{
    return count_;
}

StageGroundParamRecord StageGroundParamView::record(std::uint32_t index) const noexcept
{
    if (!valid() || index >= count_) {
        return {};
    }
    const auto offset = records_offset_ +
        static_cast<std::uint64_t>(index) * stage_ground_param_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u64(section_.bytes, offset + 16),
        read_u64(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 32),
    };
}

StageGroundParamRecord StageGroundParamView::find(
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

std::span<const std::byte> StageGroundParamView::image(
    const StageGroundParamRecord& stage) const noexcept
{
    if (!valid() || stage.file_name_hash == 0 ||
        !range_fits(stage.image_offset, stage_ground_param_image_bytes,
            section_.bytes.size())) {
        return {};
    }
    return section_.bytes.subspan(
        static_cast<std::size_t>(stage.image_offset), stage_ground_param_image_bytes);
}

std::span<const std::byte> StageGroundParamView::rows(
    const StageGroundParamRecord& stage) const noexcept
{
    const auto size = static_cast<std::uint64_t>(stage.row_count) * stage_param_row_bytes;
    if (!valid() || stage.file_name_hash == 0 ||
        !range_fits(stage.rows_offset, size, section_.bytes.size())) {
        return {};
    }
    return section_.bytes.subspan(
        static_cast<std::size_t>(stage.rows_offset), static_cast<std::size_t>(size));
}

} // namespace pf::ssbm
