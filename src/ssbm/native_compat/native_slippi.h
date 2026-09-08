#ifndef PF_SSBM_NATIVE_SLIPPI_H
#define PF_SSBM_NATIVE_SLIPPI_H

#include <stdbool.h>
#include <stdint.h>

struct Fighter;
struct HSD_GObj;

typedef int (*PfSsbmNativeMagnifyPredicate)(int player);
typedef int32_t (*PfSsbmNativeStadiumMonitorPredicate)(
    struct HSD_GObj* stage_gobj);

#ifdef __cplusplus
extern "C" {
#endif

void pf_ssbm_native_slippi_configure(
    uint8_t neutral_spawns_enabled,
    uint8_t online_enabled);
void pf_ssbm_native_slippi_stadium_configure(uint8_t frozen_stadium_enabled);
uint8_t pf_ssbm_native_slippi_whispy_excludes_fighter(int32_t motion_id);
void pf_ssbm_native_slippi_stadium_mark_preloaded(void);
void pf_ssbm_native_slippi_stadium_reset_preload(void);
int pf_ssbm_native_slippi_stadium_preload(int current_transformation);
uint8_t pf_ssbm_native_slippi_stadium_is_frozen(void);
uint8_t pf_ssbm_native_slippi_stadium_monitor(
    const struct Fighter* fighter,
    struct HSD_GObj* stage_gobj,
    PfSsbmNativeStadiumMonitorPredicate vanilla_predicate);
uint8_t pf_ssbm_native_slippi_neutral_spawn(
    int stage_kind,
    uint8_t is_teams,
    unsigned int spawn_order,
    float* out_x,
    float* out_y,
    float* out_facing);
int pf_ssbm_native_slippi_brawl_offscreen_damage(
    const struct Fighter* fp,
    PfSsbmNativeMagnifyPredicate vanilla_predicate);

#ifdef __cplusplus
}
#endif

#endif
