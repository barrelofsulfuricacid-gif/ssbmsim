#include "lb/lbcommand.h"
#include "lb/types.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef union RawCommandWord {
    uint32_t alignment;
    unsigned char bytes[4];
} RawCommandWord;

static RawCommandWord raw_word(uint32_t value)
{
    RawCommandWord result;
    result.bytes[0] = (unsigned char) (value >> 24U);
    result.bytes[1] = (unsigned char) (value >> 16U);
    result.bytes[2] = (unsigned char) (value >> 8U);
    result.bytes[3] = (unsigned char) value;
    return result;
}

int main(void)
{
    RawCommandWord script[] = {
        raw_word((3U << 26U) | 3U),
        raw_word((1U << 26U) | 2U),
        raw_word(4U << 26U),
        raw_word(0U),
    };
    CommandInfo info;
    union CmdUnion* const loop_body = (union CmdUnion*) &script[1];
    union CmdUnion* const execute_loop = (union CmdUnion*) &script[2];
    union CmdUnion* const after_loop = (union CmdUnion*) &script[3];

    memset(&info, 0, sizeof(info));
    info.u = (union CmdUnion*) &script[0];
    Command_03(&info);
    if (info.loop_count != 2U || info.u != loop_body ||
        info.event_return[0] != loop_body ||
        (uint32_t) (uintptr_t) info.event_return[1] != 3U) {
        fprintf(stderr,
                "native-command-loop=fail phase=set-loop depth=%u u=%p "
                "return=%p count=%u\n",
                info.loop_count, (void*) info.u,
                (void*) info.event_return[0],
                (uint32_t) (uintptr_t) info.event_return[1]);
        return 1;
    }

    info.u = execute_loop;
    Command_04(&info);
    if (info.loop_count != 2U || info.u != loop_body ||
        (uint32_t) (uintptr_t) info.event_return[1] != 2U) {
        fprintf(stderr,
                "native-command-loop=fail phase=first-execute depth=%u "
                "u=%p count=%u\n",
                info.loop_count, (void*) info.u,
                (uint32_t) (uintptr_t) info.event_return[1]);
        return 1;
    }

    info.u = execute_loop;
    Command_04(&info);
    if (info.loop_count != 2U || info.u != loop_body ||
        (uint32_t) (uintptr_t) info.event_return[1] != 1U) {
        fprintf(stderr,
                "native-command-loop=fail phase=second-execute depth=%u "
                "u=%p count=%u\n",
                info.loop_count, (void*) info.u,
                (uint32_t) (uintptr_t) info.event_return[1]);
        return 1;
    }

    info.u = execute_loop;
    Command_04(&info);
    if (info.loop_count != 0U || info.u != after_loop ||
        (uint32_t) (uintptr_t) info.event_return[1] != 0U) {
        fprintf(stderr,
                "native-command-loop=fail phase=final-execute depth=%u "
                "u=%p count=%u\n",
                info.loop_count, (void*) info.u,
                (uint32_t) (uintptr_t) info.event_return[1]);
        return 1;
    }

    puts("native-command-loop=pass iterations=3 return-targets=2");
    return 0;
}
