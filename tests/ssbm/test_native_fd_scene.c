#include "native_fd_scene.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>

static uint32_t rng;
static unsigned calls;
static struct HSD_GObj* expected;
uint32_t pf_ssbm_native_rng_get(void) { return rng; }
void pf_ssbm_native_rng_set(uint32_t value) { rng = value; }
static void update(struct HSD_GObj* gobj)
{
    assert(gobj == expected);
    ++calls;
    rng = rng * 1664525u + 1013904223u;
}
int main(void)
{
    unsigned object;
    expected = (struct HSD_GObj*)&object;
    pf_ssbm_native_fd_scene_configure(PF_SSBM_FD_SCENE_VANILLA);
    rng = 123;
    pf_ssbm_native_fd_scene_update(expected, update);
    assert(calls == 1 && rng != 123);
    pf_ssbm_native_fd_scene_configure(PF_SSBM_FD_SCENE_DISABLED);
    rng = 123;
    pf_ssbm_native_fd_scene_update(expected, update);
    assert(calls == 1 && rng == 123);
    pf_ssbm_native_fd_scene_configure(PF_SSBM_FD_SCENE_PRESERVE_RNG);
    pf_ssbm_native_fd_scene_update(expected, update);
    assert(calls == 2 && rng == 123);
    pf_ssbm_native_fd_scene_configure(PF_SSBM_FD_SCENE_VANILLA);
    pf_ssbm_native_fd_scene_update(expected, update);
    assert(calls == 3 && rng != 123);
    puts("ssbm-fd-scene=pass");
}
