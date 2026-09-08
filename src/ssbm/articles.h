#ifndef PF_SSBM_ARTICLES_H
#define PF_SSBM_ARTICLES_H

#include "asset_pack.h"

#include <array>
#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t articles_schema = 1;
inline constexpr std::uint32_t article_source_record_bytes = 40;
inline constexpr std::uint32_t article_slot_record_bytes = 208;
inline constexpr std::uint32_t article_state_record_bytes = 40;
inline constexpr std::uint32_t article_hurtbox_record_bytes = 32;
inline constexpr std::uint32_t article_dynamic_descriptor_bytes = 32;
inline constexpr std::uint32_t article_dynamic_parameter_bytes = 60;
inline constexpr std::uint32_t article_common_attribute_words = 32;

struct ArticleSourceRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t group_kind{};
    std::uint32_t first_slot{};
    std::uint32_t slot_count{};
};

struct ArticleSlotRecord {
    bool present{};
    std::uint32_t presence{};
    std::uint64_t model_file_name_hash{};
    std::uint64_t model_root_name_hash{};
    std::uint8_t common_byte{};
    std::int32_t model_bone_count{};
    std::int32_t model_attach_bone{};
    std::int32_t model_flags{};
    std::uint32_t first_hurtbox{};
    std::uint32_t hurtbox_count{};
    std::uint32_t first_state{};
    std::uint32_t state_count{};
    std::uint32_t first_dynamic_descriptor{};
    std::uint32_t dynamic_descriptor_count{};
    std::uint32_t extension_bytes{};
    std::uint32_t extension_reference_count{};
    std::uint32_t declared_dynamic_count{};
    std::uint32_t common_attribute_bytes{};
};

struct ArticleStateRecord {
    std::uint32_t presence{};
    std::span<const std::byte> script{};
    std::uint32_t parameter_bytes{};
    std::uint32_t parameter_reference_count{};
};

struct ArticleHurtboxRecord {
    std::int32_t bone_index{};
    std::array<std::uint32_t, 7> value_bits{};
};

struct ArticleDynamicDescriptorRecord {
    std::int32_t bone_index{};
    std::uint32_t first_parameter{};
    std::uint32_t parameter_count{};
    std::uint32_t drag_bits{};
    std::uint32_t stiffness_bits{};
    std::uint32_t gravity_bits{};
};

struct ArticleDynamicParameterRecord {
    std::array<std::uint32_t, 15> value_bits{};
};

class ArticlesView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t source_count() const noexcept;
    [[nodiscard]] std::uint32_t slot_count() const noexcept;
    [[nodiscard]] std::uint32_t state_count() const noexcept;
    [[nodiscard]] std::uint32_t hurtbox_count() const noexcept;
    [[nodiscard]] std::uint32_t descriptor_count() const noexcept;
    [[nodiscard]] std::uint32_t parameter_count() const noexcept;
    [[nodiscard]] ArticleSourceRecord source(std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleSourceRecord find_source(
        std::uint64_t file_name_hash,
        std::uint64_t root_name_hash = 0) const noexcept;
    [[nodiscard]] ArticleSlotRecord slot(std::uint32_t index) const noexcept;
    [[nodiscard]] std::uint32_t common_attribute_word(
        std::uint32_t slot_index,
        std::uint32_t word_index) const noexcept;
    [[nodiscard]] ArticleStateRecord state(std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleHurtboxRecord hurtbox(std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleDynamicDescriptorRecord descriptor(
        std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleDynamicParameterRecord parameter(
        std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t source_count_{};
    std::uint32_t slot_count_{};
    std::uint32_t state_count_{};
    std::uint32_t hurtbox_count_{};
    std::uint32_t descriptor_count_{};
    std::uint32_t parameter_count_{};
    std::uint64_t sources_offset_{};
    std::uint64_t slots_offset_{};
    std::uint64_t states_offset_{};
    std::uint64_t hurtboxes_offset_{};
    std::uint64_t descriptors_offset_{};
    std::uint64_t parameters_offset_{};
    std::uint64_t blob_offset_{};
};

} // namespace pf::ssbm

#endif
