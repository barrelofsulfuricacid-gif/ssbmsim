#ifndef PF_SSBM_PLAYER_COMMON_H
#define PF_SSBM_PLAYER_COMMON_H

#include "asset_pack.h"

#include <cstdint>
#include <span>

namespace pf::ssbm {

inline constexpr std::uint32_t player_common_schema = 1;
inline constexpr std::uint32_t player_common_header_bytes = 32;
inline constexpr std::uint32_t player_common_word_count = 0x184 / 4;

class PlayerCommonView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint64_t file_name_hash() const noexcept;
    [[nodiscard]] std::uint64_t root_name_hash() const noexcept;
    [[nodiscard]] std::span<const std::byte> data() const noexcept;

private:
    SectionView section_{};
};

} // namespace pf::ssbm

#endif
