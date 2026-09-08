/* glibc and the imported SDK declare incompatible legacy __assert APIs.
 * Only the host declaration is renamed; assert() uses __assert_fail. */
#define __assert ssbmsim_unused_libc_assert
#include <assert.h>
#undef __assert
#include <stddef.h>
#include <stdio.h>

#include <melee/ft/types.h>
#include <melee/gm/types.h>

struct NativeDmgResult {
    float dir;
    int angle;
    int hurt_height;
    float kb;
    Vec3 pos;
    u32 element;
    int sfx_severity;
    HSD_GObj* source;
    float damage;
};

#define FIGHTER_DMG_RELATIVE(field, base)                                   \
    (offsetof(Fighter, dmg.field) - offsetof(Fighter, dmg.base))

_Static_assert(offsetof(struct NativeDmgResult, dir) ==
                   FIGHTER_DMG_RELATIVE(x1870, x1870),
               "secondary damage direction layout");
_Static_assert(offsetof(struct NativeDmgResult, angle) ==
                   FIGHTER_DMG_RELATIVE(x1874, x1870),
               "secondary damage angle layout");
_Static_assert(offsetof(struct NativeDmgResult, hurt_height) ==
                   FIGHTER_DMG_RELATIVE(x1878, x1870),
               "secondary damage hurt-height layout");
_Static_assert(offsetof(struct NativeDmgResult, kb) ==
                   FIGHTER_DMG_RELATIVE(x187c, x1870),
               "secondary damage knockback layout");
_Static_assert(offsetof(struct NativeDmgResult, pos) ==
                   FIGHTER_DMG_RELATIVE(x1880, x1870),
               "secondary damage position layout");
_Static_assert(offsetof(struct NativeDmgResult, element) ==
                   FIGHTER_DMG_RELATIVE(x188c, x1870),
               "secondary damage element layout");
_Static_assert(offsetof(struct NativeDmgResult, sfx_severity) ==
                   FIGHTER_DMG_RELATIVE(x1890, x1870),
               "secondary damage sound layout");
_Static_assert(offsetof(struct NativeDmgResult, source) ==
                   FIGHTER_DMG_RELATIVE(x1894, x1870),
               "secondary damage source layout");
_Static_assert(offsetof(struct NativeDmgResult, damage) ==
                   FIGHTER_DMG_RELATIVE(x1898, x1870),
               "secondary damage amount layout");
_Static_assert(sizeof(struct NativeDmgResult) ==
                   FIGHTER_DMG_RELATIVE(x189C_unk_num_frames, x1870),
               "secondary damage result extent");

_Static_assert(offsetof(struct NativeDmgResult, dir) ==
                   FIGHTER_DMG_RELATIVE(facing_dir_1, facing_dir_1),
               "primary damage direction layout");
_Static_assert(offsetof(struct NativeDmgResult, source) ==
                   FIGHTER_DMG_RELATIVE(x1868_source, facing_dir_1),
               "primary damage source layout");
_Static_assert(sizeof(struct NativeDmgResult) ==
                   FIGHTER_DMG_RELATIVE(x1870, facing_dir_1),
               "primary damage result extent");
_Static_assert(sizeof(((ftCommonData*) 0)->x23C) == sizeof(s32),
               "damage-fly-roll threshold type");
_Static_assert(sizeof(((ftCommonData*) 0)->x5EC) == sizeof(u32),
               "damage timer type");
_Static_assert(sizeof(((FtSFX*) 0)->x1C) == sizeof(FtSFXArr*),
               "damage-fall sound-array source type");
_Static_assert(sizeof(((Fighter*) 0)->dmg.x190C) == sizeof(FtSFXArr*),
               "damage-fall sound-array retained type");
_Static_assert(sizeof(((UnkAllstarData*) 0)->x76) == 26,
               "All-Star character sentinel span must contain 26 bytes");
_Static_assert(offsetof(UnkAllstarData, x90) == 0x90,
               "All-Star sentinel span must preserve the x90 offset");

int main(void)
{
    Fighter fighter = { 0 };
    HSD_GObj* source = (HSD_GObj*) &fighter;

    fighter.dmg.x1894 = source;
    assert(fighter.dmg.x1894 == source);
    puts("native-ft-damage-layout=pass");
    return 0;
}
