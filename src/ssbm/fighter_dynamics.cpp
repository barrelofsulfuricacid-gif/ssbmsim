#include "fighter_dynamics.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 80;

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

[[nodiscard]] bool offset_index(
    std::uint64_t offset,
    std::uint64_t base,
    std::uint32_t stride,
    std::uint32_t expected) noexcept
{
    return offset >= base && (offset - base) % stride == 0U &&
        (offset - base) / stride == expected;
}

} // namespace

bool FighterDynamicsView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::fighter_data ||
        section.schema_version != fighter_dynamics_schema ||
        section.stride != fighter_dynamics_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != fighter_dynamics_schema ||
        read_u32(section.bytes, 8) != fighter_dynamics_record_bytes ||
        read_u32(section.bytes, 12) != fighter_dynamic_descriptor_bytes ||
        read_u32(section.bytes, 16) != fighter_dynamic_parameter_bytes ||
        read_u32(section.bytes, 20) != fighter_dynamic_bubble_bytes ||
        read_u32(section.bytes, 24) != fighter_dynamic_apply_table_bytes) {
        return false;
    }
    fighter_count_ = read_u32(section.bytes, 4);
    fighters_offset_ = read_u64(section.bytes, 32);
    descriptors_offset_ = read_u64(section.bytes, 40);
    parameters_offset_ = read_u64(section.bytes, 48);
    bubbles_offset_ = read_u64(section.bytes, 56);
    tables_offset_ = read_u64(section.bytes, 64);
    values_offset_ = read_u64(section.bytes, 72);
    std::uint64_t fighter_bytes = 0;
    if (section.count != fighter_count_ ||
        !multiply_fits(fighter_count_, fighter_dynamics_record_bytes, fighter_bytes) ||
        fighters_offset_ < header_bytes ||
        fighters_offset_ > section.bytes.size() ||
        fighter_bytes > section.bytes.size() - fighters_offset_ ||
        descriptors_offset_ < fighters_offset_ + fighter_bytes ||
        parameters_offset_ < descriptors_offset_ ||
        bubbles_offset_ < parameters_offset_ ||
        tables_offset_ < bubbles_offset_ ||
        values_offset_ < tables_offset_ ||
        values_offset_ > section.bytes.size() ||
        (section.bytes.size() - values_offset_) % sizeof(std::uint32_t) != 0U) {
        *this = {};
        return false;
    }
    value_count_ = static_cast<std::uint32_t>(
        (section.bytes.size() - values_offset_) / sizeof(std::uint32_t));
    section_ = section;

    std::uint32_t expected_descriptor = 0;
    std::uint32_t expected_bubble = 0;
    std::uint32_t expected_table = 0;
    for (std::uint32_t index = 0; index < fighter_count_; ++index) {
        const auto offset = fighters_offset_ +
            static_cast<std::uint64_t>(index) * fighter_dynamics_record_bytes;
        const auto present = read_u32(section.bytes, offset + 16);
        const auto descriptor_count = read_u32(section.bytes, offset + 20);
        const auto descriptor_offset = read_u64(section.bytes, offset + 24);
        const auto bubble_count = read_u32(section.bytes, offset + 32);
        const auto bubble_offset = read_u64(section.bytes, offset + 40);
        const auto table_count = read_u32(section.bytes, offset + 48);
        const auto table_offset = read_u64(section.bytes, offset + 56);
        if (present > 1U ||
            !offset_index(descriptor_offset, descriptors_offset_,
                fighter_dynamic_descriptor_bytes, expected_descriptor) ||
            !offset_index(bubble_offset, bubbles_offset_,
                fighter_dynamic_bubble_bytes, expected_bubble) ||
            !offset_index(table_offset, tables_offset_,
                fighter_dynamic_apply_table_bytes, expected_table) ||
            (present == 0U &&
             (descriptor_count != 0U || bubble_count != 0U || table_count != 0U)) ||
            descriptor_count >
                std::numeric_limits<std::uint32_t>::max() - expected_descriptor ||
            bubble_count >
                std::numeric_limits<std::uint32_t>::max() - expected_bubble ||
            table_count >
                std::numeric_limits<std::uint32_t>::max() - expected_table) {
            *this = {};
            return false;
        }
        expected_descriptor += descriptor_count;
        expected_bubble += bubble_count;
        expected_table += table_count;
    }
    std::uint64_t descriptor_bytes = 0;
    std::uint64_t bubble_bytes = 0;
    std::uint64_t table_bytes = 0;
    if (!multiply_fits(expected_descriptor, fighter_dynamic_descriptor_bytes,
            descriptor_bytes) ||
        !multiply_fits(expected_bubble, fighter_dynamic_bubble_bytes, bubble_bytes) ||
        !multiply_fits(expected_table, fighter_dynamic_apply_table_bytes, table_bytes) ||
        descriptor_bytes > parameters_offset_ - descriptors_offset_ ||
        bubble_bytes > tables_offset_ - bubbles_offset_ ||
        table_bytes > values_offset_ - tables_offset_) {
        *this = {};
        return false;
    }
    descriptor_count_ = expected_descriptor;
    bubble_count_ = expected_bubble;
    table_count_ = expected_table;

    std::uint32_t expected_parameter = 0;
    for (std::uint32_t index = 0; index < descriptor_count_; ++index) {
        const auto offset = descriptors_offset_ +
            static_cast<std::uint64_t>(index) * fighter_dynamic_descriptor_bytes;
        const auto parameter_offset = read_u64(section.bytes, offset + 8);
        const auto parameter_count = read_u32(section.bytes, offset + 16);
        if (!offset_index(parameter_offset, parameters_offset_,
                fighter_dynamic_parameter_bytes, expected_parameter) ||
            parameter_count >
                std::numeric_limits<std::uint32_t>::max() - expected_parameter) {
            *this = {};
            return false;
        }
        expected_parameter += parameter_count;
    }
    std::uint64_t parameter_bytes = 0;
    if (!multiply_fits(expected_parameter, fighter_dynamic_parameter_bytes,
            parameter_bytes) ||
        parameter_bytes > bubbles_offset_ - parameters_offset_) {
        *this = {};
        return false;
    }
    parameter_count_ = expected_parameter;

    std::uint32_t expected_value = 0;
    for (std::uint32_t index = 0; index < table_count_; ++index) {
        const auto offset = tables_offset_ +
            static_cast<std::uint64_t>(index) * fighter_dynamic_apply_table_bytes;
        const auto value_offset = read_u64(section.bytes, offset);
        const auto value_count = read_u32(section.bytes, offset + 8);
        const auto present = read_u32(section.bytes, offset + 12);
        if (present > 1U ||
            !offset_index(value_offset, values_offset_, sizeof(std::uint32_t),
                expected_value) ||
            (present == 0U && value_count != 0U) ||
            expected_value > value_count_ ||
            value_count > value_count_ - expected_value) {
            *this = {};
            return false;
        }
        expected_value += value_count;
    }
    if (expected_value != value_count_) {
        *this = {};
        return false;
    }
    return true;
}

bool FighterDynamicsView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t FighterDynamicsView::fighter_count() const noexcept { return fighter_count_; }
std::uint32_t FighterDynamicsView::descriptor_count() const noexcept { return descriptor_count_; }
std::uint32_t FighterDynamicsView::parameter_count() const noexcept { return parameter_count_; }
std::uint32_t FighterDynamicsView::bubble_count() const noexcept { return bubble_count_; }
std::uint32_t FighterDynamicsView::apply_table_count() const noexcept { return table_count_; }
std::uint32_t FighterDynamicsView::value_count() const noexcept { return value_count_; }

FighterDynamicsRecord FighterDynamicsView::fighter(std::uint32_t index) const noexcept
{
    if (!valid() || index >= fighter_count_) return {};
    const auto offset = fighters_offset_ +
        static_cast<std::uint64_t>(index) * fighter_dynamics_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 16) != 0U,
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset + 24) -
            descriptors_offset_) / fighter_dynamic_descriptor_bytes),
        read_u32(section_.bytes, offset + 20),
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset + 40) -
            bubbles_offset_) / fighter_dynamic_bubble_bytes),
        read_u32(section_.bytes, offset + 32),
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset + 56) -
            tables_offset_) / fighter_dynamic_apply_table_bytes),
        read_u32(section_.bytes, offset + 48),
    };
}

FighterDynamicsRecord FighterDynamicsView::find(std::uint64_t file_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < fighter_count_; ++index) {
        const auto candidate = fighter(index);
        if (candidate.file_name_hash == file_name_hash) return candidate;
    }
    return {};
}

FighterDynamicDescriptorRecord FighterDynamicsView::descriptor(std::uint32_t index) const noexcept
{
    if (!valid() || index >= descriptor_count_) return {};
    const auto offset = descriptors_offset_ +
        static_cast<std::uint64_t>(index) * fighter_dynamic_descriptor_bytes;
    return {
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset + 8) -
            parameters_offset_) / fighter_dynamic_parameter_bytes),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
    };
}

FighterDynamicParameterRecord FighterDynamicsView::parameter(std::uint32_t index) const noexcept
{
    FighterDynamicParameterRecord result{};
    if (!valid() || index >= parameter_count_) return result;
    const auto offset = parameters_offset_ +
        static_cast<std::uint64_t>(index) * fighter_dynamic_parameter_bytes;
    for (std::size_t i = 0; i < result.value_bits.size(); ++i)
        result.value_bits[i] = read_u32(section_.bytes, offset + i * 4);
    return result;
}

FighterDynamicBubbleRecord FighterDynamicsView::bubble(std::uint32_t index) const noexcept
{
    FighterDynamicBubbleRecord result{};
    if (!valid() || index >= bubble_count_) return result;
    const auto offset = bubbles_offset_ +
        static_cast<std::uint64_t>(index) * fighter_dynamic_bubble_bytes;
    result.bone_index = std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset));
    for (std::size_t i = 0; i < result.value_bits.size(); ++i)
        result.value_bits[i] = read_u32(section_.bytes, offset + 4 + i * 4);
    return result;
}

FighterDynamicApplyTableRecord FighterDynamicsView::apply_table(std::uint32_t index) const noexcept
{
    if (!valid() || index >= table_count_) return {};
    const auto offset = tables_offset_ +
        static_cast<std::uint64_t>(index) * fighter_dynamic_apply_table_bytes;
    return {
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset) -
            values_offset_) / sizeof(std::uint32_t)),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12) != 0U,
    };
}

std::int32_t FighterDynamicsView::apply_value(std::uint32_t index) const noexcept
{
    if (!valid() || index >= value_count_) return 0;
    return std::bit_cast<std::int32_t>(read_u32(
        section_.bytes, values_offset_ + static_cast<std::uint64_t>(index) * 4U));
}

} // namespace pf::ssbm
