#include "native_numeric.h"

#include <stdio.h>

static int expect_u16(const char* label, u16 actual, u16 expected)
{
    if (actual != expected) {
        fprintf(stderr, "%s: expected %u, got %u\n", label, expected, actual);
        return 1;
    }
    return 0;
}

int main(void)
{
    int failed = 0;

    failed |= expect_u16("negative clamp", PF_QuantizeU16Scale0(-1.0F), 0);
    failed |= expect_u16("zero", PF_QuantizeU16Scale0(0.0F), 0);
    failed |= expect_u16("fraction below one",
                         PF_QuantizeU16Scale0(0.999F), 0);
    failed |= expect_u16("truncate", PF_QuantizeU16Scale0(1.999F), 1);
    failed |= expect_u16("middle truncate",
                         PF_QuantizeU16Scale0(32768.75F), 32768);
    failed |= expect_u16("largest unsaturated truncate",
                         PF_QuantizeU16Scale0(65534.75F), 65534);
    failed |= expect_u16("upper endpoint",
                         PF_QuantizeU16Scale0(65535.0F), 65535);
    failed |= expect_u16("upper clamp", PF_QuantizeU16Scale0(3.4028235e38F),
                         65535);

    if (failed != 0) {
        return 1;
    }
    puts("native-quantize=pass");
    return 0;
}
