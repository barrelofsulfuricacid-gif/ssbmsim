#include "mapped_pack.h"
#include "runtime.h"

extern "C" {
#include "native_compat/native_fail_closed_boundaries.h"
#include "native_compat/native_fighter_state.h"
#include "native_compat/native_gobj_runtime.h"

unsigned int gm_801A4BA8(void);
unsigned int gm_801A4BB8(void);
}

#include <array>
#include <csetjmp>
#include <cstdint>
#include <cstdio>

namespace {

constexpr std::uint16_t battlefield_stage_kind = 0x1F;
constexpr std::int8_t captain_character_kind = 0;
constexpr std::uint32_t x_button = 1U << 10U;
constexpr std::uint32_t a_button = 1U << 8U;
constexpr unsigned int frontier_frame_count = 600;

std::jmp_buf unsupported_boundary_jump;
const char* reached_boundary;

void capture_unsupported_boundary(const char* name)
{
    reached_boundary = name;
    std::longjmp(unsupported_boundary_jump, 1);
}

PfSsbmNativeMatchConfig match_config()
{
    PfSsbmNativeMatchConfig config{};
    config.stage_kind = battlefield_stage_kind;
    config.stock_count = 4;
    config.disable_pausing = 1;
    config.ucf_084_enabled = 1;
    config.random_seed = 0x12345678U;
    config.time_limit_seconds = 8 * 60;
    config.damage_ratio = 1.0F;
    config.game_speed = 1.0F;
    config.players[0].present = 1;
    config.players[0].character_kind = captain_character_kind;
    config.players[1].present = 1;
    config.players[1].character_kind = captain_character_kind;
    return config;
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2) {
        std::fputs("usage: ssbm_runtime_frontier_test <asset-pack>\n", stderr);
        return 2;
    }

    pf::ssbm::MappedPack pack;
    if (pack.open(argv[1]) != pf::ssbm::PackStatus::ok) {
        std::fputs("ssbm-runtime-frontier=asset-fail\n", stderr);
        return 1;
    }

    pf::ssbm::MatchState state{};
    pf::ssbm::Runtime runtime;
    const auto config = match_config();
    pf_ssbm_set_unsupported_boundary_handler(capture_unsupported_boundary);
    if (setjmp(unsupported_boundary_jump) == 0) {
        if (runtime.initialize(pack.view(), state, config) !=
            pf::ssbm::RuntimeStatus::ok) {
            std::fputs("ssbm-runtime-frontier=setup-fail\n", stderr);
            return 1;
        }

        const auto outer_frames_before_steps = gm_801A4BA8();
        const auto active_frames_before_steps = gm_801A4BB8();
        const auto startup_bytes_before_steps =
            pf_hsd_gobj_runtime_startup_bytes_used();
        std::array<pf::ssbm::ControllerSample, pf::ssbm::max_players> input{};
        for (unsigned int frame = 0; frame < frontier_frame_count; ++frame) {
            input = {};
            if (frame >= 60 && frame < 240) {
                input[0].main_x = 1.0F;
                input[0].raw_main_x = 80;
                input[1].main_x = -1.0F;
                input[1].raw_main_x = -80;
            }
            if (frame == 120) {
                input[0].buttons = x_button;
            }
            if (frame == 240) {
                input[0].buttons = a_button;
            }
            if (runtime.step(input) !=
                pf::ssbm::RuntimeStatus::ok) {
                std::fputs("ssbm-runtime-frontier=step-fail\n", stderr);
                return 1;
            }
        }
        const auto startup_bytes_after_steps =
            pf_hsd_gobj_runtime_startup_bytes_used();
        PfSsbmNativeFighterState player_zero{};
        PfSsbmNativeFighterState player_one{};
        pf_ssbm_set_unsupported_boundary_handler(nullptr);
        const auto runtime_allocation_bytes =
            startup_bytes_after_steps - startup_bytes_before_steps;
        if (!pf_ssbm_native_read_fighter_state(0, &player_zero) ||
            !pf_ssbm_native_read_fighter_state(1, &player_one) ||
            !player_zero.present || !player_one.present ||
            state.frame != frontier_frame_count || runtime_allocation_bytes != 0 ||
            gm_801A4BA8() - outer_frames_before_steps != frontier_frame_count ||
            gm_801A4BB8() - active_frames_before_steps != frontier_frame_count) {
            std::fprintf(
                stderr,
                "ssbm-runtime-frontier=state-fail frames=%llu "
                "runtime-allocation-bytes=%zu outer-frames=%u "
                "active-frames=%u\n",
                static_cast<unsigned long long>(state.frame),
                runtime_allocation_bytes,
                gm_801A4BA8() - outer_frames_before_steps,
                gm_801A4BB8() - active_frames_before_steps);
            return 1;
        }
        std::printf(
            "ssbm-runtime-frontier=complete frames=%u "
            "runtime-allocation-bytes=%zu active-inputs=3 "
            "fighters=2 p0-action=%d p1-action=%d\n",
            frontier_frame_count,
            runtime_allocation_bytes,
            player_zero.action_state_id,
            player_one.action_state_id);
        return 0;
    }
    pf_ssbm_set_unsupported_boundary_handler(nullptr);

    if (reached_boundary == nullptr ||
        reached_boundary != pf_ssbm_last_unsupported_boundary) {
        std::fputs("ssbm-runtime-frontier=invalid-boundary\n", stderr);
        return 1;
    }
    std::printf("ssbm-runtime-frontier=unsupported boundary=%s\n", reached_boundary);
    if (pf_ssbm_last_unsupported_detail != nullptr) {
        std::printf(
            "ssbm-runtime-frontier-detail=%s\n",
            pf_ssbm_last_unsupported_detail);
    }
    return 1;
}
