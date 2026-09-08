#ifndef PF_SSBM_NATIVE_TARGET_BOOL_H
#define PF_SSBM_NATIVE_TARGET_BOOL_H

/*
 * GALE01's MSL stdbool.h defines bool as signed int.  Host C17 stdbool.h
 * instead maps it to _Bool and silently narrows nonzero gameplay values to 1.
 * Force this header only for imported Melee/Aurora translation units; native
 * host-provider APIs retain the platform C/C++ bool ABI.
 */
#ifndef __cplusplus
#include <stdbool.h>
#undef bool
#undef true
#undef false
#define bool int
#define true 1
#define false 0
_Static_assert(sizeof(bool) == 4, "GALE01 bool must remain 32-bit");
#endif

#endif
