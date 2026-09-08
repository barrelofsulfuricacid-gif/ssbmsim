#ifndef PF_SSBM_NATIVE_NUMERIC_H
#define PF_SSBM_NATIVE_NUMERIC_H

#include <dolphin/types.h>

#include <stdint.h>
#include <math.h>
#include "native_arithmetic.h"

/* Slippi playback variants differ in binary64 contraction. The caller
 * chooses one profile at match initialization, before gameplay executes. */
static inline double PF_SlippiMulAddF64(double a, double b, double c)
{
    if (pf_ssbm_native_arithmetic_current() == PF_SSBM_ARITHMETIC_FUSED) {
        return fma(a, b, c);
    }
    volatile double product = a * b;
    volatile double result = product + c;
    return result;
}

/* A binary32 product is exact in binary64. Both oracle modes then round
 * their binary64 sum before converting to binary32. Direct fmaf can skip
 * that intermediate rounding at halfway boundaries. */
static inline float PF_SlippiMulAddF32(float a, float b, float c)
{
    volatile double product = (double)a * (double)b;
    volatile double result = product + (double)c;
    return (float)result;
}

static inline u16 PF_QuantizeU16Scale0(f32 value)
{
    if (!(value > 0.0F)) {
        return 0;
    }
    if (value >= (f32) UINT16_MAX) {
        return UINT16_MAX;
    }
    return (u16) value;
}

#endif
