#ifndef PF_SSBM_NATIVE_OBJALLOC_H
#define PF_SSBM_NATIVE_OBJALLOC_H

#include <stddef.h>
#include <stdint.h>

typedef struct _HSD_ObjAllocData HSD_ObjAllocData;

#ifdef __cplusplus
extern "C" {
#endif

/* Bind HSD object-pool growth to caller-owned storage. No heap fallback exists. */
void pf_hsd_obj_arena_bind(void* storage, size_t bytes);
size_t pf_hsd_obj_arena_bytes_used(void);
size_t pf_hsd_obj_arena_bytes_remaining(void);
int pf_hsd_obj_pool_prepare(
    HSD_ObjAllocData* data,
    size_t object_bytes,
    size_t alignment,
    uint32_t capacity);
uint32_t pf_hsd_obj_pool_used(const HSD_ObjAllocData* data);

#ifdef __cplusplus
}
#endif

#endif
