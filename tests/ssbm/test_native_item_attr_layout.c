/* glibc and the imported SDK declare incompatible legacy __assert APIs.
 * Only the host declaration is renamed; assert() uses __assert_fail. */
#define __assert ssbmsim_unused_libc_assert
#include <assert.h>
#undef __assert
#include <stddef.h>
#include <stdio.h>

#include <melee/it/types.h>

_Static_assert(offsetof(struct ItemAttr, x3) == 2,
               "item attribute flag bytes must occupy offsets zero and one");
_Static_assert(offsetof(struct ItemAttr, x4_throw_speed_mul) == 4,
               "item attribute scalar payload must retain its source offset");
_Static_assert(sizeof(struct ItemAttr) == 0x84,
               "item attribute asset record must retain its source size");

static void clear_attr(struct ItemAttr* attr)
{
    unsigned char* bytes = (unsigned char*) attr;
    size_t index;

    for (index = 0; index < sizeof(*attr); ++index) {
        bytes[index] = 0;
    }
}

int main(void)
{
    struct ItemAttr attr;
    unsigned char* bytes = (unsigned char*) &attr;

    clear_attr(&attr);
    bytes[0] = 0x80;
    assert(attr.x0_is_heavy == 1);
    bytes[0] = 0x78;
    assert(attr.x0_78 == 0xF);
    bytes[0] = 0x07;
    assert(attr.x0_hold_kind == 0x7);

    bytes[0] = 0;
    bytes[1] = 0xC0;
    assert(attr.x1_1 == 0x3);
    bytes[1] = 0x20;
    assert(attr.x1_3 == 1);
    bytes[1] = 0x10;
    assert(attr.x1_4 == 1);
    bytes[1] = 0x08;
    assert(attr.x1_5 == 1);
    bytes[1] = 0x06;
    assert(attr.x1_67_cam_kind == 0x3);
    bytes[1] = 0x01;
    assert(attr.x1_8 == 1);

    bytes[0] = 0x01;
    bytes[1] = 0x28;
    assert(attr.x0_is_heavy == 0);
    assert(attr.x0_78 == 0);
    assert(attr.x0_hold_kind == 1);
    assert(attr.x1_3 == 1);
    assert(attr.x1_5 == 1);
    assert(attr.x1_1 == 0);
    assert(attr.x1_4 == 0);
    assert(attr.x1_67_cam_kind == 0);
    assert(attr.x1_8 == 0);

    puts("native-item-attr-layout=pass raw=01,28,00,00");
    return 0;
}
