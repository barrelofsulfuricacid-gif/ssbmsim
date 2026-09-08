#ifndef PF_SSBM_NATIVE_GOBJ_RUNTIME_H
#define PF_SSBM_NATIVE_GOBJ_RUNTIME_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum PfHsdGObjRuntimeStatus {
    PF_HSD_GOBJ_RUNTIME_OK = 0,
    PF_HSD_GOBJ_RUNTIME_INVALID_ARGUMENT = 1,
    PF_HSD_GOBJ_RUNTIME_STARTUP_ARENA_TOO_SMALL = 2,
    PF_HSD_GOBJ_RUNTIME_OBJECT_ARENA_TOO_SMALL = 3,
    PF_HSD_GOBJ_RUNTIME_MEMORY_POOL_TOO_SMALL = 4,
    PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_STATE = 5,
    PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_CAPACITY = 6,
} PfHsdGObjRuntimeStatus;

PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_initialize(
    void* startup_storage,
    size_t startup_bytes,
    void* object_storage,
    size_t object_bytes,
    uint32_t gobj_capacity,
    uint32_t process_capacity,
    uint64_t* disabled_process_links);
PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_prewarm_memory_pool(
    uint32_t pieces_per_size_class);
PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_begin_deferred_process_capture(void);
PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_end_deferred_process_capture(void);
PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_activate_deferred_stage_start(void);
uint32_t pf_hsd_gobj_runtime_deferred_process_count(void);
int pf_hsd_gobj_runtime_deferred_stage_start_is_active(void);
PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_finalize_initialization(void);
void pf_hsd_gobj_runtime_step(void);
void pf_hsd_gobj_runtime_post_frame(void);
size_t pf_hsd_gobj_runtime_startup_bytes_used(void);
size_t pf_hsd_gobj_runtime_object_bytes_used(void);

#ifdef __cplusplus
}
#endif

#endif
