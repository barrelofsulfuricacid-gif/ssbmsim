#ifndef PF_SSBM_ASSET_PACK_H
#define PF_SSBM_ASSET_PACK_H

#include <cstddef>
#include <cstdint>
#include <span>

namespace pf::ssbm {

inline constexpr std::size_t pack_header_size = 96;
inline constexpr std::size_t section_record_size = 80;
inline constexpr std::uint32_t pack_format_version = 1;
inline constexpr std::uint32_t endian_marker = 0x01020304U;

enum class SectionKind : std::uint32_t {
    source_catalog = 1,
    fighter_data = 4,
    stage_data = 5,
    item_data = 6,
    animation_data = 7,
    effect_data = 8,
    player_data = 9,
};

struct SectionView {
    SectionKind kind{};
    std::uint32_t schema_version{};
    std::uint64_t name_hash{};
    std::span<const std::byte> bytes{};
    std::uint32_t count{};
    std::uint32_t stride{};
};

enum class PackStatus : std::uint8_t {
    ok,
    too_small,
    bad_magic,
    unsupported_format,
    unsupported_endian,
    bad_layout,
    out_of_bounds,
    duplicate_section,
};

class AssetPackView final {
public:
    [[nodiscard]] PackStatus open(std::span<const std::byte> bytes) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t section_count() const noexcept;
    [[nodiscard]] SectionView section(std::uint32_t index) const noexcept;
    [[nodiscard]] SectionView find(
        SectionKind kind,
        std::uint64_t name_hash = 0) const noexcept;
    [[nodiscard]] std::span<const std::byte>
    source_set_digest() const noexcept;

private:
    std::span<const std::byte> bytes_{};
    std::uint32_t section_count_{};
    std::uint64_t directory_offset_{};
};

[[nodiscard]] std::uint64_t stable_name_hash(
    std::span<const std::byte> name) noexcept;

} // namespace pf::ssbm

#endif
