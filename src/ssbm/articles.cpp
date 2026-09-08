#include "articles.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 112;
constexpr std::uint32_t known_slot_presence = 0x3fU;
constexpr std::uint32_t known_state_presence = 0x0fU;

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
    if (count != 0U && stride > std::numeric_limits<std::uint64_t>::max() / count) {
        return false;
    }
    result = count * stride;
    return true;
}

[[nodiscard]] std::uint64_t align8(std::uint64_t value) noexcept
{
    return (value + 7U) & ~std::uint64_t{7U};
}

[[nodiscard]] bool zero_range(
    std::span<const std::byte> bytes,
    std::uint64_t offset,
    std::uint64_t size) noexcept
{
    if (!range_fits(offset, size, bytes.size())) return false;
    for (std::uint64_t index = 0; index < size; ++index) {
        if (bytes[static_cast<std::size_t>(offset + index)] != std::byte{0}) {
            return false;
        }
    }
    return true;
}

} // namespace

bool ArticlesView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::item_data ||
        section.schema_version != articles_schema ||
        section.stride != article_slot_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != articles_schema ||
        read_u32(section.bytes, 28) != article_source_record_bytes ||
        read_u32(section.bytes, 32) != article_slot_record_bytes ||
        read_u32(section.bytes, 36) != article_state_record_bytes ||
        read_u32(section.bytes, 40) != article_hurtbox_record_bytes ||
        read_u32(section.bytes, 44) != article_dynamic_descriptor_bytes ||
        read_u32(section.bytes, 48) != article_dynamic_parameter_bytes) {
        return false;
    }
    source_count_ = read_u32(section.bytes, 4);
    slot_count_ = read_u32(section.bytes, 8);
    state_count_ = read_u32(section.bytes, 12);
    hurtbox_count_ = read_u32(section.bytes, 16);
    descriptor_count_ = read_u32(section.bytes, 20);
    parameter_count_ = read_u32(section.bytes, 24);
    sources_offset_ = read_u64(section.bytes, 56);
    slots_offset_ = read_u64(section.bytes, 64);
    states_offset_ = read_u64(section.bytes, 72);
    hurtboxes_offset_ = read_u64(section.bytes, 80);
    descriptors_offset_ = read_u64(section.bytes, 88);
    parameters_offset_ = read_u64(section.bytes, 96);
    blob_offset_ = read_u64(section.bytes, 104);

    std::uint64_t source_bytes = 0;
    std::uint64_t slot_bytes = 0;
    std::uint64_t state_bytes = 0;
    std::uint64_t hurtbox_bytes = 0;
    std::uint64_t descriptor_bytes = 0;
    std::uint64_t parameter_bytes = 0;
    if (section.count != slot_count_ ||
        !multiply_fits(source_count_, article_source_record_bytes, source_bytes) ||
        !multiply_fits(slot_count_, article_slot_record_bytes, slot_bytes) ||
        !multiply_fits(state_count_, article_state_record_bytes, state_bytes) ||
        !multiply_fits(hurtbox_count_, article_hurtbox_record_bytes, hurtbox_bytes) ||
        !multiply_fits(descriptor_count_, article_dynamic_descriptor_bytes,
            descriptor_bytes) ||
        !multiply_fits(parameter_count_, article_dynamic_parameter_bytes,
            parameter_bytes) ||
        sources_offset_ != header_bytes ||
        slots_offset_ != align8(sources_offset_ + source_bytes) ||
        states_offset_ != align8(slots_offset_ + slot_bytes) ||
        hurtboxes_offset_ != align8(states_offset_ + state_bytes) ||
        descriptors_offset_ != align8(hurtboxes_offset_ + hurtbox_bytes) ||
        parameters_offset_ != align8(descriptors_offset_ + descriptor_bytes) ||
        blob_offset_ != align8(parameters_offset_ + parameter_bytes) ||
        blob_offset_ > section.bytes.size()) {
        *this = {};
        return false;
    }

    std::uint32_t expected_slot = 0;
    for (std::uint32_t index = 0; index < source_count_; ++index) {
        const auto offset = sources_offset_ +
            static_cast<std::uint64_t>(index) * article_source_record_bytes;
        const auto first = read_u32(section.bytes, offset + 20);
        const auto count = read_u32(section.bytes, offset + 24);
        if (first != expected_slot || count > slot_count_ - expected_slot ||
            read_u32(section.bytes, offset + 16) > 2U ||
            !zero_range(section.bytes, offset + 28, 12)) {
            *this = {};
            return false;
        }
        expected_slot += count;
    }
    if (expected_slot != slot_count_) {
        *this = {};
        return false;
    }

    std::uint32_t expected_state = 0;
    std::uint32_t expected_hurtbox = 0;
    std::uint32_t expected_descriptor = 0;
    for (std::uint32_t index = 0; index < slot_count_; ++index) {
        const auto offset = slots_offset_ +
            static_cast<std::uint64_t>(index) * article_slot_record_bytes;
        const auto present = read_u32(section.bytes, offset);
        if (present == 0U) {
            if (!zero_range(section.bytes, offset, article_slot_record_bytes)) {
                *this = {};
                return false;
            }
            continue;
        }
        const auto presence = read_u32(section.bytes, offset + 4);
        const auto first_hurtbox = read_u32(section.bytes, offset + 168);
        const auto hurtbox_count = read_u32(section.bytes, offset + 172);
        const auto first_state = read_u32(section.bytes, offset + 176);
        const auto state_count = read_u32(section.bytes, offset + 180);
        const auto first_descriptor = read_u32(section.bytes, offset + 184);
        const auto descriptor_count = read_u32(section.bytes, offset + 188);
        const auto common_attribute_bytes = read_u32(section.bytes, offset + 204);
        if (present != 1U || (presence & ~known_slot_presence) != 0U ||
            first_hurtbox != expected_hurtbox ||
            hurtbox_count > hurtbox_count_ - expected_hurtbox ||
            first_state != expected_state || state_count > state_count_ - expected_state ||
            first_descriptor != expected_descriptor ||
            descriptor_count > descriptor_count_ - expected_descriptor ||
            (((presence & 1U) == 0U) != (common_attribute_bytes == 0U)) ||
            (common_attribute_bytes != 0U &&
             (common_attribute_bytes < 4U || common_attribute_bytes > 132U ||
              common_attribute_bytes % 4U != 0U)) ||
            ((presence & (1U << 4U)) == 0U &&
             (read_u64(section.bytes, offset + 8) != 0U ||
              read_u64(section.bytes, offset + 16) != 0U))) {
            *this = {};
            return false;
        }
        expected_hurtbox += hurtbox_count;
        expected_state += state_count;
        expected_descriptor += descriptor_count;
    }
    if (expected_state != state_count_ || expected_hurtbox != hurtbox_count_ ||
        expected_descriptor != descriptor_count_) {
        *this = {};
        return false;
    }

    for (std::uint32_t index = 0; index < state_count_; ++index) {
        const auto offset = states_offset_ +
            static_cast<std::uint64_t>(index) * article_state_record_bytes;
        const auto presence = read_u32(section.bytes, offset);
        const auto script_offset = read_u64(section.bytes, offset + 8);
        const auto script_size = read_u32(section.bytes, offset + 16);
        if ((presence & ~known_state_presence) != 0U || script_offset < blob_offset_ ||
            !range_fits(script_offset, script_size, section.bytes.size()) ||
            !zero_range(section.bytes, offset + 4, 4) ||
            !zero_range(section.bytes, offset + 28, 12)) {
            *this = {};
            return false;
        }
    }

    std::uint32_t expected_parameter = 0;
    for (std::uint32_t index = 0; index < descriptor_count_; ++index) {
        const auto offset = descriptors_offset_ +
            static_cast<std::uint64_t>(index) * article_dynamic_descriptor_bytes;
        const auto first = read_u32(section.bytes, offset + 4);
        const auto count = read_u32(section.bytes, offset + 8);
        if (first != expected_parameter || count > parameter_count_ - expected_parameter ||
            !zero_range(section.bytes, offset + 24, 8)) {
            *this = {};
            return false;
        }
        expected_parameter += count;
    }
    if (expected_parameter != parameter_count_) {
        *this = {};
        return false;
    }

    section_ = section;
    return true;
}

bool ArticlesView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t ArticlesView::source_count() const noexcept { return source_count_; }
std::uint32_t ArticlesView::slot_count() const noexcept { return slot_count_; }
std::uint32_t ArticlesView::state_count() const noexcept { return state_count_; }
std::uint32_t ArticlesView::hurtbox_count() const noexcept { return hurtbox_count_; }
std::uint32_t ArticlesView::descriptor_count() const noexcept { return descriptor_count_; }
std::uint32_t ArticlesView::parameter_count() const noexcept { return parameter_count_; }

ArticleSourceRecord ArticlesView::source(std::uint32_t index) const noexcept
{
    if (!valid() || index >= source_count_) return {};
    const auto offset = sources_offset_ +
        static_cast<std::uint64_t>(index) * article_source_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
    };
}

ArticleSourceRecord ArticlesView::find_source(
    std::uint64_t file_name_hash,
    std::uint64_t root_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < source_count_; ++index) {
        const auto candidate = source(index);
        if (candidate.file_name_hash == file_name_hash &&
            (root_name_hash == 0U || candidate.root_name_hash == root_name_hash)) {
            return candidate;
        }
    }
    return {};
}

ArticleSlotRecord ArticlesView::slot(std::uint32_t index) const noexcept
{
    if (!valid() || index >= slot_count_) return {};
    const auto offset = slots_offset_ +
        static_cast<std::uint64_t>(index) * article_slot_record_bytes;
    return {
        read_u32(section_.bytes, offset) != 0U,
        read_u32(section_.bytes, offset + 4),
        read_u64(section_.bytes, offset + 8),
        read_u64(section_.bytes, offset + 16),
        std::to_integer<std::uint8_t>(
            section_.bytes[static_cast<std::size_t>(offset + 24)]),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 156)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 160)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 164)),
        read_u32(section_.bytes, offset + 168),
        read_u32(section_.bytes, offset + 172),
        read_u32(section_.bytes, offset + 176),
        read_u32(section_.bytes, offset + 180),
        read_u32(section_.bytes, offset + 184),
        read_u32(section_.bytes, offset + 188),
        read_u32(section_.bytes, offset + 192),
        read_u32(section_.bytes, offset + 196),
        read_u32(section_.bytes, offset + 200),
        read_u32(section_.bytes, offset + 204),
    };
}

std::uint32_t ArticlesView::common_attribute_word(
    std::uint32_t slot_index,
    std::uint32_t word_index) const noexcept
{
    if (!valid() || slot_index >= slot_count_ ||
        word_index >= article_common_attribute_words) return 0;
    const auto offset = slots_offset_ +
        static_cast<std::uint64_t>(slot_index) * article_slot_record_bytes;
    return read_u32(section_.bytes, offset + 28U + word_index * 4U);
}

ArticleStateRecord ArticlesView::state(std::uint32_t index) const noexcept
{
    if (!valid() || index >= state_count_) return {};
    const auto offset = states_offset_ +
        static_cast<std::uint64_t>(index) * article_state_record_bytes;
    const auto script_offset = read_u64(section_.bytes, offset + 8);
    const auto script_size = read_u32(section_.bytes, offset + 16);
    return {
        read_u32(section_.bytes, offset),
        section_.bytes.subspan(static_cast<std::size_t>(script_offset), script_size),
        read_u32(section_.bytes, offset + 20),
        read_u32(section_.bytes, offset + 24),
    };
}

ArticleHurtboxRecord ArticlesView::hurtbox(std::uint32_t index) const noexcept
{
    ArticleHurtboxRecord result{};
    if (!valid() || index >= hurtbox_count_) return result;
    const auto offset = hurtboxes_offset_ +
        static_cast<std::uint64_t>(index) * article_hurtbox_record_bytes;
    result.bone_index = std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset));
    for (std::size_t value = 0; value < result.value_bits.size(); ++value)
        result.value_bits[value] = read_u32(section_.bytes, offset + 4U + value * 4U);
    return result;
}

ArticleDynamicDescriptorRecord ArticlesView::descriptor(
    std::uint32_t index) const noexcept
{
    if (!valid() || index >= descriptor_count_) return {};
    const auto offset = descriptors_offset_ +
        static_cast<std::uint64_t>(index) * article_dynamic_descriptor_bytes;
    return {
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        read_u32(section_.bytes, offset + 4),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
    };
}

ArticleDynamicParameterRecord ArticlesView::parameter(
    std::uint32_t index) const noexcept
{
    ArticleDynamicParameterRecord result{};
    if (!valid() || index >= parameter_count_) return result;
    const auto offset = parameters_offset_ +
        static_cast<std::uint64_t>(index) * article_dynamic_parameter_bytes;
    for (std::size_t value = 0; value < result.value_bits.size(); ++value)
        result.value_bits[value] = read_u32(section_.bytes, offset + value * 4U);
    return result;
}

} // namespace pf::ssbm
