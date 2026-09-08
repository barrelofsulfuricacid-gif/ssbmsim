#include "native_fighter_state.h"
#include "native_post_frame_api.h"

#include "ft/fighter.h"
#include "pl/player.h"

#include <stdio.h>
#include <string.h>

static int check(int condition, const char* message)
{
    if (!condition) {
        fprintf(stderr, "native-fighter-state: %s\n", message);
        return 0;
    }
    return 1;
}

s32 Player_GetStocks(int slot)
{
    (void) slot;
    return 3;
}

HSD_GObj* Player_GetEntity(s32 slot)
{
    (void) slot;
    return NULL;
}

static Fighter fighter_for_port(unsigned int player_index, int subfighter)
{
    Fighter fighter;
    memset(&fighter, 0, sizeof(fighter));
    fighter.player_id = player_index;
    fighter.x221F_b4 = subfighter != 0;
    fighter.motion_id = 42;
    fighter.cur_pos.x = 12.5F;
    fighter.cur_pos.y = -3.25F;
    fighter.facing_dir = -1.0F;
    fighter.co_attrs.max_jumps = 2;
    fighter.x1968_jumpsUsed = 1;
    return fighter;
}

int main(void)
{
    Fighter leader = fighter_for_port(0, 0);
    Fighter follower = fighter_for_port(0, 1);
    PfSsbmNativeFighterState state;

    pf_ssbm_native_post_frame_begin();
    pf_ssbm_native_post_frame_capture(&leader);
    if (!check(
            pf_ssbm_native_read_fighter_state(0, &state) && state.present &&
                state.action_state_id == 42 && state.position_x == 12.5F &&
                state.stocks_remaining == 3 && state.jumps_remaining == 1,
            "awake leader was not captured")) {
        return 1;
    }

    pf_ssbm_native_post_frame_begin();
    leader.x221F_b3 = true;
    pf_ssbm_native_post_frame_capture(&leader);
    if (!check(
            pf_ssbm_native_read_fighter_state(0, &state) && !state.present,
            "sleeping leader produced a post-frame event")) {
        return 1;
    }

    pf_ssbm_native_post_frame_begin();
    pf_ssbm_native_post_frame_capture(&follower);
    if (!check(
            pf_ssbm_native_read_subfighter_state(0, &state) && state.present &&
                state.action_state_id == 42,
            "awake subfighter was not captured")) {
        return 1;
    }

    pf_ssbm_native_post_frame_begin();
    follower.x221F_b3 = true;
    pf_ssbm_native_post_frame_capture(&follower);
    if (!check(
            pf_ssbm_native_read_subfighter_state(0, &state) && !state.present,
            "sleeping subfighter produced a post-frame event")) {
        return 1;
    }

    puts("ssbm-native-fighter-state=pass awake=2 sleeping-suppressed=2");
    return 0;
}
