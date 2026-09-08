#ifndef PF_SSBM_NATIVE_MSL_MATH_H
#define PF_SSBM_NATIVE_MSL_MATH_H

#include <dolphin/types.h>

#include "native_ps_math.h"
#include "native_numeric.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

static inline uint32_t PF_MSLFloatBits(f32 value)
{
    uint32_t bits;
    (void) memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static inline f32 PF_MSLFloatFromBits(uint32_t bits)
{
    f32 value;
    (void) memcpy(&value, &bits, sizeof(value));
    return value;
}

/*
 * Native form of Runtime.__cvt_dbl_usll for a binary32 input widened exactly
 * to double. It truncates toward zero and saturates outside signed-64 range,
 * including infinities and NaNs according to their sign bit.
 */
static inline int64_t PF_MSLTruncS64FromF32(f32 value)
{
    const uint32_t bits = PF_MSLFloatBits(value);
    const uint32_t exponent = (bits >> 23) & UINT32_C(0xff);
    const int negative = (bits & UINT32_C(0x80000000)) != 0;
    uint64_t magnitude;
    int shift;

    if (exponent < 127) {
        return 0;
    }
    if (exponent > 189) {
        return negative ? INT64_MIN : INT64_MAX;
    }

    magnitude = UINT64_C(0x800000) | (bits & UINT32_C(0x007fffff));
    shift = (int) exponent - 127 - 23;
    if (shift >= 0) {
        magnitude <<= shift;
    } else {
        magnitude >>= -shift;
    }
    return negative ? -(int64_t) magnitude : (int64_t) magnitude;
}

/*
 * Exact native form of src/MSL/math.h fmodf as emitted in GALE01. The double
 * expression is exact for the binary32 product and cancellation domain, then
 * its final binary32 conversion reproduces Gekko's fused fnmsubs rounding.
 */
static inline f32 PF_MSLFmodf(f32 a, f32 b)
{
    const f32 abs_a = PF_MSLFloatFromBits(
        PF_MSLFloatBits(a) & UINT32_C(0x7fffffff));
    const f32 abs_b = PF_MSLFloatFromBits(
        PF_MSLFloatBits(b) & UINT32_C(0x7fffffff));
    f32 quotient_input;
    int64_t quotient;
    f32 quotient_float;

    if (abs_b > abs_a) {
        return a;
    }
    quotient_input = a / b;
    quotient = PF_MSLTruncS64FromF32(quotient_input);
    quotient_float = (f32) quotient;
    return (f32) ((f64) a - (f64) b * (f64) quotient_float);
}

/*
 * Exact native form of the Newton sequence emitted for MSL math_ppc.h's
 * sqrtf and sqrtf_accurate under Slippi deterministic arithmetic. Preserve
 * the binary64 multiply, subtract, then negate rounding of its fnmsub path.
 */
static inline f64 PF_MSLRsqrtRefine(f64 x, f64 guess)
{
    const f64 square = guess * guess;
    const f64 half_guess = 0.5 * guess;
    const f64 correction = -PF_SlippiMulAddF64(x, square, -3.0);
    return half_guess * correction;
}

static inline f64 PF_MSLRsqrtEstimate(f32 x, int iteration_count)
{
    const f64 input = (f64) x;
    f64 guess = PF_GekkoFrsqrte(input);
    int iteration;

    for (iteration = 0; iteration < iteration_count; ++iteration) {
        guess = PF_MSLRsqrtRefine(input, guess);
    }
    return guess;
}

static inline f32 PF_MSLSqrtf(f32 x)
{
    volatile f32 result;

    if (x > 0.0F) {
        const f64 guess = PF_MSLRsqrtEstimate(x, 3);
        result = (f32) ((f64) x * guess);
        return result;
    }
    return x;
}

static inline f32 PF_MSLSqrtfAccurate(f32 x)
{
    volatile f32 result;

    if (x > 0.0F) {
        const f64 guess = PF_MSLRsqrtEstimate(x, 4);
        result = (f32) ((f64) x * guess);
        return result;
    }
    return x;
}

#endif
