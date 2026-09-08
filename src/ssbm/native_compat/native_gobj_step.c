#include "native_gobj_runtime.h"

#include "baselib/gobj.h"
#include "baselib/initialize.h"

void pf_ifMagnify_headless_post_frame(void);

void pf_hsd_gobj_runtime_step(void)
{
    HSD_GObj_80390CFC();
    pf_ifMagnify_headless_post_frame();
}

void pf_hsd_gobj_runtime_post_frame(void)
{
    /* Preserve source pass setup and camera callback ordering from
     * gm_801A4D34 after its active scheduler/bookend counters. */
    HSD_StartRender(HSD_RP_SCREEN);
    HSD_GObj_80390FC0();
    HSD_Init_803755A8();
}
