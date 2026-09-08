#include "native_slippi_spawn.h"
#include "baselib/gobj.h"
#include "melee/cm/camera.h"
#include "melee/cm/types.h"
#include "melee/ft/ftcamera.h"
#include "melee/ft/ftparts.h"
#include "melee/ft/types.h"
#include "melee/pl/player.h"

/* The source-owned mapping is declared privately in player.c. */
extern struct _ftMapping {
    s8 internal_id;
    s8 extra_internal_id;
    s8 has_transformation;
} ftMapping_list[];
extern int mpColl_804D64AC;
static uint8_t first_replay_frame;

void pf_ssbm_native_slippi_spawn_begin_frame(uint64_t runtime_frame)
{
    first_replay_frame = runtime_frame == 0;
}

void pf_ssbm_native_slippi_spawn_correct(HSD_GObj* gobj)
{
    Fighter* fp = gobj->user_data;
    /* Slippi fcf47f10dc244152c2ebaa3a9dec142ea42243b7,
     * Playback/Core/RestoreGameFrame.asm at 0x8006B0DC. Runtime frame zero
     * is Slippi -123. Preserve GetIsFollower's mapping-table predicate.
     * Playback resynchronization is disabled: use only simulated state. */
    if (!first_replay_frame ||
        (fp->x221F_b4 &&
         ftMapping_list[Player_GetPlayerCharacter(fp->player_id)]
                 .has_transformation == 0)) {
        return;
    }
    ftPartSetRotX(fp, 0, 0.0F);
    fp->coll_data.cur_pos = fp->cur_pos;
    fp->coll_data.last_pos = fp->cur_pos;
    fp->mv.co.entry.x4 = fp->cur_pos.y;
    fp->coll_data.x38 = mpColl_804D64AC;
    Player_80032828(fp->player_id, fp->x221F_b4, &fp->cur_pos);
    ftCamera_UpdateCameraBox(gobj);
    fp->x890_cameraBox->ext.h = fp->x890_cameraBox->target_ext.h;
    Camera_8002F3AC();
}
