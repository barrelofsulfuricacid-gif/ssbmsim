#ifndef PF_SSBM_NATIVE_MATCH_SETUP_H
#define PF_SSBM_NATIVE_MATCH_SETUP_H

#include <stdbool.h>
#include <stdalign.h>
#include <stddef.h>
#include <stdint.h>
#include "native_arithmetic.h"

#ifdef __cplusplus
extern "C" {
#endif

enum {
    PF_SSBM_CONTROLLER_PORT_COUNT = 4,
    PF_SSBM_ENGINE_PLAYER_COUNT = 6,
    PF_SSBM_START_MELEE_DATA_STORAGE_BYTES = 512,
    PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT = 8,
};

typedef struct PfSsbmNativePlayerConfig {
    int8_t character_kind;
    uint8_t present;
    uint8_t costume;
    uint8_t team;
    uint8_t nametag;
    uint8_t rumble_enabled;
    uint8_t cpu_level;
    uint8_t reserved;
} PfSsbmNativePlayerConfig;

typedef struct PfSsbmNativeMatchConfig {
    uint16_t stage_kind;
    uint8_t stock_count;
    uint8_t is_teams;
    uint8_t friendly_fire;
    uint8_t disable_pausing;
    uint8_t ucf_084_enabled;
    uint8_t frozen_stadium;
    uint8_t slippi_online;
    uint8_t slippi_neutral_spawns;
    uint8_t item_spawn_behavior;
    uint8_t arithmetic_profile;
    uint32_t random_seed;
    alignas(8) uint64_t enabled_items;
    uint32_t time_limit_seconds;
    float damage_ratio;
    float game_speed;
    PfSsbmNativePlayerConfig players[PF_SSBM_CONTROLLER_PORT_COUNT];
    uint8_t fd_scene_mode;
} PfSsbmNativeMatchConfig;

/* Gameplay C and runtime C++ use different compiler alignment defaults. */
#ifdef __cplusplus
#define PF_SSBM_MATCH_ABI_ASSERT static_assert
#define PF_SSBM_MATCH_ABI_ALIGN alignof
#else
#define PF_SSBM_MATCH_ABI_ASSERT _Static_assert
#define PF_SSBM_MATCH_ABI_ALIGN _Alignof
#endif
PF_SSBM_MATCH_ABI_ASSERT(sizeof(PfSsbmNativePlayerConfig) == 8,
                         "player configuration ABI size");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativePlayerConfig, cpu_level) == 6,
                         "player configuration CPU-level offset");
PF_SSBM_MATCH_ABI_ASSERT(sizeof(PfSsbmNativeMatchConfig) == 72,
                         "match configuration ABI size");
PF_SSBM_MATCH_ABI_ASSERT(PF_SSBM_MATCH_ABI_ALIGN(PfSsbmNativeMatchConfig) == 8,
                         "match configuration ABI alignment");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, arithmetic_profile) == 11,
                         "match configuration arithmetic offset");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, random_seed) == 12,
                         "match configuration seed offset");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, enabled_items) == 16,
                         "match configuration item-mask offset");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, time_limit_seconds) == 24,
                         "match configuration timer offset");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, players) == 36,
                         "match configuration players offset");
PF_SSBM_MATCH_ABI_ASSERT(offsetof(PfSsbmNativeMatchConfig, fd_scene_mode) == 68,
                         "match configuration FD scene offset");
#undef PF_SSBM_MATCH_ABI_ASSERT
#undef PF_SSBM_MATCH_ABI_ALIGN

/* Fixed-width results also support callers compiled with retail int-sized bool. */
uint8_t pf_ssbm_native_match_config_supported(
    const PfSsbmNativeMatchConfig* config);
uint8_t pf_ssbm_native_build_start_melee_data(
    void* storage,
    size_t storage_bytes,
    const PfSsbmNativeMatchConfig* config);
size_t pf_ssbm_native_start_melee_data_bytes(void);

#ifdef __cplusplus
}
#endif

#endif
