#include "native_slippi_frame_start.h"

#include "baselib/gobj.h"
#include "baselib/gobjproc.h"
#include "native_rng.h"

static bool frame_start_installed;
static bool frame_start_captured;
static uint32_t frame_start_seed;

static void capture_frame_start_seed(HSD_GObj* gobj)
{
    (void) gobj;
    frame_start_seed = pf_ssbm_native_rng_get();
    frame_start_captured = true;
}

void pf_ssbm_native_slippi_frame_start_reset(void)
{
    frame_start_installed = false;
    frame_start_captured = false;
    frame_start_seed = 0;
}

void pf_ssbm_native_slippi_frame_start_install(void)
{
    HSD_GObj* gobj;

    if (frame_start_installed) {
        return;
    }
    gobj = GObj_Create(HSD_GOBJ_CLASS_FIGHTER, 7, 0);
    if (gobj != NULL &&
        HSD_GObj_SetupProc(gobj, capture_frame_start_seed, 0) != NULL) {
        frame_start_installed = true;
    }
}

uint8_t pf_ssbm_native_slippi_frame_start_installed(void)
{
    return frame_start_installed;
}

void pf_ssbm_native_slippi_frame_start_begin_frame(void)
{
    frame_start_captured = false;
}

uint8_t pf_ssbm_native_slippi_frame_start_take(uint32_t* out_seed)
{
    if (!frame_start_captured || out_seed == NULL) {
        return false;
    }
    *out_seed = frame_start_seed;
    frame_start_captured = false;
    return true;
}
