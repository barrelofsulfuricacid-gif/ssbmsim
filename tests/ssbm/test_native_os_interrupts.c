#include <assert.h>
#include <stdio.h>

int OSDisableInterrupts(void);
int OSRestoreInterrupts(int level);

int main(void)
{
    assert(OSDisableInterrupts() == 1);
    assert(OSDisableInterrupts() == 0);
    assert(OSRestoreInterrupts(0) == 0);
    assert(OSRestoreInterrupts(1) == 0);
    assert(OSDisableInterrupts() == 1);
    assert(OSRestoreInterrupts(1) == 0);
    puts("native-os-interrupts=pass nested=1 restore=1");
    return 0;
}
