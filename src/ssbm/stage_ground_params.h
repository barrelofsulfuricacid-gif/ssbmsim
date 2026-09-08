#ifndef PF_SSBM_STAGE_GROUND_PARAMS_H
#define PF_SSBM_STAGE_GROUND_PARAMS_H

#include "asset_pack.h"

#include <cstdint>
#include <span>

namespace pf::ssbm {

inline constexpr std::uint32_t stage_ground_param_schema = 1;
inline constexpr std::uint32_t stage_ground_param_record_bytes = 48;
inline constexpr std::uint32_t stage_ground_param_image_bytes = 0xDC;
inline constexpr std::uint32_t stage_param_row_bytes = 0x64;

struct StageGroundParamRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint64_t image_offset{};
    std::uint64_t rows_offset{};
    std::uint32_t row_count{};
};

class StageGroundParamView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] StageGroundParamRecord record(std::uint32_t index) const noexcept;
    [[nodiscard]] StageGroundParamRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] std::span<const std::byte> image(
        const StageGroundParamRecord& stage) const noexcept;
    [[nodiscard]] std::span<const std::byte> rows(
        const StageGroundParamRecord& stage) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint64_t records_offset_{};
};

} // namespace pf::ssbm

#endif
