#ifndef PF_SSBM_NATIVE_PS_MATH_H
#define PF_SSBM_NATIVE_PS_MATH_H

#include <stdint.h>
#include <string.h>

/* Scalar binary32 multiplication rounds its right operand to the precision
 * used by the pinned Slippi oracle before multiplying in binary64. This is
 * observable when a reciprocal-square-root estimate has more precision than
 * a stored float. Pure value operations only; no machine or instruction state.
 * Source: Interpreter_FPUtils.h Force25Bit and Jit64 fp_tri_op(roundRHS).
 */
static inline double PF_SlippiRoundSingleMultiplier(double value)
{
    uint64_t bits;
    (void) memcpy(&bits, &value, sizeof(bits));
    bits = (bits & UINT64_C(0xfffffffff8000000)) +
           (bits & UINT64_C(0x0000000008000000));
    (void) memcpy(&value, &bits, sizeof(value));
    return value;
}

static inline float PF_SlippiMulF32FromF64(double left, double right)
{
    volatile double product = left * PF_SlippiRoundSingleMultiplier(right);
    return (float) product;
}

typedef struct PF_GekkoRsqrtEstimateEntry {
    int32_t base;
    int32_t decrement;
} PF_GekkoRsqrtEstimateEntry;

typedef struct PF_GekkoReciprocalEstimateEntry {
    int32_t base;
    int32_t decrement;
} PF_GekkoReciprocalEstimateEntry;

/*
 * Native value transform for Gekko fres/ps_res. This is the lookup and
 * exponent contract used by the pinned Slippi Dolphin oracle; like the
 * reciprocal-square-root helper below, it models only the numeric result and
 * has no guest instruction or machine state.
 */
static inline double PF_GekkoFres(double value)
{
    static const PF_GekkoReciprocalEstimateEntry table[32] = {
        { 0x7ff800, 0x3e1 }, { 0x783800, 0x3a7 },
        { 0x70ea00, 0x371 }, { 0x6a0800, 0x340 },
        { 0x638800, 0x313 }, { 0x5d6200, 0x2ea },
        { 0x579000, 0x2c4 }, { 0x520800, 0x2a0 },
        { 0x4cc800, 0x27f }, { 0x47ca00, 0x261 },
        { 0x430800, 0x245 }, { 0x3e8000, 0x22a },
        { 0x3a2c00, 0x212 }, { 0x360800, 0x1fb },
        { 0x321400, 0x1e5 }, { 0x2e4a00, 0x1d1 },
        { 0x2aa800, 0x1be }, { 0x272c00, 0x1ac },
        { 0x23d600, 0x19b }, { 0x209e00, 0x18b },
        { 0x1d8800, 0x17c }, { 0x1a9000, 0x16e },
        { 0x17ae00, 0x15b }, { 0x14f800, 0x15b },
        { 0x124400, 0x143 }, { 0x0fbe00, 0x143 },
        { 0x0d3800, 0x12d }, { 0x0ade00, 0x12d },
        { 0x088400, 0x11a }, { 0x065000, 0x11a },
        { 0x041c00, 0x108 }, { 0x020c00, 0x106 },
    };
    uint64_t bits;
    const uint64_t sign_mask = UINT64_C(0x8000000000000000);
    const uint64_t exponent_mask = UINT64_C(0x7ff0000000000000);
    const uint64_t mantissa_mask = UINT64_C(0x000fffffffffffff);
    const uint64_t quiet_nan_bit = UINT64_C(0x0008000000000000);
    uint64_t mantissa;
    uint64_t sign;
    uint64_t exponent;
    int index_input;
    int table_index;
    int table_remainder;

    (void) memcpy(&bits, &value, sizeof(bits));
    mantissa = bits & mantissa_mask;
    sign = bits & sign_mask;
    exponent = bits & exponent_mask;

    if (mantissa == 0U && exponent == 0U) {
        bits = sign | UINT64_C(0x7ff0000000000000);
    } else if (exponent == exponent_mask) {
        bits = mantissa == 0U ? sign : bits | quiet_nan_bit;
    } else if (exponent < (UINT64_C(895) << 52U)) {
        bits = sign | UINT64_C(0x47efffffe0000000);
    } else if (exponent >= (UINT64_C(1149) << 52U)) {
        bits = sign;
    } else {
        index_input = (int) (mantissa >> 37U);
        table_index = index_input / 1024;
        table_remainder = index_input % 1024;
        bits = sign | ((UINT64_C(0x7fd) << 52U) - exponent) |
               ((uint64_t) (table[table_index].base -
                            (table[table_index].decrement * table_remainder +
                             1) /
                                2)
                << 29U);
    }
    (void) memcpy(&value, &bits, sizeof(value));
    return value;
}

/*
 * Native numeric compatibility for the Gekko frsqrte result used by the
 * Dolphin SDK paired-single vector routines. This is deliberately a pure
 * value transform: it has no guest registers, instruction decoder, memory,
 * exceptions, or other emulator state.
 *
 * The lookup contract is shared by the pinned ExiAI Slippi Dolphin fork
 * (bf1aec4de4856eab412996137287f447daa8ae17) and upstream Dolphin
 * (1fd7f3521895f285aa9382af8e7e464991437225).
 */
static inline double PF_GekkoFrsqrte(double value)
{
    static const PF_GekkoRsqrtEstimateEntry table[32] = {
        { 0x1a7e800, -0x568 }, { 0x17cb800, -0x4f3 },
        { 0x1552800, -0x48d }, { 0x130c000, -0x435 },
        { 0x10f2000, -0x3e7 }, { 0x0eff000, -0x3a2 },
        { 0x0d2e000, -0x365 }, { 0x0b7c000, -0x32e },
        { 0x09e5000, -0x2fc }, { 0x0867000, -0x2d0 },
        { 0x06ff000, -0x2a8 }, { 0x05ab800, -0x283 },
        { 0x046a000, -0x261 }, { 0x0339800, -0x243 },
        { 0x0218800, -0x226 }, { 0x0105800, -0x20b },
        { 0x3ffa000, -0x7a4 }, { 0x3c29000, -0x700 },
        { 0x38aa000, -0x670 }, { 0x3572000, -0x5f2 },
        { 0x3279000, -0x584 }, { 0x2fb7000, -0x524 },
        { 0x2d26000, -0x4cc }, { 0x2ac0000, -0x47e },
        { 0x2881000, -0x43a }, { 0x2665000, -0x3fa },
        { 0x2468000, -0x3c2 }, { 0x2287000, -0x38e },
        { 0x20c1000, -0x35e }, { 0x1f12000, -0x332 },
        { 0x1d79000, -0x30a }, { 0x1bf4000, -0x2e6 },
    };
    uint64_t bits;
    uint64_t mantissa;
    const uint64_t sign_mask = UINT64_C(0x8000000000000000);
    const uint64_t exponent_mask = UINT64_C(0x7ff0000000000000);
    const uint64_t mantissa_mask = UINT64_C(0x000fffffffffffff);
    const uint64_t quiet_nan_bit = UINT64_C(0x0008000000000000);
    uint64_t sign;
    int64_t exponent;
    int64_t exponent_lsb;
    int index_input;
    int table_index;
    int table_remainder;

    (void) memcpy(&bits, &value, sizeof(bits));
    mantissa = bits & mantissa_mask;
    sign = bits & sign_mask;
    exponent = (int64_t) (bits & exponent_mask);

    if (mantissa == 0U && exponent == 0) {
        bits = sign != 0U ? UINT64_C(0xfff0000000000000)
                          : UINT64_C(0x7ff0000000000000);
        (void) memcpy(&value, &bits, sizeof(value));
        return value;
    }
    if ((uint64_t) exponent == exponent_mask) {
        if (mantissa == 0U) {
            bits = sign != 0U ? UINT64_C(0x7ff8000000000000) : 0U;
        } else {
            bits |= quiet_nan_bit;
        }
        (void) memcpy(&value, &bits, sizeof(value));
        return value;
    }
    if (sign != 0U) {
        bits = UINT64_C(0x7ff8000000000000);
        (void) memcpy(&value, &bits, sizeof(value));
        return value;
    }

    if (exponent == 0) {
        do {
            exponent -= INT64_C(1) << 52;
            mantissa <<= 1U;
        } while ((mantissa & (UINT64_C(1) << 52)) == 0U);
        mantissa &= mantissa_mask;
        exponent += INT64_C(1) << 52;
    }

    exponent_lsb = exponent & (INT64_C(1) << 52);
    exponent = ((INT64_C(0x3ff) << 52) -
                ((exponent - (INT64_C(0x3fe) << 52)) / 2)) &
               (INT64_C(0x7ff) << 52);
    index_input = (int) (((uint64_t) exponent_lsb | mantissa) >> 37U);
    table_index = index_input / 2048;
    table_remainder = index_input % 2048;
    bits = (uint64_t) exponent |
           ((uint64_t) (table[table_index].base +
                        table[table_index].decrement * table_remainder)
            << 26U);
    (void) memcpy(&value, &bits, sizeof(value));
    return value;
}

#endif
