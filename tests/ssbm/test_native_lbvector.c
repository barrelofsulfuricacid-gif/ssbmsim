#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <dolphin/mtx.h>
#include <melee/lb/lbvector.h>

static float float_from_bits(uint32_t bits)
{
    float value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static uint32_t float_bits(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

int main(void)
{
    Vec3 flat_floor = {
        -0.0F,
        float_from_bits(UINT32_C(0x411A8AE0)),
        0.0F,
    };
    Vec3 flat_floor_unit;
    Vec3 velocity = {
        float_from_bits(UINT32_C(0x3FD7528E)),
        float_from_bits(UINT32_C(0x3F2467AC)),
        0.0F,
    };
    Vec3 wall_normal = {
        float_from_bits(UINT32_C(0xBF5E6831)),
        float_from_bits(UINT32_C(0xBEFD8B39)),
        0.0F,
    };

    PSVECNormalize(&flat_floor, &flat_floor_unit);
    if (float_bits(flat_floor_unit.x) != UINT32_C(0x80000000) ||
        float_bits(flat_floor_unit.y) != UINT32_C(0x3F800000) ||
        float_bits(flat_floor_unit.z) != 0U)
    {
        fprintf(stderr,
                "native-lbvector=flat-floor-normalize-fail "
                "bits=%08x,%08x,%08x\n",
                float_bits(flat_floor_unit.x), float_bits(flat_floor_unit.y),
                float_bits(flat_floor_unit.z));
        return 1;
    }

    {
        /* Captured Dream Land wall edge; Slippi bookends give these exact
         * normalized components before the first divergent wall bounce.
         * Exercise the real SDK provider and its in-place call contract. */
        Vec3 sloped = {
            float_from_bits(UINT32_C(0x4130ced9)),
            float_from_bits(UINT32_C(0xbf6eb200)),
            0.0F,
        };
        PSVECNormalize(&sloped, &sloped);
        if (float_bits(sloped.x) != UINT32_C(0x3f7f17f2) ||
            float_bits(sloped.y) != UINT32_C(0xbdac30ff) ||
            float_bits(sloped.z) != 0U)
        {
            fprintf(stderr, "native-lbvector=sloped-normalize-fail "
                    "bits=%08x,%08x,%08x\n", float_bits(sloped.x),
                    float_bits(sloped.y), float_bits(sloped.z));
            return 1;
        }
    }

    lbVector_Mirror(&velocity, &wall_normal);
    if (float_bits(velocity.x) != UINT32_C(0xBFB47297) ||
        float_bits(velocity.y) != UINT32_C(0xBF8F62E8) ||
        float_bits(velocity.z) != 0U)
    {
        fprintf(stderr,
                "native-lbvector=mirror-fusion-fail bits=%08x,%08x,%08x\n",
                float_bits(velocity.x), float_bits(velocity.y),
                float_bits(velocity.z));
        return 1;
    }

    puts("native-lbvector=pass mirror-fmadds=3 witness=wall-reflect");
    puts("native-lbvector=pass witness=dream-land-flat-floor");
    return 0;
}
