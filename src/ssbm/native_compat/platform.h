#ifndef PF_SSBM_NATIVE_PLATFORM_H
#define PF_SSBM_NATIVE_PLATFORM_H

#include <dolphin/types.h>

typedef int enum_t;

#if defined(_MSC_VER) && !defined(__clang__)
typedef ptrdiff_t ssize_t;
#endif

typedef void (*Event)(void);
typedef bool (*Predicate)(void);

#define ASM

#if defined(__clang__) || defined(__GNUC__)
#define UNUSED __attribute__((unused))
#define ATTRIBUTE_NORETURN __attribute__((noreturn))
#else
#define UNUSED
#define ATTRIBUTE_NORETURN
#endif

#define SECTION_INIT
#define SECTION_CTORS
#define SECTION_DTORS
#define ATTRIBUTE_RESTRICT
#ifndef AT_ADDRESS
#define AT_ADDRESS(address)
#endif
#define SDATA
#define DATA
#define WEAK

#define U8_MAX UINT8_MAX
#define U16_MAX UINT16_MAX
#define U32_MAX UINT32_MAX
#define S8_MAX INT8_MAX
#define S16_MAX INT16_MAX
#define S32_MAX INT32_MAX
#define F32_MAX 3.4028235e38F

#define SQ(value) ((value) * (value))
#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define MIN(left, right) (((left) < (right)) ? (left) : (right))
#define MAX(left, right) (((left) > (right)) ? (left) : (right))
/*
 * The native runtime is intentionally i686 so gameplay structures retain the
 * original 32-bit pointer ABI.  Silencing the decomp's layout assertions would
 * allow a source-complete build whose field accesses are still wrong at run
 * time, so keep every upstream size/offset contract live.
 */
#define STATIC_ASSERT(condition) _Static_assert((condition), #condition)
#define ASSERT_SIZE(expression, size)                                        \
    _Static_assert(sizeof(expression) == (size), #expression)

#define RETURN_IF(condition)                                                   \
    do {                                                                       \
        if (condition) {                                                       \
            return;                                                            \
        }                                                                      \
    } while (0)

#define M_TAU 6.283185307179586
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#define M_PI_2 (M_PI / 2.0)
#define M_PI_3 (M_PI / 3.0)
#define M_PI_F 3.14159265358979323846F
#define M_TAU_F 6.283185307179586F
#define M_PI_2_F (M_PI_F / 2.0F)
#define M_PI_3_F (M_PI_F / 3.0F)
#define M_PI_L 3.14159265358979323846L
#define M_TAU_L 6.283185307179586L
#define M_PI_2_L (M_PI_L / 2.0L)
#define SIGNF(value) ((value) > 0.0F ? 1.0F : -1.0F)
#define FLT_EPSILON 1.00000001335e-10F
#define ABS(value) ((value) < 0 ? -(value) : (value))

#endif
