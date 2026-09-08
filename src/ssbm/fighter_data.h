#ifndef PF_SSBM_FIGHTER_DATA_H
#define PF_SSBM_FIGHTER_DATA_H

#include "asset_pack.h"

#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t fighter_attributes_schema = 1;
inline constexpr std::uint32_t fighter_attribute_words = 97;
inline constexpr std::uint32_t fighter_attribute_record_bytes = 32;

struct FighterAttributeRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint64_t words_offset{};
    std::uint32_t word_count{};
};

class FighterAttributesView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] FighterAttributeRecord record(std::uint32_t index) const noexcept;
    [[nodiscard]] FighterAttributeRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] std::uint32_t word(
        const FighterAttributeRecord& fighter,
        std::uint32_t index) const noexcept;
    [[nodiscard]] float scalar(
        const FighterAttributeRecord& fighter,
        std::uint32_t byte_offset) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint64_t records_offset_{};
};

} // namespace pf::ssbm

#endif
