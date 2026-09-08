#include "native_slippi_wobble.h"
#include <stdio.h>
#include <string.h>

static Fighter defender, grabber, follower;
static HSD_GObj defender_obj, grabber_obj, follower_obj, item_obj;
static Item item;
static ftCommonData common;
ftCommonData* p_ftCommonData = &common;
static bool teams;
static HSD_GObj* available_follower;
static HSD_GObj* released[2];
static int release_args[2], releases, air_calls, motion_calls;

bool gm_8016B168(void) { return teams; }
void ftCo_800DA698(Fighter_GObj* gobj, bool release_victim)
{
    if (releases < 2) {
        released[releases] = gobj;
        release_args[releases] = release_victim;
    }
    ++releases;
}
HSD_GObj* Player_GetEntityAtIndex(int slot, int index)
{
    return slot == grabber.player_id && index == 1 ? available_follower : NULL;
}
void ftCommon_8007D5D4(Fighter* fp)
{
    if (fp == &follower) { ++air_calls; }
}
void Fighter_ChangeMotionState(Fighter_GObj* gobj, FtMotionId msid,
                              MotionFlags flags, f32 start, f32 speed,
                              f32 blend, Fighter_GObj* other)
{
    if (gobj == &follower_obj && msid == ftCo_MS_CaptureJump && flags == 0 &&
        start == 0.0f && speed == 1.0f && blend == 0.0f && other == NULL) {
        ++motion_calls;
    }
}

static void setup(void)
{
    memset(&defender, 0, sizeof(defender));
    memset(&grabber, 0, sizeof(grabber));
    memset(&follower, 0, sizeof(follower));
    memset(&item, 0, sizeof(item));
    defender_obj.user_data = &defender;
    grabber_obj.user_data = &grabber;
    follower_obj.user_data = &follower;
    item_obj.user_data = &item;
    item_obj.classifier = 6;
    defender.motion_id = ftCo_MS_CaptureDamageHi;
    defender.victim_gobj = &grabber_obj;
    defender.dmg.x1868_source = &grabber_obj;
    grabber.x2222_b5 = true;
    grabber.player_id = 1;
    releases = air_calls = motion_calls = 0;
    teams = false;
    available_follower = NULL;
    pf_slippi_wobble_reset(&defender);
}

#define CHECK(value) do { if (!(value)) { \
    fprintf(stderr, "wobble regression failed at line %d\n", __LINE__); \
    return 1; } } while (0)

int main(void)
{
    PfSlippiWobbleMotionState* state;
    int hit;
    setup();
    memset(&defender.mv, 0xA5, sizeof(defender.mv));
    pf_slippi_wobble_reset(&defender);
    state = pf_slippi_wobble_state(&defender);
    CHECK(state->count == 0 && state->last_move_id == 0xFFFF);
    CHECK(state->reserved == 0xA5 && state->preceding_motion_fields[0] == 0xA5);
    for (hit = 1; hit <= 3; ++hit) {
        grabber.x2074.x2088 = (u16) hit;
        CHECK(!pf_slippi_wobble_check(&defender));
        CHECK(state->count == hit && releases == 0);
    }
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 3);
    grabber.x2074.x2088 = 4;
    CHECK(pf_slippi_wobble_check(&defender));
    CHECK(state->count == 4 && releases == 1 && released[0] == &grabber_obj);
    CHECK(release_args[0] == 3);

    setup(); state->count = 3; state->last_move_id = 7;
    teams = true; grabber.x2074.x2088 = 8;
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 4 && releases == 0);
    setup(); state->count = 3;
    defender.dmg.x1868_source = &item_obj;
    item.owner = &follower_obj; item.xDA8_short = 9;
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 3);
    item.owner = &grabber_obj;
    CHECK(pf_slippi_wobble_check(&defender) && state->last_move_id == 9);

    setup(); state->count = 3; grabber.x2222_b5 = false;
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 3);
    setup(); state->count = 3; defender.motion_id = ftCo_MS_CaptureCut;
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 3);
    setup(); state->count = 255;
    CHECK(!pf_slippi_wobble_check(&defender) && state->count == 0);

    setup(); state->count = 3; available_follower = &follower_obj;
    CHECK(pf_slippi_wobble_check(&defender) && releases == 2);
    CHECK(released[1] == &follower_obj && release_args[1] == 0);
    for (hit = 0; hit < 3; ++hit) {
        setup(); state->count = 3; available_follower = &follower_obj;
        follower.x221F_b1 = hit == 0;
        follower.x2219_b5 = hit == 1;
        follower.x2070.x2071_b0_3 = hit == 2 ? 13 : 0;
        CHECK(pf_slippi_wobble_check(&defender) && releases == 1);
    }
    setup(); state->count = 3; available_follower = &follower_obj;
    follower.ground_or_air = GA_Air; follower.facing_dir = -1.0f;
    common.x374 = 2.0f; common.x378 = 3.0f;
    follower.mv.co.capturewait.x0 = 99.0f;
    CHECK(pf_slippi_wobble_check(&defender));
    CHECK(releases == 1 && air_calls == 1 && motion_calls == 1);
    CHECK(follower.self_vel.x == 2.0f && follower.self_vel.y == 3.0f &&
          follower.mv.co.capturewait.x0 == 0.0f);
    puts("ssbm-native-wobble=pass");
    return 0;
}
