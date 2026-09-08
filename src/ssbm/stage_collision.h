#ifndef PF_SSBM_STAGE_COLLISION_H
#define PF_SSBM_STAGE_COLLISION_H

#include "asset_pack.h"

#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t stage_collision_schema = 1;
inline constexpr std::uint32_t stage_collision_record_bytes = 96;
inline constexpr std::uint32_t stage_collision_vertex_bytes = 8;
inline constexpr std::uint32_t stage_collision_line_bytes = 16;
inline constexpr std::uint32_t stage_collision_group_bytes = 40;

struct StageCollisionRange {
    std::int16_t offset{};
    std::int16_t count{};
};

struct StageCollisionRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint64_t vertices_offset{};
    std::uint32_t vertex_count{};
    std::uint64_t lines_offset{};
    std::uint32_t line_count{};
    std::uint64_t groups_offset{};
    std::uint32_t group_count{};
    StageCollisionRange top{};
    StageCollisionRange bottom{};
    StageCollisionRange right{};
    StageCollisionRange left{};
    StageCollisionRange dynamic{};
};

struct StageCollisionVertex {
    std::uint32_t x_bits{};
    std::uint32_t y_bits{};
    [[nodiscard]] float x() const noexcept;
    [[nodiscard]] float y() const noexcept;
};

struct StageCollisionLine {
    std::int16_t vertex_1{};
    std::int16_t vertex_2{};
    std::int16_t next{};
    std::int16_t previous{};
    std::int16_t next_alternate{};
    std::int16_t previous_alternate{};
    std::int16_t collision_flags{};
    std::uint8_t properties{};
    std::uint8_t material{};
};

struct StageCollisionGroup {
    StageCollisionRange top{};
    StageCollisionRange bottom{};
    StageCollisionRange right{};
    StageCollisionRange left{};
    StageCollisionRange dynamic{};
    std::uint32_t x_min_bits{};
    std::uint32_t y_min_bits{};
    std::uint32_t x_max_bits{};
    std::uint32_t y_max_bits{};
    StageCollisionRange vertices{};
    [[nodiscard]] float x_min() const noexcept;
    [[nodiscard]] float y_min() const noexcept;
    [[nodiscard]] float x_max() const noexcept;
    [[nodiscard]] float y_max() const noexcept;
};

class StageCollisionView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t count() const noexcept;
    [[nodiscard]] StageCollisionRecord record(std::uint32_t index) const noexcept;
    [[nodiscard]] StageCollisionRecord find(std::uint64_t file_name_hash) const noexcept;
    [[nodiscard]] StageCollisionVertex vertex(
        const StageCollisionRecord& stage,
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageCollisionLine line(
        const StageCollisionRecord& stage,
        std::uint32_t index) const noexcept;
    [[nodiscard]] StageCollisionGroup group(
        const StageCollisionRecord& stage,
        std::uint32_t index) const noexcept;

private:
    SectionView section_{};
    std::uint32_t count_{};
    std::uint64_t records_offset_{};
};

} // namespace pf::ssbm

#endif
