#include "ft/fighter.h"
#include "ft/ft_0D31.h"
#include "ft/types.h"
#include "sysdolphin/baselib/gobj.h"

#include <stdio.h>
#include <string.h>

/* Exercise the imported callbacks, including the Slippi velocity-field overlay. */
int main(void)
{
    static ftCommonData common;
    static Fighter fighter;
    static HSD_GObj gobj;
    int duration = 40;
    int frame;

    p_ftCommonData = &common;
    common.x550 = 1.0f;
    common.x554 = 0.25f;
    common.x558 = 0.5f;
    common.x55C = -1.0f;
    memcpy(&common.x530, &duration, sizeof(duration));
    gobj.user_data = &fighter;
    fighter.cur_pos = (Vec3) { 11.0f, 12.0f, 13.0f };
    fighter.self_vel = (Vec3) { 9.0f, 8.0f, 7.0f };
    fighter.mv.co.unk_deadup.x40 = 1;
    fighter.mv.co.unk_deadup.x44 = 2;

    ftCo_DeadUpFall_Anim(&gobj);
    if (fighter.mv.co.unk_deadup.x44 != 3 ||
        fighter.mv.co.unk_deadup.x40 != duration ||
        fighter.mv.co.walk.slow_anim_frame != 1.0f ||
        fighter.mv.co.unk_deadup.x4C != -1.0f) {
        fputs("screen-ko: velocity phase initialization differs\n", stderr);
        return 1;
    }
    for (frame = 0; frame < 12; ++frame) {
        ftCo_DeadUpFall_Phys(&gobj);
        if (fighter.cur_pos.x != 11.0f || fighter.cur_pos.y != 12.0f ||
            fighter.cur_pos.z != 13.0f || fighter.self_vel.x != 0.0f ||
            fighter.self_vel.y != 0.0f || fighter.self_vel.z != 0.0f ||
            fighter.mv.co.unk_deadup.x5C.x != 0.0f ||
            fighter.mv.co.unk_deadup.x5C.y != 0.0f ||
            fighter.mv.co.unk_deadup.x5C.z != 0.0f) {
            fputs("screen-ko: model motion leaked into gameplay velocity/position\n",
                  stderr);
            return 1;
        }
    }
    if (fighter.mv.co.walk.slow_anim_frame != -0.5f ||
        fighter.mv.co.unk_deadup.x50.z != -12.0f) {
        fputs("screen-ko: terminal fall or model depth differs\n", stderr);
        return 1;
    }
    puts("ssbm-native-screen-ko=pass");
    return 0;
}
