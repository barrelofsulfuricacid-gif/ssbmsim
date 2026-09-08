#include "native_arithmetic.h"
static uint8_t arithmetic_profile = PF_SSBM_ARITHMETIC_FUSED;
uint8_t pf_ssbm_native_arithmetic_configure(uint8_t profile)
{
    if (profile > PF_SSBM_ARITHMETIC_SEPARATE) return 0;
    arithmetic_profile = profile;
    return 1;
}
uint8_t pf_ssbm_native_arithmetic_current(void)
{
    return arithmetic_profile;
}
