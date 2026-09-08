#include "ft/types.h"

#include <stdint.h>
#include <stdio.h>

static int fail(const Fighter* fighter, const char* check)
{
    fprintf(stderr,
            "native-fighter-anim-flags-layout=fail check=%s raw=%08x "
            "x7=%u x0=%u kind=%u selection=%u named=%u%u%u%u%u%u%u%u\n",
            check, (uint32_t) fighter->x594_s32,
            (unsigned) fighter->x596_bits.x7,
            (unsigned) fighter->x596_bits.x0,
            (unsigned) fighter->x597_bits,
            (unsigned) fighter->x594_bits,
            (unsigned) fighter->x594_b0,
            (unsigned) fighter->x594_b1_loop,
            (unsigned) fighter->x594_b2,
            (unsigned) fighter->x594_b3,
            (unsigned) fighter->x594_b4,
            (unsigned) fighter->x594_b5,
            (unsigned) fighter->x594_b6,
            (unsigned) fighter->x594_b7);
    return 1;
}

int main(void)
{
    Fighter fighter = { 0 };

    /*
     * GALE01 0x80069C48/0x80069C50 applies (lhz(fp+596) >> 6) & 7.
     * The low six bits remain the FighterKind field, not the bone index.
     */
    fighter.x594_s32 = (int32_t) UINT32_C(0x40000012);
    if (fighter.x596_bits.x7 != 0U || fighter.x597_bits != 0x12U ||
        fighter.x596_bits.x0 != 0U || !fighter.x594_b1_loop) {
        return fail(&fighter, "real-walkmiddle-flags");
    }

    fighter.x594_s32 = (int32_t) UINT32_C(0x00000092);
    if (fighter.x596_bits.x7 != 2U || fighter.x597_bits != 0x12U) {
        return fail(&fighter, "transition-bone-index");
    }

    fighter.x594_s32 = (int32_t) UINT32_C(0xFF3FFFFF);
    if (!fighter.x594_b0 || !fighter.x594_b1_loop ||
        !fighter.x594_b2 || !fighter.x594_b3 || !fighter.x594_b4 ||
        !fighter.x594_b5 || !fighter.x594_b6 || !fighter.x594_b7 ||
        fighter.x594_bits != UINT32_C(0x1FFF) ||
        fighter.x597_bits != UINT32_C(0x3F) ||
        fighter.x596_bits.x7 != 7U) {
        return fail(&fighter, "all-read-accessors");
    }

    fighter.x594_s32 = 0;
    fighter.x597_bits = UINT32_C(0x2D);
    fighter.x596_bits.x7 = 5U;
    fighter.x596_bits.x0 = UINT32_C(0x55);
    if ((uint32_t) fighter.x594_s32 != UINT32_C(0x0000AB6D)) {
        return fail(&fighter, "cross-byte-write-accessors");
    }

    puts("native-fighter-anim-flags-layout=pass accessors=13 x7-raw=00000140");
    return 0;
}
