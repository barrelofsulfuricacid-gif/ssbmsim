#include "native_memory.h"

#include "baselib/memory.h"

#include <stdint.h>

typedef struct NativeStartupArena {
    uintptr_t begin;
    uintptr_t current;
    uintptr_t end;
    size_t rejected_allocations;
    int frozen;
} NativeStartupArena;

static NativeStartupArena startup_arena;

static uintptr_t align_up(uintptr_t value, size_t alignment)
{
    const uintptr_t mask = (uintptr_t) alignment - 1U;
    if (value > UINTPTR_MAX - mask) {
        return 0;
    }
    return (value + mask) & ~mask;
}

void pf_hsd_startup_arena_bind(void* storage, size_t bytes)
{
    const uintptr_t begin = (uintptr_t) storage;
    if (storage == NULL || bytes == 0 || begin > UINTPTR_MAX - bytes) {
        startup_arena = (NativeStartupArena) { 0, 0, 0, 0, 1 };
        return;
    }
    startup_arena = (NativeStartupArena) {
        .begin = begin,
        .current = begin,
        .end = begin + bytes,
        .rejected_allocations = 0,
        .frozen = 0,
    };
}

void pf_hsd_startup_arena_freeze(void)
{
    startup_arena.frozen = 1;
}

size_t pf_hsd_startup_arena_bytes_used(void)
{
    return (size_t) (startup_arena.current - startup_arena.begin);
}

size_t pf_hsd_startup_arena_bytes_remaining(void)
{
    return (size_t) (startup_arena.end - startup_arena.current);
}

size_t pf_hsd_startup_arena_rejected_allocations(void)
{
    return startup_arena.rejected_allocations;
}

void* HSD_MemAlloc(ssize_t size)
{
    const size_t alignment = _Alignof(max_align_t);
    uintptr_t result;
    size_t bytes;

    if (size <= 0) {
        return NULL;
    }
    if (startup_arena.frozen != 0) {
        startup_arena.rejected_allocations += 1;
        return NULL;
    }
    bytes = (size_t) size;
    result = align_up(startup_arena.current, alignment);
    if (result == 0 || result > startup_arena.end ||
        bytes > (size_t) (startup_arena.end - result)) {
        startup_arena.rejected_allocations += 1;
        return NULL;
    }
    startup_arena.current = result + bytes;
    return (void*) result;
}

void HSD_Free(void* ptr)
{
    const uintptr_t address = (uintptr_t) ptr;

    if (ptr == NULL) {
        return;
    }
    if (address < startup_arena.begin || address >= startup_arena.current) {
        startup_arena.rejected_allocations += 1;
        return;
    }

    /* The native match arena has whole-match lifetime and is never reused
     * after construction. Source destructors still run before this ownership
     * release marker, but reclaiming individual blocks would add allocator
     * state that step() is deliberately forbidden to depend on. */
}

void DCFlushRange(void* address, u32 bytes)
{
    (void) address;
    (void) bytes;
}

void DCInvalidateRange(void* address, u32 bytes)
{
    (void) address;
    (void) bytes;
}
