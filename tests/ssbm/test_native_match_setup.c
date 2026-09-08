#include "native_match_setup.h"

#include "ft/forward.h"
#include "gr/forward.h"
#include "mn/types.h"
#include "pl/forward.h"

#include <stdio.h>

alignas(PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT)
    static unsigned char storage[PF_SSBM_START_MELEE_DATA_STORAGE_BYTES];

static int check(int condition, const char* message)
{
    if (!condition) {
        fprintf(stderr, "native-match-setup: %s\n", message);
        return 0;
    }
    return 1;
}

static PfSsbmNativeMatchConfig falcon_battlefield(void)
{
    PfSsbmNativeMatchConfig config = { 0 };
    config.stage_kind = St_Kind_Battle;
    config.stock_count = 4;
    config.disable_pausing = 1;
    config.ucf_084_enabled = 1;
    config.item_spawn_behavior = 255;
    config.time_limit_seconds = 8 * 60;
    config.damage_ratio = 1.0F;
    config.game_speed = 1.0F;
    config.players[0].present = 1;
    config.players[0].character_kind = 0;
    config.players[0].costume = 1;
    config.players[0].nametag = 0x78;
    config.players[0].cpu_level = 1;
    config.players[1].present = 1;
    config.players[1].character_kind = 0;
    config.players[1].costume = 3;
    config.players[1].nametag = 0x78;
    config.players[1].cpu_level = 9;
    return config;
}

int main(void)
{
    PfSsbmNativeMatchConfig config = falcon_battlefield();
    StartMeleeData* data = (StartMeleeData*) storage;
    unsigned int index;

    for (index = 1; index < PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT; ++index) {
        if (!check(
                !pf_ssbm_native_build_start_melee_data(
                    storage + index, sizeof(storage) - index, &config),
                "misaligned opaque match storage was accepted")) {
            return 1;
        }
    }

    if (!check(
            pf_ssbm_native_start_melee_data_bytes() == sizeof(*data),
            "opaque storage size differs from source type") ||
        !check(
            pf_ssbm_native_build_start_melee_data(
                storage, sizeof(storage), &config),
            "legal UCF match was rejected") ||
        !check(data->rules.match_kind == MatchKind_Stock, "not stock mode") ||
        !check(data->rules.stkind == St_Kind_Battle, "stage was not copied") ||
        !check(data->rules.time_limit == 480, "timer was not copied") ||
        !check(data->rules.xB == -1 && data->rules.x20 == 0,
               "items-off contract was not encoded") ||
        !check(data->rules.x30 == 1.0F && data->rules.game_speed == 1.0F,
               "source ratios were not encoded") ||
        !check(data->players[0].slot_type == Gm_PKind_Human &&
                   data->players[1].slot_type == Gm_PKind_Human,
               "active ports were not human") ||
        !check(data->players[0].stocks == 4 && data->players[1].stocks == 4,
               "stocks were not copied") ||
        !check(data->players[0].color == 1 && data->players[1].color == 3,
               "costumes were not copied") ||
        !check(data->players[0].cpu_level == 1 && data->players[1].cpu_level == 9,
               "recorded CPU levels were not retained for human slots") ||
        !check(data->players[0].handicap == 9 &&
                   data->players[0].attack_ratio == 1.0F &&
                   data->players[0].defense_ratio == 1.0F,
               "source player defaults were not preserved")) {
        return 1;
    }
    for (index = 2; index < PF_SSBM_ENGINE_PLAYER_COUNT; ++index) {
        if (!check(
                data->players[index].slot_type == Gm_PKind_NA,
                "inactive engine slot was enabled")) {
            return 1;
        }
    }

    config.players[1].cpu_level = 10;
    if (!check(!pf_ssbm_native_match_config_supported(&config),
               "invalid CPU level was admitted")) return 1;
    config.players[1].cpu_level = 9;
    config.arithmetic_profile = PF_SSBM_ARITHMETIC_SEPARATE;
    if (!check(pf_ssbm_native_match_config_supported(&config),
               "separate arithmetic profile was rejected")) {
        return 1;
    }
    config.arithmetic_profile = 2;
    if (!check(!pf_ssbm_native_match_config_supported(&config),
               "invalid arithmetic profile was admitted")) {
        return 1;
    }
    config.arithmetic_profile = PF_SSBM_ARITHMETIC_FUSED;
    config.stage_kind = St_Kind_Corneria;
    if (!check(
            !pf_ssbm_native_match_config_supported(&config),
            "non-legal stage was admitted")) {
        return 1;
    }
    config.stage_kind = St_Kind_PStadium;
    if (!check(
            !pf_ssbm_native_match_config_supported(&config),
            "transforming Stadium was admitted")) {
        return 1;
    }
    config.frozen_stadium = 1;
    if (!check(
            pf_ssbm_native_match_config_supported(&config),
            "frozen Stadium was rejected")) {
        return 1;
    }
    config.ucf_084_enabled = 0;
    if (!check(
            !pf_ssbm_native_match_config_supported(&config),
            "non-UCF match was admitted")) {
        return 1;
    }
    config.ucf_084_enabled = 1;
    for (index = 0; index < CKIND_PLAYABLE_COUNT; ++index) {
        config.players[0].character_kind = (int8_t) index;
        if (!check(pf_ssbm_native_match_config_supported(&config),
                   "playable character was rejected")) {
            return 1;
        }
    }
    config.players[0].character_kind = CKIND_MASTERH;
    if (!check(
            !pf_ssbm_native_match_config_supported(&config),
            "non-playable character was admitted")) {
        return 1;
    }
    config.players[0].character_kind = -1;
    if (!check(!pf_ssbm_native_match_config_supported(&config),
               "negative character ID was admitted")) {
        return 1;
    }

    puts("ssbm-native-match-setup=pass");
    return 0;
}
