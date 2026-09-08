#include "mapped_pack.h"
#include "runtime.h"

extern "C" {
#include "native_compat/native_fail_closed_boundaries.h"
#include "native_compat/native_fighter_state.h"
}

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {

struct Options {
    const char* asset_pack{};
    std::uint32_t seed{};
    std::uint64_t enabled_items{};
    std::uint16_t stage_id{};
    std::uint8_t item_spawn_behavior{};
    std::uint8_t arithmetic_profile{};
    std::uint8_t fd_scene_mode{};
    std::array<std::int8_t, 2> character_ids{};
    std::array<std::uint8_t, 2> costume_ids{};
    std::array<std::uint8_t, 2> cpu_levels{};
    std::array<std::uint8_t, 2> ports{};
    bool frozen_stadium{};
    bool slippi_online{};
    bool slippi_neutral_spawns{};
    bool friendly_fire{};
    bool final_state_only{};
};

[[noreturn]] void unsupported_boundary(const char* name)
{
    std::fprintf(stderr, "ssbm-native-replay=unsupported boundary=%s\n", name);
    if (pf_ssbm_last_unsupported_detail != nullptr) {
        std::fprintf(
            stderr,
            "ssbm-native-replay-detail=%s\n",
            pf_ssbm_last_unsupported_detail);
    }
    std::fflush(stderr);
    std::_Exit(3);
}

bool parse_unsigned(const char* text, unsigned long maximum, unsigned long& value)
{
    char* end{};
    errno = 0;
    value = std::strtoul(text, &end, 0);
    return errno == 0 && end != text && *end == '\0' && value <= maximum;
}

bool parse_u64(const char* text, std::uint64_t& value)
{
    char* end{};
    errno = 0;
    const auto parsed = std::strtoull(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0') {
        return false;
    }
    value = static_cast<std::uint64_t>(parsed);
    return true;
}

bool parse_pair(
    const char* text,
    unsigned long maximum,
    unsigned long& first,
    unsigned long& second)
{
    char* end{};
    errno = 0;
    first = std::strtoul(text, &end, 0);
    if (errno != 0 || end == text || *end != ',' || first > maximum) {
        return false;
    }
    const char* second_text = end + 1;
    errno = 0;
    second = std::strtoul(second_text, &end, 0);
    return errno == 0 && end != second_text && *end == '\0' &&
           second <= maximum;
}

bool parse_options(int argc, char** argv, Options& options)
{
    if (argc < 2) {
        return false;
    }
    options.asset_pack = argv[1];
    bool have_stage = false;
    bool have_seed = false;
    bool have_enabled_items = false;
    bool have_item_spawn_behavior = false;
    bool have_characters = false;
    bool have_costumes = false;
    bool have_ports = false;
    for (int index = 2; index < argc; index += 2) {
        if (index + 1 >= argc) {
            return false;
        }
        unsigned long first{};
        unsigned long second{};
        if (std::strcmp(argv[index], "--stage-id") == 0 &&
            parse_unsigned(argv[index + 1], UINT16_MAX, first)) {
            options.stage_id = static_cast<std::uint16_t>(first);
            have_stage = true;
        } else if (std::strcmp(argv[index], "--seed") == 0 &&
                   parse_unsigned(argv[index + 1], UINT32_MAX, first)) {
            options.seed = static_cast<std::uint32_t>(first);
            have_seed = true;
        } else if (std::strcmp(argv[index], "--enabled-items") == 0 &&
                   parse_u64(argv[index + 1], options.enabled_items)) {
            have_enabled_items = true;
        } else if (std::strcmp(argv[index], "--item-spawn-behavior") == 0 &&
                   parse_unsigned(argv[index + 1], UINT8_MAX, first)) {
            options.item_spawn_behavior = static_cast<std::uint8_t>(first);
            have_item_spawn_behavior = true;
        } else if (std::strcmp(argv[index], "--character-ids") == 0 &&
                   parse_pair(argv[index + 1], INT8_MAX, first, second)) {
            options.character_ids = {
                static_cast<std::int8_t>(first),
                static_cast<std::int8_t>(second),
            };
            have_characters = true;
        } else if (std::strcmp(argv[index], "--costume-ids") == 0 &&
                   parse_pair(argv[index + 1], UINT8_MAX, first, second)) {
            options.costume_ids = {
                static_cast<std::uint8_t>(first),
                static_cast<std::uint8_t>(second),
            };
            have_costumes = true;
        } else if (std::strcmp(argv[index], "--cpu-levels") == 0 &&
                   parse_pair(argv[index + 1], 9, first, second)) {
            options.cpu_levels = {
                static_cast<std::uint8_t>(first),
                static_cast<std::uint8_t>(second),
            };
        } else if (std::strcmp(argv[index], "--ports") == 0 &&
                   parse_pair(argv[index + 1], 3, first, second) &&
                   first != second) {
            options.ports = {
                static_cast<std::uint8_t>(first),
                static_cast<std::uint8_t>(second),
            };
            have_ports = true;
        } else if (std::strcmp(argv[index], "--frozen-stadium") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.frozen_stadium = first != 0;
        } else if (std::strcmp(argv[index], "--slippi-online") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.slippi_online = first != 0;
        } else if (std::strcmp(argv[index], "--neutral-spawns") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.slippi_neutral_spawns = first != 0;
        } else if (std::strcmp(argv[index], "--friendly-fire") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.friendly_fire = first != 0;
        } else if (std::strcmp(argv[index], "--fd-scene-mode") == 0 &&
                   parse_unsigned(argv[index + 1], 2, first)) {
            options.fd_scene_mode = static_cast<std::uint8_t>(first);
        } else if (std::strcmp(argv[index], "--arithmetic-profile") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.arithmetic_profile = static_cast<std::uint8_t>(first);
        } else if (std::strcmp(argv[index], "--final-state-only") == 0 &&
                   parse_unsigned(argv[index + 1], 1, first)) {
            options.final_state_only = first != 0;
        } else {
            return false;
        }
    }
    return have_stage && have_seed && have_enabled_items &&
        have_item_spawn_behavior && have_characters && have_costumes &&
        have_ports;
}

PfSsbmNativeMatchConfig make_config(const Options& options)
{
    PfSsbmNativeMatchConfig config{};
    config.stage_kind = options.stage_id;
    config.stock_count = 4;
    config.disable_pausing = 1;
    config.friendly_fire = options.friendly_fire;
    config.ucf_084_enabled = 1;
    config.frozen_stadium = options.frozen_stadium;
    config.slippi_online = options.slippi_online;
    config.slippi_neutral_spawns = options.slippi_neutral_spawns;
    config.random_seed = options.seed;
    config.item_spawn_behavior = options.item_spawn_behavior;
    config.arithmetic_profile = options.arithmetic_profile;
    config.fd_scene_mode = options.fd_scene_mode;
    config.enabled_items = options.enabled_items;
    config.time_limit_seconds = 8 * 60;
    config.damage_ratio = 1.0F;
    config.game_speed = 1.0F;
    for (std::size_t index = 0; index < 2; ++index) {
        const auto port = options.ports[index];
        config.players[port].present = 1;
        config.players[port].character_kind = options.character_ids[index];
        config.players[port].costume = options.costume_ids[index];
        config.players[port].cpu_level = options.cpu_levels[index];
    }
    return config;
}

bool parse_integer(
    char*& cursor,
    long long minimum,
    long long maximum,
    long long& value)
{
    char* end{};
    errno = 0;
    value = std::strtoll(cursor, &end, 10);
    if (errno != 0 || end == cursor || value < minimum || value > maximum) {
        return false;
    }
    if (*end == ',') {
        cursor = end + 1;
    } else if (*end == '\n' || *end == '\r' || *end == '\0') {
        cursor = end;
    } else {
        return false;
    }
    return true;
}

bool parse_float(char*& cursor, float& value)
{
    char* end{};
    errno = 0;
    value = std::strtof(cursor, &end);
    if (errno != 0 || end == cursor) {
        return false;
    }
    if (*end == ',') {
        cursor = end + 1;
    } else if (*end == '\n' || *end == '\r' || *end == '\0') {
        cursor = end;
    } else {
        return false;
    }
    return true;
}

bool parse_player(char*& cursor, pf::ssbm::ControllerSample& sample)
{
    long long integer{};
    if (!parse_integer(cursor, 0, UINT32_MAX, integer)) {
        return false;
    }
    sample.buttons = static_cast<std::uint32_t>(integer);
    if (!parse_float(cursor, sample.main_x) ||
        !parse_float(cursor, sample.main_y) ||
        !parse_float(cursor, sample.c_x) ||
        !parse_float(cursor, sample.c_y) ||
        !parse_float(cursor, sample.left_trigger) ||
        !parse_float(cursor, sample.right_trigger)) {
        return false;
    }
    std::int8_t* raw[] = {
        &sample.raw_main_x,
        &sample.raw_main_y,
        &sample.raw_c_x,
        &sample.raw_c_y,
    };
    for (std::int8_t* axis : raw) {
        if (!parse_integer(cursor, INT8_MIN, INT8_MAX, integer)) {
            return false;
        }
        *axis = static_cast<std::int8_t>(integer);
    }
    return true;
}

void print_fighter(const PfSsbmNativeFighterState& fighter)
{
    std::printf(
        ",%u,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%u,%d,%u,%u",
        fighter.present ? 1U : 0U,
        fighter.action_state_id,
        fighter.position_x,
        fighter.position_y,
        fighter.facing_direction,
        fighter.damage_percent,
        fighter.shield_health,
        fighter.self_velocity_x,
        fighter.self_velocity_y,
        fighter.attack_velocity_x,
        fighter.attack_velocity_y,
        fighter.hitlag_remaining,
        fighter.animation_frame,
        fighter.ground_id,
        fighter.stocks_remaining,
        fighter.jumps_remaining,
        fighter.is_airborne);
}

} // namespace

int main(int argc, char** argv)
{
    if (std::setvbuf(stdout, nullptr, _IOLBF, 0) != 0) {
        std::fputs("ssbm-native-replay=stdout-buffer-fail\n", stderr);
        return 1;
    }
    Options options{};
    if (!parse_options(argc, argv, options)) {
        std::fputs(
            "usage: ssbm_native_replay_runner ASSET_PACK --stage-id N "
            "--seed N --enabled-items N --item-spawn-behavior N "
            "--character-ids N,N --costume-ids N,N "
            "--ports N,N "
            "[--frozen-stadium 0|1] [--slippi-online 0|1] "
            "[--neutral-spawns 0|1] [--friendly-fire 0|1] [--arithmetic-profile 0|1]\n",
            stderr);
        return 2;
    }

    pf::ssbm::MappedPack pack;
    if (pack.open(options.asset_pack) != pf::ssbm::PackStatus::ok) {
        std::fputs("ssbm-native-replay=asset-fail\n", stderr);
        return 1;
    }
    pf::ssbm::MatchState state{};
    pf::ssbm::Runtime runtime;
    pf_ssbm_set_unsupported_boundary_handler(unsupported_boundary);
    if (runtime.initialize(pack.view(), state, make_config(options)) !=
        pf::ssbm::RuntimeStatus::ok) {
        std::fputs("ssbm-native-replay=setup-fail\n", stderr);
        return 1;
    }

    std::puts(
        "source_frame,rng,post_rng,executed_frames,p0_present,p0_action,p0_x,p0_y,p0_facing,"
        "p0_damage,p0_shield,p0_self_vx,p0_self_vy,p0_attack_vx,"
        "p0_attack_vy,p0_hitlag,p0_anim_frame,"
        "p0_ground_id,p0_stocks,p0_jumps,p0_airborne,p1_present,p1_action,"
        "p1_x,p1_y,p1_facing,p1_damage,p1_shield,p1_self_vx,p1_self_vy,"
        "p1_attack_vx,p1_attack_vy,p1_hitlag,p1_anim_frame,p1_ground_id,"
        "p1_stocks,p1_jumps,p1_airborne,"
        "p0f_present,p0f_action,p0f_x,p0f_y,p0f_facing,p0f_damage,"
        "p0f_shield,p0f_self_vx,p0f_self_vy,p0f_attack_vx,p0f_attack_vy,"
        "p0f_hitlag,p0f_anim_frame,p0f_ground_id,p0f_stocks,p0f_jumps,"
        "p0f_airborne,p1f_present,p1f_action,p1f_x,p1f_y,p1f_facing,"
        "p1f_damage,p1f_shield,p1f_self_vx,p1f_self_vy,p1f_attack_vx,"
        "p1f_attack_vy,p1f_hitlag,p1f_anim_frame,p1f_ground_id,p1f_stocks,"
        "p1f_jumps,p1f_airborne");
    const auto emit_state = [&](long long frame, std::uint64_t rows) {
        PfSsbmNativeFighterState fighters[2]{};
        PfSsbmNativeFighterState subfighters[2]{};
        if (!pf_ssbm_native_read_fighter_state(
                options.ports[0], &fighters[0]) ||
            !pf_ssbm_native_read_fighter_state(
                options.ports[1], &fighters[1]) ||
            !pf_ssbm_native_read_subfighter_state(
                options.ports[0], &subfighters[0]) ||
            !pf_ssbm_native_read_subfighter_state(
                options.ports[1], &subfighters[1])) {
            std::fputs("ssbm-native-replay=state-fail\n", stderr);
            return false;
        }
        std::printf("%lld,%u,%u,%llu", frame, state.frame_start_rng, state.hsd_rng,
                    static_cast<unsigned long long>(rows));
        print_fighter(fighters[0]);
        print_fighter(fighters[1]);
        print_fighter(subfighters[0]);
        print_fighter(subfighters[1]);
        std::putchar('\n');
        return true;
    };
    long long last_frame{};
    char line[4096];
    std::uint64_t rows = 0;
    while (std::fgets(line, sizeof(line), stdin) != nullptr) {
        if (std::strchr(line, '\n') == nullptr && !std::feof(stdin)) {
            std::fputs("ssbm-native-replay=input-line-too-long\n", stderr);
            return 2;
        }
        char* cursor = line;
        long long frame{};
        long long seed{};
        if (!parse_integer(cursor, INT32_MIN, INT32_MAX, frame) ||
            !parse_integer(cursor, 0, UINT32_MAX, seed)) {
            std::fputs("ssbm-native-replay=malformed-frame-prefix\n", stderr);
            return 2;
        }
        std::array<pf::ssbm::ControllerSample, pf::ssbm::max_players> input{};
        if (!parse_player(cursor, input[options.ports[0]]) ||
            !parse_player(cursor, input[options.ports[1]]) ||
            (*cursor != '\n' && *cursor != '\r' && *cursor != '\0')) {
            std::fputs("ssbm-native-replay=malformed-player-input\n", stderr);
            return 2;
        }
        // The FrameStart seed is oracle state to compare, never an input to
        // the native simulation. Reseeding here would mask RNG divergence.
        (void) seed;
        if (runtime.step(input) !=
            pf::ssbm::RuntimeStatus::ok) {
            std::fputs("ssbm-native-replay=step-fail\n", stderr);
            return 1;
        }
        ++rows;
        last_frame = frame;
        if (!options.final_state_only && !emit_state(frame, rows)) {
            return 1;
        }
    }
    if (std::ferror(stdin)) {
        std::fputs("ssbm-native-replay=input-read-fail\n", stderr);
        return 1;
    }
    if (options.final_state_only && rows != 0 && !emit_state(last_frame, rows)) {
        return 1;
    }
    std::fprintf(stderr, "ssbm-native-replay=complete frames=%llu\n",
                 static_cast<unsigned long long>(rows));
    return rows == 0 ? 1 : 0;
}
