#include "baselib/debug.h"

#include <stdlib.h>

/* Diagnostic text has no simulation-visible state. Keeping the symbol local
 * to the native host also prevents ordinary fallback/reporting paths from
 * dispatching through an absent console backend. */
void OSReport(const char* format, ...)
{
    (void) format;
}

ATTRIBUTE_NORETURN void __assert(char* file, u32 line, char* condition)
{
    (void) file;
    (void) line;
    (void) condition;
    abort();
}
