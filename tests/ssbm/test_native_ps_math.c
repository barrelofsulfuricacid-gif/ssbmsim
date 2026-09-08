#include "native_ps_math.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * Exact inputs and results from upstream Dolphin FloatUtilsTest.cpp at
 * 1fd7f3521895f285aa9382af8e7e464991437225.
 */
static uint64_t double_bits(double value)
{
    uint64_t result;
    (void) memcpy(&result, &value, sizeof(result));
    return result;
}

int main(void)
{
    static const uint64_t reciprocal_inputs[9] = {
        UINT64_C(0x0000000000000000), UINT64_C(0x8000000000000000),
        UINT64_C(0x3fe0000000000000), UINT64_C(0x3ff0000000000000),
        UINT64_C(0x3ff8000000000000), UINT64_C(0x4000000000000000),
        UINT64_C(0x4010000000000000), UINT64_C(0x3fefffffe0000000),
        UINT64_C(0x3ff0000020000000),
    };
    static const uint64_t reciprocal_expected[9] = {
        UINT64_C(0x7ff0000000000000), UINT64_C(0xfff0000000000000),
        UINT64_C(0x3fffff0000000000), UINT64_C(0x3fefff0000000000),
        UINT64_C(0x3fe5550000000000), UINT64_C(0x3fdfff0000000000),
        UINT64_C(0x3fcfff0000000000), UINT64_C(0x3ff0001060000000),
        UINT64_C(0x3fefff0000000000),
    };
    static const uint64_t inputs[57] = {
        UINT64_C(0x0000000000000000), UINT64_C(0x0000000000000001),
        UINT64_C(0x0000000001000000), UINT64_C(0x000fffffffffffff),
        UINT64_C(0x0010000000000000), UINT64_C(0x0010000000000002),
        UINT64_C(0x3ff0000000000000), UINT64_C(0x7fefffffffffffff),
        UINT64_C(0x7ff0000000000000), UINT64_C(0x7ff0000000000001),
        UINT64_C(0x7ff7ffffffffffff), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7fffffffffffffff), UINT64_C(0x8000000000000000),
        UINT64_C(0x8000000000000001), UINT64_C(0x8000000001000000),
        UINT64_C(0x800fffffffffffff), UINT64_C(0x8010000000000000),
        UINT64_C(0x8010000000000002), UINT64_C(0xbff0000000000000),
        UINT64_C(0xffefffffffffffff), UINT64_C(0xfff0000000000000),
        UINT64_C(0xfff0000000000001), UINT64_C(0xfff7ffffffffffff),
        UINT64_C(0xfff8000000000000), UINT64_C(0xffffffffffffffff),
        UINT64_C(0x3800000000000000), UINT64_C(0x3810000000000000),
        UINT64_C(0xb800000000000000), UINT64_C(0xb810000000000000),
        UINT64_C(0x3800123456789abc), UINT64_C(0x3810123456789abc),
        UINT64_C(0xb800123456789abc), UINT64_C(0xb810123456789abc),
        UINT64_C(0x3680000000000000), UINT64_C(0x36a0000000000000),
        UINT64_C(0x36b0000000000000), UINT64_C(0xb680000000000000),
        UINT64_C(0xb6a0000000000000), UINT64_C(0xb6b0000000000000),
        UINT64_C(0x3680123456789abc), UINT64_C(0x36a0123456789abc),
        UINT64_C(0x36b0123456789abc), UINT64_C(0xb680123456789abc),
        UINT64_C(0xb6a0123456789abc), UINT64_C(0xb6b0123456789abc),
        UINT64_C(0x47c0000000000000), UINT64_C(0x47d0000000000000),
        UINT64_C(0xc7c0000000000000), UINT64_C(0xc7d0000000000000),
        UINT64_C(0x37f0000000000000), UINT64_C(0x37e0000000000000),
        UINT64_C(0xb7f0000000000000), UINT64_C(0xb7e0000000000000),
        UINT64_C(0x3ff8000000000000), UINT64_C(0x408f400000000000),
        UINT64_C(0xc008000000000000),
    };
    static const uint64_t expected[57] = {
        UINT64_C(0x7ff0000000000000), UINT64_C(0x617ffe8000000000),
        UINT64_C(0x60bffe8000000000), UINT64_C(0x5fe000082c000000),
        UINT64_C(0x5fdffe8000000000), UINT64_C(0x5fdffe8000000000),
        UINT64_C(0x3feffe8000000000), UINT64_C(0x1ff000082c000000),
        UINT64_C(0x0000000000000000), UINT64_C(0x7ff8000000000001),
        UINT64_C(0x7fffffffffffffff), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7fffffffffffffff), UINT64_C(0xfff0000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0xfff8000000000001), UINT64_C(0xffffffffffffffff),
        UINT64_C(0xfff8000000000000), UINT64_C(0xffffffffffffffff),
        UINT64_C(0x43e69fa000000000), UINT64_C(0x43dffe8000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x43e6936060000000), UINT64_C(0x43dfed3070000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x44a69fa000000000), UINT64_C(0x44969fa000000000),
        UINT64_C(0x448ffe8000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x44a6936060000000), UINT64_C(0x4496936060000000),
        UINT64_C(0x448fed3070000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x3c069fa000000000), UINT64_C(0x3bfffe8000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x43effe8000000000), UINT64_C(0x43f69fa000000000),
        UINT64_C(0x7ff8000000000000), UINT64_C(0x7ff8000000000000),
        UINT64_C(0x3fea204000000000), UINT64_C(0x3fa0310800000000),
        UINT64_C(0x7ff8000000000000),
    };
    size_t index;

    for (index = 0;
         index < sizeof(reciprocal_inputs) / sizeof(reciprocal_inputs[0]);
         ++index) {
        double input;
        uint64_t actual;
        (void) memcpy(&input, &reciprocal_inputs[index], sizeof(input));
        actual = double_bits(PF_GekkoFres(input));
        if (actual != reciprocal_expected[index]) {
            (void) fprintf(stderr,
                           "gekko-fres[%zu]: expected %016llx, got %016llx\n",
                           index,
                           (unsigned long long) reciprocal_expected[index],
                           (unsigned long long) actual);
            return 1;
        }
    }

    for (index = 0; index < sizeof(inputs) / sizeof(inputs[0]); ++index) {
        double input;
        uint64_t actual;
        (void) memcpy(&input, &inputs[index], sizeof(input));
        actual = double_bits(PF_GekkoFrsqrte(input));
        if (actual != expected[index]) {
            (void) fprintf(stderr,
                           "gekko-frsqrte[%zu]: expected %016llx, got %016llx\n",
                           index, (unsigned long long) expected[index],
                           (unsigned long long) actual);
            return 1;
        }
    }
    {
        const double estimate = 0x1.715bd68p-4;
        const float square = PF_SlippiMulF32FromF64(estimate, estimate);
        uint32_t square_bits;
        (void) memcpy(&square_bits, &square, sizeof(square_bits));
        if (PF_SlippiRoundSingleMultiplier(estimate) != 0x1.715bd7p-4 ||
            PF_SlippiRoundSingleMultiplier(-estimate) != -0x1.715bd7p-4 ||
            PF_SlippiRoundSingleMultiplier(1.0) != 1.0 ||
            square_bits != UINT32_C(0x3c053a79))
        {
            (void) fprintf(stderr, "single-multiply precision mismatch: %08x\n",
                           square_bits);
            return 1;
        }
    }
    {
        /* Only the right operand is rounded. Swapping these operands must
         * retain the distinct results observed at the scalar boundary. */
        const double estimate = 0x1.715bd68p-4;
        const double left[] = { estimate, 0.5, -estimate };
        const double right[] = { 0.5, estimate, estimate };
        const uint32_t expected_bits[] = {
            UINT32_C(0x3d38adeb), UINT32_C(0x3d38adec), UINT32_C(0xbc053a79)
        };
        for (index = 0; index < 3; ++index) {
            const float value = PF_SlippiMulF32FromF64(left[index], right[index]);
            uint32_t bits;
            (void) memcpy(&bits, &value, sizeof(bits));
            if (bits != expected_bits[index]) {
                (void) fprintf(stderr,
                               "single-multiply operand[%zu]: %08x != %08x\n",
                               index, bits, expected_bits[index]);
                return 1;
            }
        }
    }
    (void) puts("native-ps-math=pass fres_vectors=9 frsqrte_vectors=57 single-multiply=7");
    return 0;
}
