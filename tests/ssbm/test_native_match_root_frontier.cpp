#include "mapped_pack.h"
#include "native_effect_banks.h"
#include "native_item_common.h"
#include "native_player_common.h"
#include "native_stage_assets.h"

extern "C" {
#include "native_compat/native_fail_closed_boundaries.h"
#include "native_compat/native_archive_root_api.h"
#include "native_compat/native_fighter_common_api.h"
#include "native_compat/native_gobj_runtime.h"
#include "native_compat/native_item_common_api.h"
#include "native_compat/native_match_setup.h"

void fn_8016E730(void* start_melee_data);
}

#include <csetjmp>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace {

constexpr std::uint16_t battlefield_stage_kind = 0x1F;
constexpr std::int8_t captain_character_kind = 0;
constexpr unsigned int frontier_frame_count = 600;

alignas(std::max_align_t) unsigned char startup_arena[64 * 1024 * 1024];
alignas(std::max_align_t) unsigned char object_arena[4 * 1024 * 1024];
alignas(PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT)
    unsigned char match_storage[PF_SSBM_START_MELEE_DATA_STORAGE_BYTES];
unsigned long long disabled_process_links;
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
    if (argc > 2) {
        std::fputs("usage: ssbm_match_root_frontier_test [asset-pack]\n", stderr);
        return 2;
    }
    pf::ssbm::MappedPack pack;
    if (argc == 2 &&
        (pack.open(argv[1]) != pf::ssbm::PackStatus::ok ||
         !pf::ssbm::bind_native_effect_banks(pack.view()) ||
         !pf::ssbm::bind_native_item_common(pack.view()) ||
         !pf::ssbm::bind_native_player_common(pack.view()) ||
         !pf::ssbm::bind_native_stage_assets(pack.view()))) {
        std::fputs("ssbm-match-root-frontier=asset-fail\n", stderr);
        return 1;
    }
    if (argc == 2) {
        auto** item_public = static_cast<void**>(
            pf_ssbm_native_item_common_require());
        auto* item_common = static_cast<unsigned char*>(item_public[0]);
        std::uint32_t item_count{};
        std::uint32_t knockback_scale{};
        std::uint32_t knockback_cap{};
        if (item_common == nullptr) {
            std::fputs("ssbm-match-root-frontier=item-common-missing\n", stderr);
            return 1;
        }
        std::memcpy(&item_count, item_common, sizeof(item_count));
        std::memcpy(&knockback_scale, item_common + 0x80,
            sizeof(knockback_scale));
        std::memcpy(&knockback_cap, item_common + 0x9C,
            sizeof(knockback_cap));
        if (item_count != 40U || knockback_scale != 0x3F19999AU ||
            knockback_cap != 0x451C4000U) {
            std::fprintf(stderr,
                "ssbm-match-root-frontier=item-common-endian-invalid "
                "count=%u scale=%08x cap=%08x\n",
                item_count, knockback_scale, knockback_cap);
            return 1;
        }
        auto** common = static_cast<void**>(
            pf_ssbm_native_fighter_common_require());
        auto* item_throw_attributes =
            static_cast<unsigned char*>(common[1]);
        constexpr unsigned int light_throw_f4_row = 14;
        constexpr unsigned int item_throw_row_bytes = 3 * sizeof(std::uint32_t);
        std::uint32_t throw_velocity{};
        std::uint32_t throw_angle{};
        std::uint32_t throw_scale{};
        if (item_throw_attributes != nullptr) {
            const auto row_offset = light_throw_f4_row * item_throw_row_bytes;
            std::memcpy(&throw_velocity, item_throw_attributes + row_offset,
                sizeof(throw_velocity));
            std::memcpy(&throw_angle,
                item_throw_attributes + row_offset + sizeof(std::uint32_t),
                sizeof(throw_angle));
            std::memcpy(&throw_scale,
                item_throw_attributes + row_offset + 2 * sizeof(std::uint32_t),
                sizeof(throw_scale));
        }
        if (item_throw_attributes == nullptr ||
            throw_velocity != 0x4068F5C3U || throw_angle != 0x3E449809U ||
            throw_scale != 0x3F800000U) {
            std::fprintf(stderr,
                "ssbm-match-root-frontier=item-throw-endian-invalid "
                "velocity=%08x angle=%08x scale=%08x\n",
                throw_velocity, throw_angle, throw_scale);
            return 1;
        }
        auto** part_tables = static_cast<void**>(common[5]);
        if (part_tables == nullptr) {
            std::fputs("ssbm-match-root-frontier=part-table-missing\n", stderr);
            return 1;
        }
        for (unsigned int kind = 0; kind < 0x22U; ++kind) {
            auto* descriptor = static_cast<unsigned char*>(part_tables[kind]);
            if (descriptor == nullptr) continue;
            std::int32_t count{};
            std::memcpy(&count, descriptor + sizeof(void*), sizeof(count));
            if (count < 0 || count > 32) {
                std::fprintf(stderr,
                    "ssbm-match-root-frontier=part-count-invalid "
                    "kind=%u count=%d\n",
                    kind, count);
                return 1;
            }
        }
        auto** captain_data = static_cast<void**>(
            pf_ssbm_native_archive_root_require(
                "PlCa.dat", "ftDataCaptain"));
        auto* captain_attributes = captain_data == nullptr
            ? nullptr
            : static_cast<unsigned char*>(captain_data[0]);
        if (captain_attributes == nullptr ||
            captain_attributes[0x180] != 0x07U ||
            captain_attributes[0x181] != 0U ||
            captain_attributes[0x182] != 0U ||
            captain_attributes[0x183] != 0U) {
            std::fprintf(stderr,
                "ssbm-match-root-frontier=fighter-throw-mask-endian-invalid "
                "bytes=%02x,%02x,%02x,%02x\n",
                captain_attributes == nullptr ? 0U : captain_attributes[0x180],
                captain_attributes == nullptr ? 0U : captain_attributes[0x181],
                captain_attributes == nullptr ? 0U : captain_attributes[0x182],
                captain_attributes == nullptr ? 0U : captain_attributes[0x183]);
            return 1;
        }
        auto** yoshi_data = static_cast<void**>(
            pf_ssbm_native_archive_root_require(
                "PlYs.dat", "ftDataYoshi"));
        auto* yoshi_attributes = yoshi_data == nullptr
            ? nullptr
            : static_cast<unsigned char*>(yoshi_data[1]);
        constexpr unsigned char yoshi_catch_pull_frames[] = {
            46, 44, 42, 40, 38, 36, 34, 33, 32, 31, 29, 29,
        };
        if (yoshi_attributes == nullptr ||
            std::memcmp(
                yoshi_attributes + 0x12C, yoshi_catch_pull_frames,
                sizeof(yoshi_catch_pull_frames)) != 0) {
            std::fprintf(
                stderr,
                "ssbm-match-root-frontier=yoshi-catch-pull-byte-order-invalid "
                "bytes=%02x,%02x,%02x,%02x,%02x,%02x,%02x,%02x,%02x,%02x,%02x,%02x\n",
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x12C],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x12D],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x12E],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x12F],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x130],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x131],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x132],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x133],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x134],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x135],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x136],
                yoshi_attributes == nullptr ? 0U : yoshi_attributes[0x137]);
            return 1;
        }
        auto** zelda_data = static_cast<void**>(
            pf_ssbm_native_archive_root_require(
                "PlZd.dat", "ftDataZelda"));
        if (zelda_data == nullptr || zelda_data[0] == nullptr) {
            std::fputs(
                "ssbm-match-root-frontier=transitive-zelda-data-missing\n",
                stderr);
            return 1;
        }
        auto** sheik_data = static_cast<void**>(
            pf_ssbm_native_archive_root_require(
                "PlSk.dat", "ftDataSeak"));
        auto** articles = sheik_data == nullptr
            ? nullptr
            : static_cast<void**>(sheik_data[0x48 / sizeof(void*)]);
        auto** needle_article = articles == nullptr
            ? nullptr
            : static_cast<void**>(articles[0]);
        auto* needle_states = needle_article == nullptr
            ? nullptr
            : static_cast<unsigned char*>(needle_article[3]);
        void* bounce_script = nullptr;
        if (needle_states != nullptr) {
            std::memcpy(
                &bounce_script,
                needle_states + 4 * 0x10 + 0x0C,
                sizeof(bounce_script));
        }
        auto* bounce_bytes = static_cast<unsigned char*>(bounce_script);
        bool bounce_script_valid = bounce_bytes != nullptr &&
            bounce_bytes[0] == 0x40U;
        for (unsigned int index = 1;
             bounce_script_valid && index < 16;
             ++index) {
            bounce_script_valid = bounce_bytes[index] == 0U;
        }
        if (!bounce_script_valid) {
            std::fputs(
                "ssbm-match-root-frontier=needle-command-extent-invalid\n",
                stderr);
            return 1;
        }
    }

    const auto config = match_config();
    if (pf_hsd_gobj_runtime_initialize(
            startup_arena, sizeof(startup_arena), object_arena,
            sizeof(object_arena), 4096, 8192,
            &disabled_process_links) != PF_HSD_GOBJ_RUNTIME_OK ||
        !pf_ssbm_native_build_start_melee_data(
            match_storage, sizeof(match_storage), &config)) {
        std::fputs("ssbm-match-root-frontier=setup-fail\n", stderr);
        return 1;
    }

    pf_ssbm_set_unsupported_boundary_handler(capture_unsupported_boundary);
    if (setjmp(unsupported_boundary_jump) == 0) {
        fn_8016E730(match_storage);
        if (pf_hsd_gobj_runtime_prewarm_memory_pool(256) !=
                PF_HSD_GOBJ_RUNTIME_OK ||
            pf_hsd_gobj_runtime_finalize_initialization() !=
            PF_HSD_GOBJ_RUNTIME_OK) {
            std::fputs("ssbm-match-root-frontier=freeze-fail\n", stderr);
            return 1;
        }
        const auto startup_bytes_before_steps =
            pf_hsd_gobj_runtime_startup_bytes_used();
        for (unsigned int frame = 0; frame < frontier_frame_count; ++frame) {
            pf_hsd_gobj_runtime_step();
        }
        const auto startup_bytes_after_steps =
            pf_hsd_gobj_runtime_startup_bytes_used();
        pf_ssbm_set_unsupported_boundary_handler(nullptr);
        std::printf(
            "ssbm-match-root-frontier=complete frames=%u "
            "runtime-allocation-bytes=%zu\n",
            frontier_frame_count,
            startup_bytes_after_steps - startup_bytes_before_steps);
        return 0;
    }
    pf_ssbm_set_unsupported_boundary_handler(nullptr);

    if (reached_boundary == nullptr ||
        reached_boundary != pf_ssbm_last_unsupported_boundary) {
        std::fputs("ssbm-match-root-frontier=invalid-boundary\n", stderr);
        return 1;
    }
    std::printf("ssbm-match-root-frontier=pass boundary=%s\n", reached_boundary);
    if (pf_ssbm_last_unsupported_detail != nullptr)
        std::printf("ssbm-match-root-frontier-detail=%s\n",
            pf_ssbm_last_unsupported_detail);
    return 0;
}
