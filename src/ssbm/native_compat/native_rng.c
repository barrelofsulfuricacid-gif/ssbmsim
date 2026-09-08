#include "native_rng.h"

#include "platform.h"

extern u32 seed;
extern u32* seed_ptr;

void pf_ssbm_native_rng_set(uint32_t value)
{
    seed = value;
    seed_ptr = &seed;
}

uint32_t pf_ssbm_native_rng_get(void)
{
    return *seed_ptr;
}
