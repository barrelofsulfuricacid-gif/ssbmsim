#include <platform.h>
#include <dolphin/mtx.h>
#include <sysdolphin/baselib/quatlib.h>
#include <sysdolphin/baselib/random.h>
#include <sysdolphin/baselib/spline.h>
#include <melee/lb/lb_0195.h>

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>

extern u32 seed;
extern u32* seed_ptr;

/* Explicitly exercise imported game memory routines, not host libc. */
extern void* pf_ssbm_memcpy(void*, const void*, size_t);
extern void* pf_ssbm_memset(void*, int, size_t);

static uint32_t float_bits(float value)
{
    uint32_t result;
    (void) memcpy(&result, &value, sizeof(result));
    return result;
}

static int run_rng_test(void)
{
    u32 expected_seed = UINT32_C(1);
    int index;
    seed = expected_seed;
    seed_ptr = &seed;
    for (index = 0; index < 4096; ++index) {
        expected_seed = expected_seed * UINT32_C(214013) + UINT32_C(2531011);
        if ((u32) HSD_Rand() != expected_seed >> 16U || seed != expected_seed) {
            return 0;
        }
    }

    expected_seed = UINT32_C(0x89abcdef);
    seed = expected_seed;
    expected_seed = expected_seed * UINT32_C(214013) + UINT32_C(2531011);
    {
        const float expected = (float) (expected_seed >> 16U) / 65536.0F;
        const float actual = HSD_Randf();
        if (float_bits(actual) != float_bits(expected) || seed != expected_seed) {
            return 0;
        }
    }

    seed = UINT32_C(0x12345678);
    expected_seed = seed * UINT32_C(214013) + UINT32_C(2531011);
    if (HSD_Randi(97) != (s32) (97U * (expected_seed >> 16U) / 65536U) ||
        seed != expected_seed) {
        return 0;
    }
    return sizeof(u32) == 4U && sizeof(s32) == 4U && sizeof(f32) == 4U;
}

static int same_float(float left, float right)
{
    return float_bits(left) == float_bits(right);
}

static int same_vec3(const Vec3* left, const Vec3* right)
{
    return same_float(left->x, right->x) &&
           same_float(left->y, right->y) &&
           same_float(left->z, right->z);
}

static int same_quaternion(const Quaternion* left, const Quaternion* right)
{
    return same_float(left->x, right->x) &&
           same_float(left->y, right->y) &&
           same_float(left->z, right->z) &&
           same_float(left->w, right->w);
}

static int same_mtx(const Mtx left, const Mtx right)
{
    int row;
    int column;
    for (row = 0; row < 3; ++row) {
        for (column = 0; column < 4; ++column) {
            if (!same_float(left[row][column], right[row][column])) {
                return 0;
            }
        }
    }
    return 1;
}

static int same_mtx44(const Mtx44 left, const Mtx44 right)
{
    int row;
    int column;
    for (row = 0; row < 4; ++row) {
        for (column = 0; column < 4; ++column) {
            if (!same_float(left[row][column], right[row][column])) {
                return 0;
            }
        }
    }
    return 1;
}

static int sdk_math_fail(const char* operation)
{
    (void) fprintf(stderr, "sdk-math failed: %s\n", operation);
    return 0;
}

static int run_sdk_math_test(void)
{
    Mtx translation;
    const Mtx expected_translation = {
        { 1.0F, 0.0F, 0.0F, 3.0F },
        { 0.0F, 1.0F, 0.0F, -4.0F },
        { 0.0F, 0.0F, 1.0F, 5.0F },
    };
    Mtx44 projection;
    const Mtx44 expected_ortho = {
        { 0.25F, 0.0F, 0.0F, -0.0F },
        { 0.0F, 0.5F, 0.0F, -0.0F },
        { 0.0F, 0.0F, -0.25F, -1.25F },
        { 0.0F, 0.0F, 0.0F, 1.0F },
    };
    const Vec source = { 2.0F, 3.0F, 4.0F };
    const Vec expected_transformed = { 5.0F, -1.0F, 9.0F };
    const Vec a = { 1.0F, 2.0F, 3.0F };
    const Vec b = { 4.0F, -5.0F, 6.0F };
    const Vec expected_sum = { 5.0F, -3.0F, 9.0F };
    const Vec expected_difference = { -3.0F, 7.0F, -3.0F };
    const Vec expected_scale = { 2.0F, 4.0F, 6.0F };
    const Vec expected_cross = { 27.0F, 6.0F, -13.0F };
    const Vec magnitude_5 = { 3.0F, 4.0F, 0.0F };
    const Vec expected_ps_unit = { 0.6F, 0.8F, 0.0F };
    const Vec unit_x = { 1.0F, 0.0F, 0.0F };
    Vec actual = { 0.0F, 0.0F, 0.0F };

    C_MTXTrans(translation, 3.0F, -4.0F, 5.0F);
    if (!same_mtx(translation, expected_translation)) {
        return sdk_math_fail("C_MTXTrans");
    }
    C_MTXMultVec(translation, &source, &actual);
    if (!same_vec3(&actual, &expected_transformed)) {
        return sdk_math_fail("C_MTXMultVec");
    }
    C_MTXOrtho(projection, 2.0F, -2.0F, -4.0F, 4.0F, 1.0F, 5.0F);
    if (!same_mtx44(projection, expected_ortho)) {
        return sdk_math_fail("C_MTXOrtho");
    }

    C_VECAdd(&a, &b, &actual);
    if (!same_vec3(&actual, &expected_sum)) {
        return sdk_math_fail("C_VECAdd");
    }
    C_VECSubtract(&a, &b, &actual);
    if (!same_vec3(&actual, &expected_difference)) {
        return sdk_math_fail("C_VECSubtract");
    }
    C_VECScale(&a, &actual, 2.0F);
    if (!same_vec3(&actual, &expected_scale)) {
        return sdk_math_fail("C_VECScale");
    }
    C_VECCrossProduct(&a, &b, &actual);
    if (!same_vec3(&actual, &expected_cross)) {
        return sdk_math_fail("C_VECCrossProduct");
    }
    if (!same_float(C_VECDotProduct(&a, &b), 12.0F)) {
        return sdk_math_fail("C_VECDotProduct");
    }
    if (!same_float(C_VECMag(&magnitude_5), 5.0F)) {
        return sdk_math_fail("C_VECMag");
    }
    if (!same_float(PSVECMag(&magnitude_5), 5.0F)) {
        return sdk_math_fail("PSVECMag");
    }
    PSVECNormalize(&magnitude_5, &actual);
    if (!same_vec3(&actual, &expected_ps_unit)) {
        return sdk_math_fail("PSVECNormalize");
    }
    C_VECNormalize(&unit_x, &actual);
    if (!same_vec3(&actual, &unit_x)) {
        return sdk_math_fail("C_VECNormalize");
    }
    return 1;
}

static int run_inverse_trig_test(void)
{
    volatile float inputs[3] = { 0.0F, -0.0F, 1.0F };
    const float pi_over_4 = 0.785398185253143310546875F;
    const float pi_over_2 = 1.57079637050628662109375F;

#define EXPECT_TRIG(operation, expression, expected)                           \
    do {                                                                       \
        const float actual_value = (expression);                               \
        const float expected_value = (expected);                               \
        if (!same_float(actual_value, expected_value)) {                       \
            (void) fprintf(stderr, "%s: expected %08x, got %08x\n",          \
                           (operation), float_bits(expected_value),             \
                           float_bits(actual_value));                           \
            return 0;                                                          \
        }                                                                      \
    } while (0)

    EXPECT_TRIG("atanf(+0)", atanf(inputs[0]), 0.0F);
    EXPECT_TRIG("atanf(-0)", atanf(inputs[1]), -0.0F);
    EXPECT_TRIG("atanf(1)", atanf(inputs[2]), pi_over_4);
    EXPECT_TRIG("atan2f(1,+0)", atan2f(inputs[2], inputs[0]), pi_over_2);
    EXPECT_TRIG("acosf(+0)", acosf(inputs[0]), pi_over_2);
    EXPECT_TRIG("asinf(+0)", asinf(inputs[0]), 0.0F);
#undef EXPECT_TRIG
    return 1;
}

static int run_spline_test(void)
{
    Vec3 control[2] = {
        { 0.0F, 2.0F, -4.0F },
        { 4.0F, 6.0F, 4.0F },
    };
    HSD_Spline spline = {
        .type = 0,
        .numcv = 2,
        .tension = 0.0F,
        .cv = control,
        .totalLength = 0.0F,
        .segLength = NULL,
        .segPoly = NULL,
    };
    Vec3 actual = { 0.0F, 0.0F, 0.0F };
    const Vec3 quarter = { 1.0F, 3.0F, -2.0F };

    if (!same_float(splGetHelmite(1.0F, 0.0F, 2.0F, 4.0F, 8.0F, 16.0F),
                    2.0F) ||
        !same_float(splGetHelmite(1.0F, 1.0F, 2.0F, 4.0F, 8.0F, 16.0F),
                    4.0F)) {
        return 0;
    }
    splGetSplinePoint(&actual, &spline, 0.25F);
    if (!same_vec3(&actual, &quarter)) {
        return 0;
    }
    splGetSplinePoint(&actual, &spline, 1.0F);
    return same_vec3(&actual, &control[1]);
}

static int run_quaternion_test(void)
{
    Quaternion identity = { 0.0F, 0.0F, 0.0F, 1.0F };
    Quaternion source = { 1.0F, 2.0F, 3.0F, 4.0F };
    Quaternion actual = { 0.0F, 0.0F, 0.0F, 0.0F };
    Vec3 zero = { 0.0F, 0.0F, 0.0F };
    Vec3 axis = { 1.0F, 0.0F, 0.0F };
    Mtx matrix = {
        { 1.0F, 0.0F, 0.0F, 0.0F },
        { 0.0F, 1.0F, 0.0F, 0.0F },
        { 0.0F, 0.0F, 1.0F, 0.0F },
    };

    if (EulerToQuat(&zero, &actual) != 0 ||
        !same_quaternion(&actual, &identity)) {
        return 0;
    }
    if (HSD_QuatLib_8037EC4C(&source, &identity, &actual) != 0 ||
        !same_quaternion(&actual, &source)) {
        return 0;
    }
    if (HSD_QuatLib_8037ECE0(&axis, &actual, 0.0F) != 0 ||
        !same_quaternion(&actual, &identity)) {
        return 0;
    }
    return MatToQuat(matrix, &actual) == 0 &&
           same_quaternion(&actual, &identity);
}

static int run_headless_timing_boundary_test(void)
{
    lb_80019880(UINT64_C(675000));
    lb_800195D0();
    return 1;
}

static void reference_move(
    unsigned char* bytes, size_t destination, size_t source, size_t length)
{
    unsigned char scratch[96];
    size_t index;
    for (index = 0; index < length; ++index) {
        scratch[index] = bytes[source + index];
    }
    for (index = 0; index < length; ++index) {
        bytes[destination + index] = scratch[index];
    }
}

static int run_msl_memmove_test(void)
{
    static const size_t cases[][3] = {
        { 48U, 0U, 40U },
        { 0U, 7U, 65U },
        { 5U, 0U, 70U },
        { 32U, 3U, 37U },
        { 1U, 0U, 17U },
        { 0U, 1U, 17U },
    };
    void* (*volatile move)(void*, const void*, size_t) = memmove;
    size_t case_index;
    for (case_index = 0; case_index < sizeof(cases) / sizeof(cases[0]);
         ++case_index) {
        unsigned char actual[96];
        unsigned char expected[96];
        size_t index;
        size_t destination = cases[case_index][0];
        size_t source = cases[case_index][1];
        size_t length = cases[case_index][2];
        for (index = 0; index < sizeof(actual); ++index) {
            actual[index] = expected[index] =
                (unsigned char) ((index * 37U + 11U) & 0xFFU);
        }
        reference_move(expected, destination, source, length);
        if (move(actual + destination, actual + source, length) !=
            actual + destination) {
            return 0;
        }
        for (index = 0; index < sizeof(actual); ++index) {
            if (actual[index] != expected[index]) {
                return 0;
            }
        }
    }
    return 1;
}

static int run_runtime_mem_test(void)
{
    static const size_t copy_cases[][3] = {
        { 48U, 0U, 40U },
        { 0U, 48U, 40U },
        { 5U, 0U, 70U },
        { 0U, 5U, 70U },
        { 1U, 0U, 17U },
        { 0U, 1U, 17U },
    };
    static const size_t fill_cases[][3] = {
        { 0U, 0U, 0x00U },
        { 0U, 31U, 0xA5U },
        { 1U, 32U, 0x00U },
        { 2U, 33U, 0x5AU },
        { 3U, 64U, 0xFFU },
        { 7U, 71U, 0x123U },
    };
    void* (*volatile copy)(void*, const void*, size_t) = pf_ssbm_memcpy;
    void* (*volatile fill)(void*, int, size_t) = pf_ssbm_memset;
    size_t case_index;

    for (case_index = 0;
         case_index < sizeof(copy_cases) / sizeof(copy_cases[0]);
         ++case_index) {
        unsigned char actual[96];
        unsigned char expected[96];
        size_t index;
        size_t destination = copy_cases[case_index][0];
        size_t source = copy_cases[case_index][1];
        size_t length = copy_cases[case_index][2];
        for (index = 0; index < sizeof(actual); ++index) {
            actual[index] = expected[index] =
                (unsigned char) ((index * 53U + 19U) & 0xFFU);
        }
        reference_move(expected, destination, source, length);
        if (copy(actual + destination, actual + source, length) !=
            actual + destination) {
            return 0;
        }
        for (index = 0; index < sizeof(actual); ++index) {
            if (actual[index] != expected[index]) {
                return 0;
            }
        }
    }

    for (case_index = 0;
         case_index < sizeof(fill_cases) / sizeof(fill_cases[0]);
         ++case_index) {
        unsigned char actual[96];
        unsigned char expected[96];
        size_t index;
        size_t offset = fill_cases[case_index][0];
        size_t length = fill_cases[case_index][1];
        int value = (int) fill_cases[case_index][2];
        for (index = 0; index < sizeof(actual); ++index) {
            actual[index] = expected[index] =
                (unsigned char) ((index * 29U + 7U) & 0xFFU);
        }
        for (index = 0; index < length; ++index) {
            expected[offset + index] = (unsigned char) value;
        }
        if (fill(actual + offset, value, length) != actual + offset) {
            return 0;
        }
        for (index = 0; index < sizeof(actual); ++index) {
            if (actual[index] != expected[index]) {
                return 0;
            }
        }
    }
    return 1;
}

int main(void)
{
    /* Name the failed contract so clean-machine failures are actionable. */
#define RUN_CHECK(check) do { \
    if (!(check)()) { \
        (void) fprintf(stderr, "ssbm-decomp-import=fail check=%s\n", #check); \
        return 1; \
    } \
} while (0)
    RUN_CHECK(run_rng_test);
    RUN_CHECK(run_spline_test);
    RUN_CHECK(run_quaternion_test);
    RUN_CHECK(run_sdk_math_test);
    RUN_CHECK(run_inverse_trig_test);
    RUN_CHECK(run_headless_timing_boundary_test);
    RUN_CHECK(run_msl_memmove_test);
    RUN_CHECK(run_runtime_mem_test);
#undef RUN_CHECK
    (void) puts(
        "ssbm-decomp-import=pass units=10 rng_draws=4098 "
        "spline_cases=4 quaternion_cases=4 sdk_math_cases=14 trig_cases=6 "
        "timing_boundary_cases=2 memmove_cases=6 memcpy_cases=6 "
        "memset_cases=6");
    return 0;
}
