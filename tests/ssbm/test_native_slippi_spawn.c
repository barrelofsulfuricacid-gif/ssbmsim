#include "native_slippi_spawn.h"
#include "baselib/gobj.h"
#include "melee/cm/types.h"
#include "melee/ft/types.h"
#include "melee/pl/player.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <stdlib.h>
#define assert(condition) do { if (!(condition)) { fprintf(stderr, "check failed at %d: %s\n", __LINE__, #condition); abort(); } } while (0)
#include <stdio.h>
#include <string.h>

struct _ftMapping { s8 internal_id, extra_internal_id, has_transformation; }
    ftMapping_list[2];
int mpColl_804D64AC = 17;
static Fighter fighter;
static HSD_GObj object;
static CmSubject camera;
static int calls;
static CharacterKind character;

CharacterKind Player_GetPlayerCharacter(int slot)
{
    assert(slot == 0);
    return character;
}
void ftPartSetRotX(Fighter* fp, int part, float angle)
{
    assert(fp == &fighter && part == 0 && angle == 0 && calls++ == 0);
}
void Player_80032828(int slot, bool subfighter, Vec3* pos)
{
    assert(slot == 0 && subfighter == fighter.x221F_b4);
    assert(pos == &fighter.cur_pos && calls++ == 1);
    assert(fighter.coll_data.cur_pos.x == 2);
    assert(fighter.coll_data.last_pos.y == 3);
    assert(fighter.coll_data.last_pos.z == 4);
    assert(fighter.coll_data.prev_pos.y == 99);
    assert(fighter.mv.co.entry.x4 == 3);
    assert(fighter.coll_data.x38 == 17);
}
void ftCamera_UpdateCameraBox(HSD_GObj* gobj)
{
    assert(gobj == &object && calls++ == 2);
    camera.target_ext.h.x = -12;
    camera.target_ext.h.y = 13;
}
void Camera_8002F3AC(void)
{
    assert(calls++ == 3);
    assert(camera.ext.h.x == -12 && camera.ext.h.y == 13);
}
static void reset(void)
{
    memset(&fighter, 0, sizeof(fighter));
    memset(&camera, 0, sizeof(camera));
    fighter.cur_pos = (Vec3) {2, 3, 4};
    fighter.coll_data.prev_pos.y = 99;
    fighter.x890_cameraBox = &camera;
    object.user_data = &fighter;
    calls = 0;
}
int main(void)
{
    reset();
    pf_ssbm_native_slippi_spawn_begin_frame(0);
    pf_ssbm_native_slippi_spawn_correct(&object);
    assert(calls == 4);
    reset();
    pf_ssbm_native_slippi_spawn_begin_frame(1);
    pf_ssbm_native_slippi_spawn_correct(&object);
    assert(calls == 0 && fighter.coll_data.cur_pos.y == 0);
    /* A new match must re-enable correction after any previous frame. */
    pf_ssbm_native_slippi_spawn_begin_frame(0);
    fighter.x221F_b4 = 1;
    pf_ssbm_native_slippi_spawn_correct(&object);
    assert(calls == 0 && fighter.coll_data.cur_pos.y == 0);
    character = 1;
    ftMapping_list[1].has_transformation = 1;
    pf_ssbm_native_slippi_spawn_correct(&object);
    assert(calls == 4);
    puts("native-slippi-spawn=pass order=4 follower=1 transformation=1 restart=1");
    return 0;
}
