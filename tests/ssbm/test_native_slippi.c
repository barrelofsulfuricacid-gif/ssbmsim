#include "native_slippi.h"

#include "ft/types.h"

#include <stdio.h>

static float camera_left = -100.0F;
static float camera_right = 100.0F;
static float camera_top = 80.0F;
static float camera_bottom = -60.0F;
static bool magnifier_result;
static int magnifier_player = -1;
static int random_values[4];
static int random_value_count;
static int random_value_index;
static int stadium_monitor_call_count;
static bool stadium_monitor_vanilla_result;

static bool stadium_monitor_vanilla(struct HSD_GObj* stage_gobj)
{
    (void) stage_gobj;
    ++stadium_monitor_call_count;
    return stadium_monitor_vanilla_result;
}

int HSD_Randi(int maximum)
{
    int value;
    if (random_value_index >= random_value_count || maximum != 4) {
        return 0;
    }
    value = random_values[random_value_index];
    ++random_value_index;
    return value;
}

float Stage_GetCamBoundsLeftOffset(void)
{
    return camera_left;
}

float Stage_GetCamBoundsRightOffset(void)
{
    return camera_right;
}

float Stage_GetCamBoundsTopOffset(void)
{
    return camera_top;
}

float Stage_GetCamBoundsBottomOffset(void)
{
    return camera_bottom;
}

int ifMagnify_802FC998(int player)
{
    magnifier_player = player;
    return magnifier_result;
}

static int check(bool condition, const char* message)
{
    if (!condition) {
        fprintf(stderr, "native-slippi: %s\n", message);
        return 0;
    }
    return 1;
}

int main(void)
{
    Fighter fp = { 0 };
    float spawn_x;
    float spawn_y;
    float spawn_facing;
    int preloaded_transformation;
    fp.player_id = 2;

    magnifier_result = true;
    pf_ssbm_native_slippi_configure(false, false);
    if (!check(
            pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998) &&
                magnifier_player == 2,
            "offline path did not preserve Melee magnifier semantics")) {
        return 1;
    }

    pf_ssbm_native_slippi_configure(true, false);
    if (!check(
            pf_ssbm_native_slippi_neutral_spawn(
                0x1F, false, 0, &spawn_x, &spawn_y, &spawn_facing) &&
                spawn_x == -38.8F && spawn_y == 35.2F &&
                spawn_facing == 1.0F,
            "Battlefield left neutral spawn did not match Slippi") ||
        !check(
            pf_ssbm_native_slippi_neutral_spawn(
                0x1F, false, 1, &spawn_x, &spawn_y, &spawn_facing) &&
                spawn_x == 38.8F && spawn_y == 35.2F &&
                spawn_facing == -1.0F,
            "Battlefield right neutral spawn did not match Slippi") ||
        !check(
            pf_ssbm_native_slippi_neutral_spawn(
                0x02, true, 1, &spawn_x, &spawn_y, &spawn_facing) &&
                spawn_x == -41.25F && spawn_y == 5.0F &&
                spawn_facing == 1.0F,
            "Fountain teams neutral spawn did not match Slippi") ||
        !check(
            !pf_ssbm_native_slippi_neutral_spawn(
                0x1F, false, 4, &spawn_x, &spawn_y, &spawn_facing),
            "out-of-range neutral spawn was admitted")) {
        return 1;
    }
    magnifier_result = true;
    magnifier_player = -1;
    if (!check(
            pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998) && magnifier_player == 2,
            "neutral spawns incorrectly enabled online offscreen damage")) {
        return 1;
    }

    pf_ssbm_native_slippi_configure(true, true);
    fp.cur_pos.x = 0.0F;
    fp.cur_pos.y = 0.0F;
    if (!check(
            !pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998),
            "inside camera bounds was classified offscreen") ||
        !check(
            (fp.cur_pos.x = camera_left - 1.0F,
             pf_ssbm_native_slippi_brawl_offscreen_damage(
                 &fp, ifMagnify_802FC998)),
            "left camera bound was not enforced") ||
        !check(
            (fp.cur_pos.x = camera_right + 1.0F,
             pf_ssbm_native_slippi_brawl_offscreen_damage(
                 &fp, ifMagnify_802FC998)),
            "right camera bound was not enforced") ||
        !check(
            (fp.cur_pos.x = 0.0F, fp.cur_pos.y = camera_top + 1.0F,
             pf_ssbm_native_slippi_brawl_offscreen_damage(
                 &fp, ifMagnify_802FC998)),
            "top camera bound was not enforced") ||
        !check(
            (fp.cur_pos.y = camera_bottom - 1.0F,
             pf_ssbm_native_slippi_brawl_offscreen_damage(
                 &fp, ifMagnify_802FC998)),
            "bottom camera bound was not enforced")) {
        return 1;
    }

    fp.cur_pos.x = camera_left;
    fp.cur_pos.y = camera_top;
    if (!check(
            !pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998),
            "camera bounds must use strict comparisons")) {
        return 1;
    }

    fp.cur_pos.x = camera_left - 1.0F;
    fp.x221F_b1 = true;
    if (!check(
            !pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998),
            "dead fighter was classified offscreen")) {
        return 1;
    }
    fp.x221F_b1 = false;
    fp.motion_id = 4;
    if (!check(
            !pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998),
            "star-KO state was classified offscreen")) {
        return 1;
    }
    fp.motion_id = 6;
    if (!check(
            !pf_ssbm_native_slippi_brawl_offscreen_damage(
                &fp, ifMagnify_802FC998),
            "screen-KO state was classified offscreen")) {
        return 1;
    }

    random_values[0] = 2;
    random_value_count = 1;
    random_value_index = 0;
    pf_ssbm_native_slippi_stadium_configure(true);
    pf_ssbm_native_slippi_stadium_mark_preloaded();
    if (!check(
            pf_ssbm_native_slippi_stadium_preload(5) == 5 &&
                random_value_index == 0,
            "pre-match Stadium preload latch was not preserved")) {
        return 1;
    }
    pf_ssbm_native_slippi_stadium_reset_preload();
    preloaded_transformation = pf_ssbm_native_slippi_stadium_preload(5);
    if (!check(
            preloaded_transformation == 9 && random_value_index == 1 &&
                pf_ssbm_native_slippi_stadium_is_frozen(),
            "frozen Stadium preload did not preserve Slippi RNG and ID") ||
        !check(
            pf_ssbm_native_slippi_stadium_preload(5) == 9 &&
                random_value_index == 1,
            "Stadium preload repeated after its isLoaded latch")) {
        return 1;
    }

    random_values[0] = 0;
    random_values[1] = 3;
    random_value_count = 2;
    random_value_index = 0;
    pf_ssbm_native_slippi_stadium_configure(false);
    if (!check(
            pf_ssbm_native_slippi_stadium_preload(3) == 6 &&
                random_value_index == 2 &&
                !pf_ssbm_native_slippi_stadium_is_frozen(),
            "Stadium preload did not retry the current transformation")) {
        return 1;
    }

    stadium_monitor_call_count = 0;
    stadium_monitor_vanilla_result = false;
    fp.cur_pos.x = -120.0F;
    fp.cur_pos.y = 80.0F;
    if (!check(
            pf_ssbm_native_slippi_stadium_monitor(
                &fp, NULL, stadium_monitor_vanilla) &&
                stadium_monitor_call_count == 1,
            "Stadium monitor did not preserve the vanilla call before using inclusive Slippi bounds") ||
        !check(
            (fp.cur_pos.x = 120.0F, fp.cur_pos.y = -20.0F,
             pf_ssbm_native_slippi_stadium_monitor(
                 &fp, NULL, stadium_monitor_vanilla)) &&
                stadium_monitor_call_count == 2,
            "Stadium monitor rejected an inclusive Slippi boundary") ||
        !check(
            (fp.cur_pos.x = 120.00001F,
             !pf_ssbm_native_slippi_stadium_monitor(
                 &fp, NULL, stadium_monitor_vanilla)) &&
                stadium_monitor_call_count == 3,
            "Stadium monitor did not reject the right world bound") ||
        !check(
            (fp.cur_pos.x = 0.0F, fp.cur_pos.y = -20.00001F,
             !pf_ssbm_native_slippi_stadium_monitor(
                 &fp, NULL, stadium_monitor_vanilla)) &&
                stadium_monitor_call_count == 4,
            "Stadium monitor did not reject the bottom world bound")) {
        return 1;
    }

    stadium_monitor_vanilla_result = true;
    fp.cur_pos.x = 121.0F;
    fp.cur_pos.y = 0.0F;
    if (!check(
            !pf_ssbm_native_slippi_stadium_monitor(
                &fp, NULL, stadium_monitor_vanilla) &&
                stadium_monitor_call_count == 5,
            "Stadium monitor retained the discarded camera-dependent return")) {
        return 1;
    }

    for (int online = 0; online < 2; ++online) {
        pf_ssbm_native_slippi_configure(0, online);
        for (int motion = 0; motion <= 12; ++motion) {
            if (!check(
                    pf_ssbm_native_slippi_whispy_excludes_fighter(motion) ==
                        (online && motion <= 11),
                    "Whispy death-action or offline boundary mismatch")) {
                return 1;
            }
        }
    }

    puts("native-slippi=pass offline=1 neutral-spawns=4 online-bounds=4 "
         "exclusions=3 stadium-preload=2 frozen=1 stadium-monitor=5");
    return 0;
}
