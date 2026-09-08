#ifndef PF_SSBM_RUNTIME_H
#define PF_SSBM_RUNTIME_H

#include "asset_pack.h"
#include "native_compat/native_match_setup.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace pf::ssbm {

inline constexpr std::size_t max_players = 4;
inline constexpr std::size_t hsd_startup_arena_bytes = 64 * 1024 * 1024;
inline constexpr std::size_t hsd_object_arena_bytes = 4 * 1024 * 1024;
inline constexpr std::uint32_t hsd_gobj_capacity = 4096;
inline constexpr std::uint32_t hsd_process_capacity = 8192;
inline constexpr std::uint32_t hsd_memory_pieces_per_size_class = 256;

struct ControllerSample {
    std::uint32_t buttons{};
    float main_x{};
    float main_y{};
    float c_x{};
    float c_y{};
    float left_trigger{};
    float right_trigger{};
    std::int8_t raw_main_x{};
    std::int8_t raw_main_y{};
    std::int8_t raw_c_x{};
    std::int8_t raw_c_y{};
};

struct MatchState {
    std::uint64_t frame{};
    std::uint32_t frame_start_rng{};
    std::uint32_t hsd_rng{};
    std::uint32_t match_rng{};
    std::array<ControllerSample, max_players> input{};
};

enum class RuntimeStatus : std::uint8_t {
    ok,
    invalid_assets,
    wrong_input_count,
    scheduler_initialization_failed,
    unsupported_match,
};

class Runtime final {
public:
    [[nodiscard]] RuntimeStatus initialize(
        const AssetPackView& assets,
        MatchState& state,
        const PfSsbmNativeMatchConfig& config) noexcept;
    [[nodiscard]] RuntimeStatus step(
        std::span<const ControllerSample> input) noexcept;

private:
    const AssetPackView* assets_{};
    MatchState* state_{};
    std::uint32_t rng_offset_{};
    bool slippi_online_{};
};

} // namespace pf::ssbm

#endif
