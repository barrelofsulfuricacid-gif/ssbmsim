#include "native_fd_scene.h"
#include "native_rng.h"

static uint8_t scene_mode;

void pf_ssbm_native_fd_scene_configure(uint8_t mode)
{
    scene_mode = mode;
}

void pf_ssbm_native_fd_scene_update(
    struct HSD_GObj* gobj, void (*update)(struct HSD_GObj*))
{
    /* Slippi's 0x8021AAE4 hook controls this call, not the other stage
     * callbacks. A recorded NOP disables it; DesyncProofBGTransformations
     * calls it with the shared RNG restored afterward. */
    if (scene_mode == PF_SSBM_FD_SCENE_DISABLED) return;
    if (scene_mode == PF_SSBM_FD_SCENE_PRESERVE_RNG) {
        uint32_t saved_seed = pf_ssbm_native_rng_get();
        update(gobj);
        pf_ssbm_native_rng_set(saved_seed);
    } else {
        update(gobj);
    }
}
