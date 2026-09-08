#ifndef PF_SSBM_NATIVE_FD_SCENE_H
#define PF_SSBM_NATIVE_FD_SCENE_H
#include <stdint.h>
struct HSD_GObj;
#ifdef __cplusplus
extern "C" {
#endif
enum {
    PF_SSBM_FD_SCENE_VANILLA = 0,
    PF_SSBM_FD_SCENE_DISABLED = 1,
    PF_SSBM_FD_SCENE_PRESERVE_RNG = 2
};
void pf_ssbm_native_fd_scene_configure(uint8_t mode);
void pf_ssbm_native_fd_scene_update(
    struct HSD_GObj* gobj, void (*update)(struct HSD_GObj*));
#ifdef __cplusplus
}
#endif
#endif
