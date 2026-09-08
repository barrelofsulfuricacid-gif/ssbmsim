#include "asset_pack.h"
#include "native_effect_banks.h"
#include "effect_particles.h"
#include "native_disc_file_name.h"
#include "native_player_common.h"
#include "native_stage_assets.h"
#include "runtime.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <span>
#include <string_view>

namespace {

void write_u32(
    std::span<std::byte> bytes,
    std::size_t offset,
    std::uint32_t value) noexcept
{
    for (std::uint32_t index = 0; index < 4; ++index) {
        bytes[offset + index] =
            static_cast<std::byte>((value >> (index * 8U)) & 0xffU);
    }
}

void write_u64(
    std::span<std::byte> bytes,
    std::size_t offset,
    std::uint64_t value) noexcept
{
    write_u32(bytes, offset, static_cast<std::uint32_t>(value));
    write_u32(bytes, offset + 4, static_cast<std::uint32_t>(value >> 32U));
}

[[nodiscard]] bool run()
{
    constexpr std::string_view stadium_file{"GrPs.dat"};
    const auto stadium_hash = pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(stadium_file.data()),
        stadium_file.size()});
    if (pf::ssbm::native_disc_file_name_hash("/GrPs") != stadium_hash ||
        pf::ssbm::native_disc_file_name_hash("/GrPs.dat") != stadium_hash ||
        pf::ssbm::native_disc_file_name_hash("files\\GrPs") != stadium_hash) {
        std::fputs("ssbm-runtime=disc-name-normalization-fail\n", stderr);
        return false;
    }

    constexpr std::size_t payload_offset = 416;
    constexpr std::size_t effect_offset = payload_offset;
    constexpr std::size_t effect_size = 64;
    constexpr std::size_t player_offset = effect_offset + effect_size;
    constexpr std::size_t player_size = 32 + 0x184;
    constexpr std::size_t stage_offset =
        (player_offset + player_size + 7U) & ~std::size_t{7U};
    constexpr std::size_t stage_size = 40 + 48 + 0xDC + 0x64;
    constexpr std::size_t collision_offset = stage_offset + stage_size;
    constexpr std::size_t collision_size = 48 + 96 + 16 + 16 + 40;
    std::array<std::byte, collision_offset + collision_size> bytes{};
    constexpr std::array magic{
        std::byte{'P'}, std::byte{'F'}, std::byte{'S'}, std::byte{'A'},
        std::byte{'P'}, std::byte{'C'}, std::byte{'K'}, std::byte{0}};
    for (std::size_t index = 0; index < magic.size(); ++index) {
        bytes[index] = magic[index];
    }
    write_u32(bytes, 8, pf::ssbm::pack_format_version);
    write_u32(bytes, 12, pf::ssbm::endian_marker);
    write_u32(bytes, 16, static_cast<std::uint32_t>(pf::ssbm::pack_header_size));
    write_u32(bytes, 20, static_cast<std::uint32_t>(pf::ssbm::section_record_size));
    write_u32(bytes, 24, 4);
    write_u64(bytes, 32, bytes.size());
    write_u64(bytes, 40, pf::ssbm::pack_header_size);
    write_u64(bytes, 48, payload_offset);
    write_u32(bytes, 96,
        static_cast<std::uint32_t>(pf::ssbm::SectionKind::effect_data));
    write_u32(bytes, 100, pf::ssbm::effect_particle_schema);
    constexpr std::string_view effect_name{"effect.particle_banks.v2"};
    write_u64(bytes, 104, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(effect_name.data()),
        effect_name.size()}));
    write_u64(bytes, 112, effect_offset);
    write_u64(bytes, 120, effect_size);
    write_u32(bytes, 128, 0);
    write_u32(bytes, 132, 64);

    write_u32(bytes, 176,
        static_cast<std::uint32_t>(pf::ssbm::SectionKind::player_data));
    write_u32(bytes, 180, 1);
    constexpr std::string_view player_name{"player.common_data.v1"};
    write_u64(bytes, 184, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(player_name.data()),
        player_name.size()}));
    write_u64(bytes, 192, player_offset);
    write_u64(bytes, 200, player_size);
    write_u32(bytes, 208, 0x184 / 4);
    write_u32(bytes, 212, 4);

    write_u32(bytes, 256,
        static_cast<std::uint32_t>(pf::ssbm::SectionKind::stage_data));
    write_u32(bytes, 260, 1);
    constexpr std::string_view stage_name{"stage.ground_param.v1"};
    write_u64(bytes, 264, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(stage_name.data()),
        stage_name.size()}));
    write_u64(bytes, 272, stage_offset);
    write_u64(bytes, 280, stage_size);
    write_u32(bytes, 288, 1);
    write_u32(bytes, 292, 48);

    write_u32(bytes, 336,
        static_cast<std::uint32_t>(pf::ssbm::SectionKind::stage_data));
    write_u32(bytes, 340, 1);
    constexpr std::string_view collision_name{"stage.collision.v1"};
    write_u64(bytes, 344, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(collision_name.data()),
        collision_name.size()}));
    write_u64(bytes, 352, collision_offset);
    write_u64(bytes, 360, collision_size);
    write_u32(bytes, 368, 1);
    write_u32(bytes, 372, 96);

    write_u32(bytes, effect_offset, pf::ssbm::effect_particle_schema);
    write_u32(bytes, effect_offset + 16, 64);
    write_u32(bytes, effect_offset + 20, 80);
    write_u32(bytes, effect_offset + 24, 32);
    write_u64(bytes, effect_offset + 32, effect_size);
    write_u64(bytes, effect_offset + 40, effect_size);
    write_u64(bytes, effect_offset + 48, effect_size);
    write_u64(bytes, effect_offset + 56, effect_size);

    write_u32(bytes, player_offset, 1);
    write_u32(bytes, player_offset + 4, 0x184 / 4);
    write_u32(bytes, player_offset + 8, 4);
    write_u32(bytes, player_offset + 12, 32);
    write_u64(bytes, player_offset + 16, 1);
    write_u64(bytes, player_offset + 24, 2);

    write_u32(bytes, stage_offset, 1);
    write_u32(bytes, stage_offset + 4, 1);
    write_u32(bytes, stage_offset + 8, 48);
    write_u32(bytes, stage_offset + 12, 0xDC);
    write_u32(bytes, stage_offset + 16, 0x64);
    write_u64(bytes, stage_offset + 24, 40);
    write_u64(bytes, stage_offset + 32, 88);
    constexpr std::string_view battlefield{"GrNBa.dat"};
    constexpr std::string_view ground_root{"grGroundParam"};
    write_u64(bytes, stage_offset + 40, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(battlefield.data()),
        battlefield.size()}));
    write_u64(bytes, stage_offset + 48, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(ground_root.data()),
        ground_root.size()}));
    write_u64(bytes, stage_offset + 56, 88);
    write_u64(bytes, stage_offset + 64, 88 + 0xDC);
    write_u32(bytes, stage_offset + 72, 1);
    write_u32(bytes, stage_offset + 88 + 0xB4, 1);

    write_u32(bytes, collision_offset, 1);
    write_u32(bytes, collision_offset + 4, 1);
    write_u32(bytes, collision_offset + 8, 96);
    write_u32(bytes, collision_offset + 12, 8);
    write_u32(bytes, collision_offset + 16, 16);
    write_u32(bytes, collision_offset + 20, 40);
    write_u64(bytes, collision_offset + 24, 48);
    write_u64(bytes, collision_offset + 32, 144);
    write_u64(bytes, collision_offset + 48, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(battlefield.data()),
        battlefield.size()}));
    constexpr std::string_view collision_root{"coll_data"};
    write_u64(bytes, collision_offset + 56, pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(collision_root.data()),
        collision_root.size()}));
    write_u64(bytes, collision_offset + 64, 144);
    write_u32(bytes, collision_offset + 72, 2);
    write_u64(bytes, collision_offset + 80, 160);
    write_u32(bytes, collision_offset + 88, 1);
    write_u64(bytes, collision_offset + 96, 176);
    write_u32(bytes, collision_offset + 104, 1);
    write_u32(bytes, collision_offset + 112, 0x00010000);
    write_u32(bytes, collision_offset + 176 + 36, 0x00020000);

    pf::ssbm::AssetPackView assets;
    if (assets.open(bytes) != pf::ssbm::PackStatus::ok) {
        std::fputs("ssbm-runtime=pack-open-fail\n", stderr);
        return false;
    }
    if (!pf::ssbm::bind_native_effect_banks(assets)) {
        std::fputs("ssbm-runtime=effect-bind-fail\n", stderr);
        return false;
    }
    if (!pf::ssbm::bind_native_player_common(assets)) {
        std::fputs("ssbm-runtime=player-bind-fail\n", stderr);
        return false;
    }
    // This historical four-section fixture lacks the required map-head,
    // joint-animation and item sections. The current runtime must reject it
    // before executing gameplay; a complete-pack match is an integration test.
    if (pf::ssbm::bind_native_stage_assets(assets)) {
        std::fputs("ssbm-runtime=incomplete-stage-accepted\n", stderr);
        return false;
    }
    pf::ssbm::MatchState state{};
    pf::ssbm::Runtime runtime;
    PfSsbmNativeMatchConfig config{};
    std::array<pf::ssbm::ControllerSample, pf::ssbm::max_players> input{};
    return runtime.initialize(assets, state, config) ==
               pf::ssbm::RuntimeStatus::invalid_assets &&
        runtime.step(input) == pf::ssbm::RuntimeStatus::invalid_assets &&
        state.frame == 0;

}

} // namespace

int main()
{
    if (!run()) {
        std::fputs("ssbm-runtime=fail\n", stderr);
        return 1;
    }
    std::puts("ssbm-runtime=pass");
    return 0;
}
