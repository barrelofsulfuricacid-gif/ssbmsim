#ifndef PF_SSBM_SOURCE_CATALOG_H
#define PF_SSBM_SOURCE_CATALOG_H

#include "asset_pack.h"

#include <cstdint>
#include <string_view>

namespace pf::ssbm {

inline constexpr std::uint32_t source_catalog_schema = 1;
inline constexpr std::uint32_t source_catalog_record_bytes = 72;

struct SourceCatalogRecord {
    std::string_view path{};
    std::uint64_t source_bytes{};
    std::span<const std::byte> sha256{};
    std::uint32_t root_count{};
    std::uint32_t reference_count{};
    bool empty{};
};

class SourceCatalogView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] SourceCatalogRecord source(std::uint32_t index) const noexcept;
    [[nodiscard]] SourceCatalogRecord find(std::uint64_t path_hash) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint64_t records_offset_{};
    std::uint64_t strings_offset_{};
    std::uint64_t strings_size_{};
};

} // namespace pf::ssbm

#endif
