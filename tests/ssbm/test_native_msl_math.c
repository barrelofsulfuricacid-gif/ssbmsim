#include "native_msl_math.h"

#include <stdint.h>
#include <stdio.h>

static int expect_bits(const char* label, f32 actual, uint32_t expected)
{
    const uint32_t actual_bits = PF_MSLFloatBits(actual);
    if (actual_bits != expected) {
        (void) fprintf(stderr, "%s: expected %08x, got %08x\n", label,
                       expected, actual_bits);
        return 1;
    }
    return 0;
}

static int expect_s64(const char* label, int64_t actual, int64_t expected)
{
    if (actual != expected) {
        (void) fprintf(stderr, "%s: expected %lld, got %lld\n", label,
                       (long long) expected, (long long) actual);
        return 1;
    }
    return 0;
}

static uint64_t double_bits(f64 value)
{
    uint64_t bits;
    (void) memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static int expect_double_bits(const char* label, f64 actual, uint64_t expected)
{
    const uint64_t actual_bits = double_bits(actual);
    if (actual_bits != expected) {
        (void) fprintf(stderr, "%s: expected %016llx, got %016llx\n", label,
                       (unsigned long long) expected,
                       (unsigned long long) actual_bits);
        return 1;
    }
    return 0;
}

int main(void)
{
    int failed = 0;
    if (!pf_ssbm_native_arithmetic_configure(PF_SSBM_ARITHMETIC_FUSED)) return 1;
    failed |= expect_double_bits("Slippi fused binary64 cancellation",
        PF_SlippiMulAddF64(0x1.0000002p0, 0x1.ffffffcp-1, -1.0),
        UINT64_C(0xbc90000000000000));
    if (!pf_ssbm_native_arithmetic_configure(PF_SSBM_ARITHMETIC_SEPARATE) ||
        pf_ssbm_native_arithmetic_configure(2) ||
        pf_ssbm_native_arithmetic_current() != PF_SSBM_ARITHMETIC_SEPARATE) return 1;
    failed |= expect_bits("Slippi binary32 double-rounding boundary",
        PF_SlippiMulAddF32(0x1.000002p-12F, 0x1.fffffcp-13F, 0x1.000002p0F),
        UINT32_C(0x3f800002));

    /* The product is exactly 1 - 2^-54. Binary64 rounds it to 1 before
     * cancellation; true hardware FMA instead returns -2^-54. */
    failed |= expect_double_bits("Slippi binary64 product rounding",
        PF_SlippiMulAddF64(0x1.0000002p0, 0x1.ffffffcp-1, -1.0),
        UINT64_C(0));
    failed |= expect_double_bits("Slippi binary64 negative product rounding",
        PF_SlippiMulAddF64(-0x1.0000002p0, 0x1.ffffffcp-1, 1.0),
        UINT64_C(0));

    const f32 mario_up_b_y_term =
        PF_MSLFloatFromBits(UINT32_C(0x40263c10)) *
        PF_MSLFloatFromBits(UINT32_C(0x3dc0bbdd));
    const f32 mario_up_b_rotated_x =
        PF_SlippiMulAddF32(PF_MSLFloatFromBits(UINT32_C(0xbfa4a768)),
             PF_MSLFloatFromBits(UINT32_C(0x3f7edd26)),
             -mario_up_b_y_term);

    failed |= expect_bits(
        "Gekko fnmsubs knockback decay",
        PF_SlippiMulAddF32(-PF_MSLFloatFromBits(UINT32_C(0x3d50e560)),
             PF_MSLFloatFromBits(UINT32_C(0x3e9a6951)),
             PF_MSLFloatFromBits(UINT32_C(0x3f746348))),
        UINT32_C(0x3f707349));

    failed |= expect_bits(
        "Gekko fmadds attacker shield pushback",
        PF_SlippiMulAddF32(PF_MSLFloatFromBits(UINT32_C(0x41700000)),
             PF_MSLFloatFromBits(UINT32_C(0x3d8f5c29)),
             PF_MSLFloatFromBits(UINT32_C(0x3ca3d70a))),
        UINT32_C(0x3f88f5c3));

    failed |= expect_bits(
        "Gekko fmadds ordinary knockback shell",
        PF_SlippiMulAddF32(PF_MSLFloatFromBits(UINT32_C(0x3fb33333)),
             PF_MSLFloatFromBits(UINT32_C(0x4154cccd)),
             PF_MSLFloatFromBits(UINT32_C(0x41900000))),
        UINT32_C(0x42127ae1));

    failed |= expect_bits(
        "Gekko fnmsubs Falco Fire Bird reverse acceleration",
        PF_SlippiMulAddF32(-PF_MSLFloatFromBits(UINT32_C(0x3e2e147b)),
             PF_MSLFloatFromBits(UINT32_C(0x3f3838f3)),
             PF_MSLFloatFromBits(UINT32_C(0x3f88531e))),
        UINT32_C(0x3f7154df));

    {
        const f32 dash_scaled_velocity =
            PF_MSLFloatFromBits(UINT32_C(0x3f8b8522)) *
            PF_MSLFloatFromBits(UINT32_C(0x3f400000));
        failed |= expect_bits(
            "Gekko fmadds dash-exit ground friction",
            PF_SlippiMulAddF32(-dash_scaled_velocity,
                 PF_MSLFloatFromBits(UINT32_C(0x3fc00000)),
                 PF_MSLFloatFromBits(UINT32_C(0x3f8b8522))),
            UINT32_C(0xbe0b8522));
    }

    {
        const f32 guard_asdi_scaled_input =
            PF_MSLFloatFromBits(UINT32_C(0x3f366666)) *
            PF_MSLFloatFromBits(UINT32_C(0x40400000));
        const f32 guard_asdi_scale =
            PF_MSLFloatFromBits(UINT32_C(0x3f28f5c3)) *
            guard_asdi_scaled_input;
        failed |= expect_bits(
            "Gekko fmadds guard ASDI position",
            PF_SlippiMulAddF32(PF_MSLFloatFromBits(UINT32_C(0x3f7fffff)),
                 guard_asdi_scale,
                 PF_MSLFloatFromBits(UINT32_C(0x3ff5fa8e))),
            UINT32_C(0x40554701));
    }

    failed |= expect_bits("Gekko fmsubs Mario up-B rotation",
                          mario_up_b_rotated_x,
                          UINT32_C(0xbfc33619));
    failed |= expect_bits(
        "Mario up-B post-rotation scale",
        mario_up_b_rotated_x *
            PF_MSLFloatFromBits(UINT32_C(0x3f733333)),
        UINT32_C(0xbfb97364));

    failed |= expect_bits("smaller dividend", PF_MSLFmodf(3.5F, 4.0F),
                          UINT32_C(0x40600000));
    failed |= expect_bits("positive", PF_MSLFmodf(7.5F, 2.0F),
                          UINT32_C(0x3fc00000));
    failed |= expect_bits("negative dividend", PF_MSLFmodf(-7.5F, 2.0F),
                          UINT32_C(0xbfc00000));
    failed |= expect_bits("negative divisor", PF_MSLFmodf(7.5F, -2.0F),
                          UINT32_C(0x3fc00000));
    failed |= expect_bits("exact", PF_MSLFmodf(6.0F, 2.0F),
                          UINT32_C(0x00000000));

    /* DOL fnmsubs rounding witness; separate float multiply/subtract is zero. */
    failed |= expect_bits(
        "fused cancellation",
        PF_MSLFmodf(PF_MSLFloatFromBits(UINT32_C(0x47d21631)),
                    PF_MSLFloatFromBits(UINT32_C(0xae87382a))),
        UINT32_C(0xbad45c00));

    failed |= expect_s64("positive truncate", PF_MSLTruncS64FromF32(7.75F),
                         INT64_C(7));
    failed |= expect_s64("negative truncate", PF_MSLTruncS64FromF32(-7.75F),
                         INT64_C(-7));
    failed |= expect_s64(
        "positive saturation",
        PF_MSLTruncS64FromF32(PF_MSLFloatFromBits(UINT32_C(0x7f800000))),
        INT64_MAX);
    failed |= expect_s64(
        "negative saturation",
        PF_MSLTruncS64FromF32(PF_MSLFloatFromBits(UINT32_C(0xff800000))),
        INT64_MIN);

    failed |= expect_bits("sqrt zero", PF_MSLSqrtf(0.0F),
                          UINT32_C(0x00000000));
    failed |= expect_bits("sqrt negative zero", PF_MSLSqrtf(-0.0F),
                          UINT32_C(0x80000000));
    failed |= expect_bits("sqrt two", PF_MSLSqrtf(2.0F),
                          UINT32_C(0x3fb504f3));
    failed |= expect_bits("sqrt minimum subnormal",
                          PF_MSLSqrtf(PF_MSLFloatFromBits(UINT32_C(1))),
                          UINT32_C(0x1a3504f3));
    failed |= expect_bits("sqrt negative passthrough", PF_MSLSqrtf(-1.0F),
                          UINT32_C(0xbf800000));
    failed |= expect_bits(
        "sqrt nan payload",
        PF_MSLSqrtf(PF_MSLFloatFromBits(UINT32_C(0x7fc12345))),
        UINT32_C(0x7fc12345));
    failed |= expect_double_bits("sqrt two three refinements",
                                 PF_MSLRsqrtEstimate(2.0F, 3),
                                 UINT64_C(0x3fe6a09e667f3bcd));
    failed |= expect_double_bits("sqrt two accurate refinement",
                                 PF_MSLRsqrtEstimate(2.0F, 4),
                                 UINT64_C(0x3fe6a09e667f3bcc));

    if (failed != 0) {
        return 1;
    }
    (void) puts("native-msl-math=pass fma_vectors=7 fmodf_vectors=6 "
                "conversion_vectors=5 sqrt_vectors=8");
    return 0;
}
