#include "native_competitive_presentation.h"

#include "baselib/gobj.h"
#include "baselib/gobjplink.h"
#include "baselib/gobjproc.h"
#include "baselib/random.h"
#include "ef/efsync.h"
#include "if/ifstatus.h"
#include "if/types.h"
#include "pl/player.h"

#include <string.h>

typedef struct PfHeadlessDamageHudState {
    int damage_percent;
    int old_damage;
    int damage_from_last_attack;
    unsigned char frames_of_shake_remaining;
    unsigned char force_digit_shake;
    unsigned char player_slot;
    int stocks;
} PfHeadlessDamageHudState;

static PfHeadlessDamageHudState pf_headless_damage_hud[6];

static void pf_ifStock_headless_update(HSD_GObj* gobj,
                                       PfHeadlessDamageHudState* state)
{
    const int stocks =
        Player_GetStocks((signed char) state->player_slot);

    while (state->stocks > stocks) {
        Vec3 position = { 0.0F, 0.0F, 0.0F };

        /*
         * ifStock_802F8298 emits synchronous effect 0x474 once for each
         * disappearing stock icon. Its position is presentation-only; the
         * resulting source generator 0xF7 and particle interpreter advance
         * the gameplay-global RNG on subsequent frames.
         */
        (void) efSync_Spawn(0x474, gobj, &position);
        state->stocks -= 1;
    }
    state->stocks = stocks;
}

typedef struct PfHeadlessGoBannerState {
    void (*completion_callback)(void);
    unsigned int frames_remaining;
    int schedule_failed;
} PfHeadlessGoBannerState;

static PfHeadlessGoBannerState pf_headless_go_banner;

static void pf_ifStatus_headless_update_go_banner(HSD_GObj* gobj)
{
    PfHeadlessGoBannerState* state = gobj->user_data;
    void (*completion_callback)(void);

    if (state->frames_remaining > 0) {
        state->frames_remaining -= 1;
    }
    if (state->frames_remaining != 0) {
        return;
    }
    completion_callback = state->completion_callback;
    state->completion_callback = NULL;
    completion_callback();
    HSD_GObjPLink_80390228(gobj);
}

int pf_ifStatus_headless_schedule_go_completion(void (*callback)(void))
{
    HSD_GObj* gobj;

    pf_headless_go_banner.schedule_failed = 0;
    if (callback == NULL ||
        pf_headless_go_banner.completion_callback != NULL) {
        pf_headless_go_banner.schedule_failed = 1;
        return 0;
    }
    gobj = GObj_Create(0xE, 0xE, 0);
    if (gobj == NULL) {
        pf_headless_go_banner.schedule_failed = 1;
        return 0;
    }
    pf_headless_go_banner.completion_callback = callback;
    pf_headless_go_banner.frames_remaining = 40;
    gobj->user_data = &pf_headless_go_banner;
    if (HSD_GObj_SetupProc(gobj, pf_ifStatus_headless_update_go_banner, 0) ==
        NULL) {
        pf_headless_go_banner.completion_callback = NULL;
        pf_headless_go_banner.frames_remaining = 0;
        pf_headless_go_banner.schedule_failed = 1;
        HSD_GObjPLink_80390228(gobj);
        return 0;
    }
    return 1;
}

int pf_ifStatus_headless_go_completion_failed(void)
{
    return pf_headless_go_banner.schedule_failed;
}

static void pf_ifStatus_headless_update_damage(HSD_GObj* gobj)
{
    PfHeadlessDamageHudState* state = gobj->user_data;
    int diff;

    if (Player_GetEntity((signed char) state->player_slot) == NULL) {
        return;
    }
    state->old_damage = state->damage_percent;
    state->damage_percent = Player_GetDamage((signed char) state->player_slot);
    if (state->damage_percent > 999) {
        state->damage_percent = 999;
    } else if (state->damage_percent < 0) {
        state->damage_percent = 0;
    }
    if (state->old_damage != -1 &&
        state->damage_percent > state->old_damage) {
        state->force_digit_shake = 1;
        diff = state->old_damage - state->damage_percent;
        if (diff < 0) {
            diff = -diff;
        }
        state->damage_from_last_attack = diff;
        return;
    }
    state->force_digit_shake = 0;
}

static void pf_ifStatus_headless_update_shake(HSD_GObj* gobj)
{
    PfHeadlessDamageHudState* state = gobj->user_data;
    IfDamageState* source_state =
        &ifStatus_GetHUDInfo()->players[state->player_slot];
    int i;

    /*
     * A stock loss sets the source-owned HUD explode/randomize flags through
     * ifStatus_802F69C0 and its siblings before this UI process runs. The
     * first ifStatus_PercentOnDeathAnimationThink invocation samples X/Y
     * velocities for all four flying percent digits, consuming eight values
     * from the gameplay-global RNG, then clears randomize_velocity. Native
     * headless mode has no digit JObjs, but it must preserve that one-shot RNG
     * and suppress the ordinary damage-shake path while the death animation
     * remains active.
     */
    if (source_state->flags.explode_animation) {
        if (source_state->flags.randomize_velocity) {
            for (i = 0; i < 4; ++i) {
                (void) HSD_Randf();
                (void) HSD_Randf();
            }
            source_state->flags.randomize_velocity = 0;
        }
        pf_ifStock_headless_update(gobj, state);
        return;
    }

    pf_ifStock_headless_update(gobj, state);

    if (state->force_digit_shake) {
        state->frames_of_shake_remaining = 10;
    }
    if (state->frames_of_shake_remaining == 0) {
        return;
    }
    if (state->frames_of_shake_remaining == 1) {
        state->frames_of_shake_remaining = 0;
        return;
    }

    /*
     * ifStatus_802F4B84 samples X and Y offsets for each of four damage
     * digits. The transforms are presentation-only, but these eight HSD_Randf
     * calls advance the same global RNG used by gameplay and therefore remain
     * simulation-observable in a headless match.
     */
    for (i = 0; i < 4; ++i) {
        (void) HSD_Randf();
        (void) HSD_Randf();
    }
    state->frames_of_shake_remaining -= 1;
}

int pf_ifStatus_headless_initialize(void)
{
    int slot;

    memset(pf_headless_damage_hud, 0, sizeof(pf_headless_damage_hud));
    memset(&pf_headless_go_banner, 0, sizeof(pf_headless_go_banner));
    for (slot = 0; slot < 6; ++slot) {
        HSD_GObj* gobj;
        PfHeadlessDamageHudState* state;

        if (Player_GetPlayerSlotType(slot) == Gm_PKind_NA) {
            continue;
        }
        state = &pf_headless_damage_hud[slot];
        state->damage_percent = -1;
        state->old_damage = -1;
        state->player_slot = (unsigned char) slot;
        state->stocks = Player_GetStocks(slot);

        gobj = GObj_Create(HSD_GOBJ_CLASS_UI, 0xF, 0);
        if (gobj == NULL) {
            return 0;
        }
        gobj->user_data = state;
        if (HSD_GObj_SetupProc(gobj, pf_ifStatus_headless_update_damage,
                               0x11) == NULL ||
            HSD_GObj_SetupProc(gobj, pf_ifStatus_headless_update_shake,
                               0x11) == NULL) {
            return 0;
        }
    }
    return 1;
}

void pf_ifStatus_headless_respawn_reset(int slot)
{
    PfHeadlessDamageHudState* state;
    IfDamageState* source_state;

    if ((unsigned int) slot >= 6U ||
        Player_GetPlayerSlotType(slot) == Gm_PKind_NA) {
        return;
    }

    state = &pf_headless_damage_hud[slot];
    source_state = &ifStatus_GetHUDInfo()->players[slot];

    /*
     * fn_8016719C calls ifStatus_802F6508 after Player_80032070 recreates a
     * fighter on its respawn platform. Native headless startup deliberately
     * omits ifStatus_802F665C and the IfAll.dat JObjs, so the original
     * ifStatus_804D6D60 guard is false even though its logical reset remains
     * source-observable: leaving explode_animation set suppresses later
     * damage-shake RNG. Preserve the state writes performed by
     * ifStatus_802F6508 and the animation-status clear performed by its
     * ifStatus_802F5EC0 child, while bounding only model reconstruction.
     */
    source_state->damage_percent = -1;
    source_state->old_damage = -1;
    source_state->frames_of_shake_remaining = 0;
    source_state->flags.explode_animation = 0;
    source_state->flags.randomize_velocity = 0;
    source_state->flags.force_digit_shake = 0;
    source_state->flags.unk10 = 0;
    source_state->flags.animation_status_id = 0;
    source_state->player_slot = (unsigned char) slot;
    source_state->unk9 = 0;

    state->damage_percent = -1;
    state->old_damage = -1;
    state->frames_of_shake_remaining = 0;
    state->force_digit_shake = 0;
    state->player_slot = (unsigned char) slot;
    state->stocks = Player_GetStocks(slot);
}

/*
 * Itemless competitive matches still call the trophy-display initializer
 * unconditionally from Ground_801C5878. Its only effect is to load trophy DAT
 * tables and update persistent trophy/save-data flags; no stage, fighter,
 * collision, RNG, or match state is produced. The native headless runtime has
 * no trophy collection or presentation subsystem, so its exact competitive
 * behavior is the empty operation.
 */
void tyDisplay_8031C2CC(void)
{
}

/*
 * Match startup also preloads character and stage sound banks. The function
 * below computes only audio-bank masks and drives the asynchronous HSD audio
 * loader; it does not consume RNG or mutate fighter, item, stage, collision,
 * or match state. Headless competitive simulation owns no audio backend, so
 * the exact simulation-visible result of this preload is the empty operation.
 */
void lbAudioAx_8002785C(void)
{
}

/*
 * The pause overlay owns only GmPause.dat models, their visibility flags, and
 * a presentation GObj that tilts the illustrated stick. Match pausing,
 * scheduler suspension, and unpause timing remain source-owned in gm_16AE.c.
 * No external consumer observes the overlay's private pointers or slot, so
 * the complete headless presentation contract is the empty operation.
 */
void fn_801A0E34(void* gobj)
{
    (void) gobj;
}

void gm_801A0FEC(int slot, unsigned char flag)
{
    (void) slot;
    (void) flag;
}

void gm_801A10FC(int slot)
{
    (void) slot;
}

void fn_801A1134(void)
{
}

/* IfAll.dat is the shared HUD scene (camera, lights, damage/stock anchors). */
void ifMagnify_802FC870(void);

void ifAll_802F390C(void)
{
    ifMagnify_802FC870();
}

/* Full-screen background/color flashes, including the LbBf.dat interpreter. */
void fn_8001FC08(void) {}
void fn_8001FEC4(void* gobj, int code)
{
    (void) gobj;
    (void) code;
}
void fn_800204C8(void) {}
void lbBgFlash_800205F0(int duration) { (void) duration; }
void lbBgFlash_8002063C(int count) { (void) count; }
void lbBgFlash_80020688(int count) { (void) count; }
void lbBgFlash_800206D4(void* from, void* to, int count)
{
    (void) from;
    (void) to;
    (void) count;
}
void lbBgFlash_InitState(void* color) { (void) color; }
void fn_800208B0(unsigned char alpha) { (void) alpha; }
void lbBgFlash_800208EC(int link) { (void) link; }
void lbBgFlash_800209F4(void) {}
void fn_800219E4(void* data) { (void) data; }
void lbBgFlash_80021A10(float scale) { (void) scale; }
void lbBgFlash_80021A18(int alpha) { (void) alpha; }
void fn_80021B04(void* gobj) { (void) gobj; }
void fn_80021C1C(void) {}
void lbBgFlash_80021C48(unsigned int animation, unsigned int argument)
{
    (void) animation;
    (void) argument;
}
void fn_80021C80(void* gobj) { (void) gobj; }
