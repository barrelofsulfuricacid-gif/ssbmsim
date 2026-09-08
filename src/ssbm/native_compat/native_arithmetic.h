#ifndef PF_SSBM_NATIVE_ARITHMETIC_H
#define PF_SSBM_NATIVE_ARITHMETIC_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { PF_SSBM_ARITHMETIC_FUSED = 0, PF_SSBM_ARITHMETIC_SEPARATE = 1 };
uint8_t pf_ssbm_native_arithmetic_configure(uint8_t profile);
uint8_t pf_ssbm_native_arithmetic_current(void);
#ifdef __cplusplus
}
#endif
#endif
