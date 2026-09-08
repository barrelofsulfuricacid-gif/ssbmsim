#ifndef PF_SSBM_NATIVE_MEMORY_H
#define PF_SSBM_NATIVE_MEMORY_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void pf_hsd_startup_arena_bind(void* storage, size_t bytes);
void pf_hsd_startup_arena_freeze(void);
size_t pf_hsd_startup_arena_bytes_used(void);
size_t pf_hsd_startup_arena_bytes_remaining(void);
size_t pf_hsd_startup_arena_rejected_allocations(void);

#ifdef __cplusplus
}
#endif

#endif
