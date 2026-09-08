#include "native_fighter_state.h"

#include <melee/ft/fighter.h>
#include <melee/pl/player.h>

#include <string.h>

static PfSsbmNativeFighterState post_frame_states[4];
static bool post_frame_state_valid[4];
static PfSsbmNativeFighterState post_frame_subfighter_states[4];
static bool post_frame_subfighter_state_valid[4];

static void read_fighter(
    Fighter* fighter,
    uint32_t player_index,
    PfSsbmNativeFighterState* state)
{
    int max_jumps;
    int jumps_remaining;

    memset(state, 0, sizeof(*state));
    state->present = true;
    state->action_state_id = fighter->motion_id;
    state->position_x = fighter->cur_pos.x;
    state->position_y = fighter->cur_pos.y;
    state->facing_direction = fighter->facing_dir;
    state->damage_percent = fighter->dmg.x1830_percent;
    state->shield_health = fighter->shield_health;
    state->self_velocity_x = fighter->ground_or_air == GA_Ground
                                 ? fighter->gr_vel
                                 : fighter->self_vel.x;
    state->self_velocity_y = fighter->self_vel.y;
    state->attack_velocity_x = fighter->x8c_kb_vel.x;
    state->attack_velocity_y = fighter->x8c_kb_vel.y;
    state->hitlag_remaining = fighter->dmg.x195c_hitlag_frames;
    state->animation_frame = fighter->cur_anim_frame;
    state->ground_id = (uint16_t) fighter->coll_data.floor.index;
    state->stocks_remaining = Player_GetStocks((int) player_index);
    state->is_airborne = fighter->ground_or_air == GA_Air;
    max_jumps = fighter->co_attrs.max_jumps;
    jumps_remaining = max_jumps - fighter->x1968_jumpsUsed;
    if (jumps_remaining < 0) {
        jumps_remaining = 0;
    } else if (jumps_remaining > UINT8_MAX) {
        jumps_remaining = UINT8_MAX;
    }
    state->jumps_remaining = (uint8_t) jumps_remaining;
}

void pf_ssbm_native_post_frame_begin(void)
{
    memset(post_frame_state_valid, 0, sizeof(post_frame_state_valid));
    memset(post_frame_subfighter_state_valid, 0,
           sizeof(post_frame_subfighter_state_valid));
}

void pf_ssbm_native_post_frame_capture(void* fighter_data)
{
    Fighter* fighter = fighter_data;
    uint32_t player_index;

    /* Slippi's GALE01 post-frame injection at 0x8006DA34 tests byte 0x221F,
     * mask 0x10, and emits no event while this fighter is asleep. Keep trace
     * presence aligned with that canonical event boundary; a dormant Fighter
     * object is not a reported post-frame fighter. */
    if (fighter == NULL || fighter->x221F_b3) {
        return;
    }
    player_index = fighter->player_id;
    if (player_index >= 4) {
        return;
    }
    if (fighter->x221F_b4) {
        read_fighter(fighter, player_index,
                     &post_frame_subfighter_states[player_index]);
        post_frame_subfighter_state_valid[player_index] = true;
    } else {
        read_fighter(fighter, player_index, &post_frame_states[player_index]);
        post_frame_state_valid[player_index] = true;
    }
}

uint8_t pf_ssbm_native_read_fighter_state(
    uint32_t player_index,
    PfSsbmNativeFighterState* state)
{
    HSD_GObj* fighter_gobj;
    Fighter* fighter;
    if (state == NULL || player_index >= 4) {
        return false;
    }
    if (post_frame_state_valid[player_index]) {
        *state = post_frame_states[player_index];
        return true;
    }
    memset(state, 0, sizeof(*state));
    fighter_gobj = Player_GetEntity((int) player_index);
    if (fighter_gobj == NULL || fighter_gobj->user_data == NULL) {
        return true;
    }

    fighter = GET_FIGHTER(fighter_gobj);
    read_fighter(fighter, player_index, state);
    return true;
}

uint8_t pf_ssbm_native_read_subfighter_state(
    uint32_t player_index,
    PfSsbmNativeFighterState* state)
{
    if (state == NULL || player_index >= 4) {
        return false;
    }
    if (post_frame_subfighter_state_valid[player_index]) {
        *state = post_frame_subfighter_states[player_index];
        return true;
    }
    memset(state, 0, sizeof(*state));
    return true;
}
