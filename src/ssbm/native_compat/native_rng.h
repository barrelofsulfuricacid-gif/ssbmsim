#ifndef PF_SSBM_NATIVE_RNG_H
#define PF_SSBM_NATIVE_RNG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void pf_ssbm_native_rng_set(uint32_t value);
uint32_t pf_ssbm_native_rng_get(void);

#ifdef __cplusplus
}
#endif

#endif
