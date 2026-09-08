#ifndef PF_SSBM_NATIVE_SLIPPI_WOBBLE_H
#define PF_SSBM_NATIVE_SLIPPI_WOBBLE_H

/* Slippi fcf47f10 External/PreventWobbling, compiled with the gameplay C ABI. */
#include <melee/ft/fighter.h>
#include <melee/ft/ftcommon.h>
#include <melee/ft/kinds/ftCommon/ftCo_Attack100.h>
#include <melee/ft/types.h>
#include <melee/gm/gm_16AE.h>
#include <melee/it/types.h>
#include <melee/pl/player.h>
#include <sysdolphin/baselib/gobj.h>
#include <stddef.h>

typedef struct PfSlippiWobbleMotionState {
    u8 preceding_motion_fields[0x44];
    u8 count;
    u8 reserved;
    u16 last_move_id;
} PfSlippiWobbleMotionState;

_Static_assert(offsetof(Fighter, mv) + offsetof(PfSlippiWobbleMotionState, count)
                   == 0x2384,
               "Slippi wobble counter motion-field offset");
_Static_assert(offsetof(Fighter, mv) +
                       offsetof(PfSlippiWobbleMotionState, last_move_id) == 0x2386,
               "Slippi wobble move-id motion-field offset");
_Static_assert(sizeof(PfSlippiWobbleMotionState) <= sizeof(((Fighter*) 0)->mv),
               "Slippi wobble overlay fits source motion storage");

static inline PfSlippiWobbleMotionState* pf_slippi_wobble_state(Fighter* fp)
{
    return (PfSlippiWobbleMotionState*) &fp->mv;
}

static inline void pf_slippi_wobble_reset(Fighter* fp)
{
    PfSlippiWobbleMotionState* state = pf_slippi_wobble_state(fp);
    state->count = 0;
    state->last_move_id = 0xFFFF;
}

/* True skips only the two ordinary capture-damage transitions at the hook. */
static inline bool pf_slippi_wobble_check(Fighter* fp)
{
    Fighter_GObj* grabber;
    Fighter_GObj* follower;
    Fighter* grabber_fp;
    Fighter* follower_fp;
    HSD_GObj* source;
    PfSlippiWobbleMotionState* state;
    u16 move_id;
    u16 previous_move_id;

    if (fp->motion_id < ftCo_MS_CapturePulledHi ||
        fp->motion_id > ftCo_MS_CaptureDamageLw) {
        return false;
    }
    grabber = fp->victim_gobj;
    if (grabber == NULL) {
        return false;
    }
    grabber_fp = GET_FIGHTER(grabber);
    if (!grabber_fp->x2222_b5) {
        return false;
    }
    source = fp->dmg.x1868_source;
    if (source == grabber) {
        move_id = grabber_fp->x2074.x2088;
    } else {
        Item* item;
        if (source->classifier != 6) {
            return false;
        }
        item = source->user_data;
        if (item->owner != grabber) {
            return false;
        }
        move_id = item->xDA8_short;
    }
    state = pf_slippi_wobble_state(fp);
    previous_move_id = state->last_move_id;
    if (move_id == previous_move_id) {
        return false;
    }
    state->last_move_id = move_id;
    state->count = (u8) (state->count + 1);
    if (gm_8016B168() || state->count <= 3) {
        return false;
    }

    /* The installed hook retains the previous move ID as this call argument. */
    ftCo_800DA698(grabber, previous_move_id);
    follower = Player_GetEntityAtIndex(grabber_fp->player_id, 1);
    if (follower == NULL) {
        return true;
    }
    follower_fp = GET_FIGHTER(follower);
    if (follower_fp->x221F_b1 || follower_fp->x2219_b5 ||
        follower_fp->x2070.x2071_b0_3 == 13) {
        return true;
    }
    if (follower_fp->ground_or_air == GA_Ground) {
        ftCo_800DA698(follower, false);
    } else {
        ftCommon_8007D5D4(follower_fp);
        follower_fp->self_vel.x =
            p_ftCommonData->x374 * -follower_fp->facing_dir;
        follower_fp->self_vel.y = p_ftCommonData->x378;
        follower_fp->mv.co.capturewait.x0 = 0.0f;
        Fighter_ChangeMotionState(follower, ftCo_MS_CaptureJump, 0,
                                  0.0f, 1.0f, 0.0f, NULL);
    }
    return true;
}

#endif
