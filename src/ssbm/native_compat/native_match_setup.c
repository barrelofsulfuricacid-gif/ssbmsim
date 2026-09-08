#include "native_match_setup.h"

#include "ft/forward.h"
#include "gm/gm_1601.h"
#include "gr/forward.h"
#include "mn/types.h"
#include "pl/forward.h"

static bool is_legal_stage(uint16_t stage_kind)
{
    switch ((StKind) stage_kind) {
    case St_Kind_Izumi:
    case St_Kind_PStadium:
    case St_Kind_Story:
    case St_Kind_OldPupupu:
    case St_Kind_Battle:
    case St_Kind_Last:
        return true;
    default:
        return false;
    }
}

static bool is_acceptance_character(int8_t character_kind)
{
    return character_kind >= CKIND_CAPTAIN &&
           character_kind < CKIND_PLAYABLE_COUNT;
}

uint8_t pf_ssbm_native_match_config_supported(
    const PfSsbmNativeMatchConfig* config)
{
    unsigned int active_players = 0;
    unsigned int index;

    if (config == NULL || !config->ucf_084_enabled ||
        config->arithmetic_profile > PF_SSBM_ARITHMETIC_SEPARATE ||
        config->fd_scene_mode > 2 ||
        !is_legal_stage(config->stage_kind) || config->stock_count == 0 ||
        config->game_speed != 1.0F || config->damage_ratio <= 0.0F ||
        (config->stage_kind == St_Kind_PStadium) !=
            (config->frozen_stadium != 0)) {
        return false;
    }
    for (index = 0; index < PF_SSBM_CONTROLLER_PORT_COUNT; ++index) {
        if (config->players[index].present) {
            if (config->players[index].cpu_level > 9) return false;
            ++active_players;
            if (!is_acceptance_character(
                    config->players[index].character_kind)) {
                return false;
            }
        }
    }
    return active_players >= 2;
}

uint8_t pf_ssbm_native_build_start_melee_data(
    void* storage,
    size_t storage_bytes,
    const PfSsbmNativeMatchConfig* config)
{
    StartMeleeData* data;
    unsigned int index;

    if (storage == NULL || storage_bytes < sizeof(StartMeleeData) ||
        (uintptr_t) storage % PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT != 0 ||
        !pf_ssbm_native_match_config_supported(config)) {
        return false;
    }

    data = storage;
    gm_SetupRulesDefaults(&data->rules);
    gm_SetupAllPlayerDefaults(data->players);

    data->rules.match_kind = MatchKind_Stock;
    data->rules.timer_enabled = config->time_limit_seconds != 0;
    data->rules.time_limit = config->time_limit_seconds;
    data->rules.is_teams = config->is_teams != 0;
    data->rules.friendly_fire = config->friendly_fire != 0;
    data->rules.disable_pausing = config->disable_pausing != 0;
    data->rules.stkind = config->stage_kind;
    data->rules.xB = (int8_t) config->item_spawn_behavior;
    data->rules.x20 = config->enabled_items;
    data->rules.x30 = config->damage_ratio;
    data->rules.game_speed = config->game_speed;

    for (index = 0; index < PF_SSBM_CONTROLLER_PORT_COUNT; ++index) {
        const PfSsbmNativePlayerConfig* player = &config->players[index];
        if (!player->present) {
            continue;
        }
        data->players[index].ckind = player->character_kind;
        data->players[index].slot_type = Gm_PKind_Human;
        data->players[index].stocks = config->stock_count;
        data->players[index].color = player->costume;
        data->players[index].slot = 0;
        data->players[index].sub_color = index;
        data->players[index].team = player->team;
        data->players[index].nametag = player->nametag;
        data->players[index].rumble_enabled = player->rumble_enabled != 0;
        /* Human slots retain this field too: Nana consumes the owner's
         * recorded level through the ordinary fighter initialization path. */
        data->players[index].cpu_level = player->cpu_level;
    }
    return true;
}

size_t pf_ssbm_native_start_melee_data_bytes(void)
{
    return sizeof(StartMeleeData);
}

_Static_assert(
    sizeof(StartMeleeData) <= PF_SSBM_START_MELEE_DATA_STORAGE_BYTES,
    "native StartMeleeData storage is too small");
_Static_assert(
    alignof(StartMeleeData) == PF_SSBM_START_MELEE_DATA_STORAGE_ALIGNMENT,
    "native StartMeleeData storage alignment differs from GALE01");
