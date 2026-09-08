#include "runtime.h"
#include "native_compat/native_slippi_spawn.h"
#include "native_compat/native_fd_scene.h"

#include "native_compat/native_gobj_runtime.h"
#include "native_compat/native_competitive_presentation.h"
#include "native_compat/native_pad_input.h"
#include "native_compat/native_post_frame_api.h"
#include "native_compat/native_rng.h"
#include "native_compat/native_slippi.h"
#include "native_compat/native_slippi_frame_start.h"
#include "native_effect_banks.h"
#include "native_item_common.h"
#include "native_player_common.h"
#include "native_stage_assets.h"

#include <algorithm>
#include <bit>

extern "C" void fn_8016E730(void* start_melee_data);
extern "C" void fn_8016B7F8(void);
extern "C" void Stage_802252E4(int stkind, void* context);
extern "C" void gm_Scene_Vs_OnFrame(void);
extern "C" void pf_gm_active_outer_loop_post_frame(void);
extern "C" int HSD_Randi(int maximum);
extern "C" void HSD_SisLib_803A6048(std::size_t size);

namespace pf::ssbm {
namespace {

alignas(std::max_align_t)
    std::array<std::byte, hsd_startup_arena_bytes> startup_arena;
alignas(std::max_align_t)
    std::array<std::byte, hsd_object_arena_bytes> object_arena;
std::uint64_t disabled_process_links;
alignas(PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT)
    std::array<std::byte, PF_SSBM_START_MELEE_DATA_STORAGE_BYTES> match_data;

// A normal VS scene starts recording at Slippi frame -123.  The source-owned
// countdown completes immediately before fighter input processing on frame
// -39, after 84 scheduler steps.  The headless runtime omits the HUD object
// that ordinarily invokes these callbacks, but retains their gameplay work
// and timing: fighter input unfreeze, HUD-visible magnifier state, and the
// source-owned frozen-Stadium completion side effect.
constexpr std::uint64_t vs_countdown_completion_step = 84;

} // namespace

RuntimeStatus Runtime::initialize(
    const AssetPackView& assets,
    MatchState& state,
    const PfSsbmNativeMatchConfig& config) noexcept
{
    assets_ = nullptr;
    state_ = nullptr;
    rng_offset_ = config.random_seed;
    slippi_online_ = config.slippi_online != 0;
    if (!pf_ssbm_native_arithmetic_configure(config.arithmetic_profile)) {
        return RuntimeStatus::unsupported_match;
    }
    if (!assets.valid()) {
        return RuntimeStatus::invalid_assets;
    }
    if (!bind_native_effect_banks(assets) ||
        !bind_native_item_common(assets) ||
        !bind_native_player_common(assets) ||
        !bind_native_stage_assets(assets)) {
        return RuntimeStatus::invalid_assets;
    }
    if (pf_hsd_gobj_runtime_initialize(
            startup_arena.data(),
            startup_arena.size(),
            object_arena.data(),
            object_arena.size(),
            hsd_gobj_capacity,
            hsd_process_capacity,
            &disabled_process_links) != PF_HSD_GOBJ_RUNTIME_OK) {
        return RuntimeStatus::scheduler_initialization_failed;
    }

    if (!pf_ssbm_native_build_start_melee_data(
            match_data.data(), match_data.size(), &config)) {
        return RuntimeStatus::unsupported_match;
    }

    // gm_1A3F.c preloadState initializes the SIS arena before the match scene.
    // Competitive match scenes use the default 0x4800-byte arena.
    HSD_SisLib_803A6048(0x4800);

    pf_ssbm_native_pad_reset();
    pf_ssbm_native_rng_set(config.random_seed);
    pf_ssbm_native_slippi_configure(
        config.slippi_neutral_spawns != 0,
        slippi_online_);
    pf_ssbm_native_slippi_stadium_configure(config.frozen_stadium != 0);
    pf_ssbm_native_fd_scene_configure(config.fd_scene_mode);
    pf_ssbm_native_slippi_frame_start_reset();
    fn_8016E730(match_data.data());
    if (!pf_ifStatus_headless_initialize()) {
        return RuntimeStatus::scheduler_initialization_failed;
    }
    if (config.frozen_stadium != 0) {
        // Slippi console core's pinned Preload Stadium Transformations hook
        // decides and asynchronously preloads one transformation before the
        // first recorded frame. The native pack is already resident and
        // acceptance Stadium is frozen, so only its shared gameplay-RNG draw
        // remains observable. Preserve the exact HSD_Randi(4) side effect.
        (void) HSD_Randi(4);
        pf_ssbm_native_slippi_stadium_mark_preloaded();
    }
    if (pf_hsd_gobj_runtime_begin_deferred_process_capture() !=
            PF_HSD_GOBJ_RUNTIME_OK) {
        return RuntimeStatus::scheduler_initialization_failed;
    }
    Stage_802252E4(config.stage_kind, nullptr);
    if (pf_hsd_gobj_runtime_end_deferred_process_capture() !=
            PF_HSD_GOBJ_RUNTIME_OK ||
        !pf_ssbm_native_slippi_frame_start_installed() ||
        pf_hsd_gobj_runtime_prewarm_memory_pool(
            hsd_memory_pieces_per_size_class) != PF_HSD_GOBJ_RUNTIME_OK ||
        pf_hsd_gobj_runtime_finalize_initialization() !=
        PF_HSD_GOBJ_RUNTIME_OK) {
        return RuntimeStatus::scheduler_initialization_failed;
    }

    assets_ = &assets;
    state_ = &state;
    state_->frame = 0;
    state_->frame_start_rng = 0;
    state_->hsd_rng = pf_ssbm_native_rng_get();
    return RuntimeStatus::ok;
}

RuntimeStatus Runtime::step(
    std::span<const ControllerSample> input) noexcept
{
    if (assets_ == nullptr || state_ == nullptr) {
        return RuntimeStatus::invalid_assets;
    }
    if (input.size() != max_players) {
        return RuntimeStatus::wrong_input_count;
    }
    if (state_->frame == vs_countdown_completion_step) {
        fn_8016B7F8();
        if (!pf_hsd_gobj_runtime_deferred_stage_start_is_active() ||
            pf_ifStatus_headless_go_completion_failed()) {
            // fn_8016B7F8 owns the source callback order and activates the
            // preconstructed stage-start processes through its host
            // adaptation.
            return RuntimeStatus::scheduler_initialization_failed;
        }
    }
    std::copy(input.begin(), input.end(), state_->input.begin());
    if (slippi_online_) {
        // Slippi's SyncRNG process runs first each online frame. The actual
        // Gecko code rotates the global frame by 16 and adds the match RNG
        // offset, preventing rollback order from changing gameplay RNG.
        const auto frame = static_cast<std::uint32_t>(state_->frame);
        pf_ssbm_native_rng_set(
            std::rotl(frame, 16) + rng_offset_);
    }
    pf_ssbm_native_slippi_spawn_begin_frame(state_->frame);
    pf_ssbm_native_slippi_frame_start_begin_frame();
    std::array<PfSsbmNativePadSample, max_players> native_input{};
    for (std::size_t index = 0; index < input.size(); ++index) {
        native_input[index] = {
            input[index].buttons,
            input[index].main_x,
            input[index].main_y,
            input[index].c_x,
            input[index].c_y,
            input[index].left_trigger,
            input[index].right_trigger,
            input[index].raw_main_x,
            input[index].raw_main_y,
            input[index].raw_c_x,
            input[index].raw_c_y,
        };
    }
    pf_ssbm_native_apply_pad_samples(native_input.data());
    pf_ssbm_native_post_frame_begin();
    // gm_801A4D34 invokes the active scene's on_frame callback after input
    // evaluation and immediately before HSD_GObj_80390CFC.  The native
    // runtime owns that outer loop, so preserve the same direct-source call
    // and ordering here.  Match timers, pause/outcome checks, and respawn-slot
    // cooldowns all live in this callback rather than in a GObj process.
    gm_Scene_Vs_OnFrame();
    pf_hsd_gobj_runtime_step();
    if (!pf_ssbm_native_slippi_frame_start_take(
            &state_->frame_start_rng)) {
        return RuntimeStatus::scheduler_initialization_failed;
    }
    // gm_801A4D34 advances these source-owned counters immediately after the
    // scheduler.  Runtime::step is the active, unpaused headless equivalent of
    // one inner-loop sample, so retain that post-frame ordering explicitly.
    pf_gm_active_outer_loop_post_frame();
    pf_hsd_gobj_runtime_post_frame();
    state_->hsd_rng = pf_ssbm_native_rng_get();
    ++state_->frame;
    return RuntimeStatus::ok;
}

} // namespace pf::ssbm
