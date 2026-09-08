#ifndef PF_SSBM_NATIVE_SLIPPI_SPAWN_H
#define PF_SSBM_NATIVE_SLIPPI_SPAWN_H
#include <stdint.h>
struct HSD_GObj;
#ifdef __cplusplus
extern "C" {
#endif
void pf_ssbm_native_slippi_spawn_begin_frame(uint64_t runtime_frame);
void pf_ssbm_native_slippi_spawn_correct(struct HSD_GObj* gobj);
#ifdef __cplusplus
}
#endif
#endif
