#include "native_objalloc.h"

#include "baselib/objalloc.h"

#include <stdint.h>
#include <string.h>

typedef struct NativeObjArena {
    uintptr_t begin;
    uintptr_t current;
    uintptr_t end;
} NativeObjArena;

static NativeObjArena obj_arena;
static HSD_ObjAllocData* alloc_datas;

static int is_power_of_two(size_t value)
{
    return value != 0 && (value & (value - 1)) == 0;
}

static uintptr_t align_up(uintptr_t value, size_t alignment)
{
    const uintptr_t mask = (uintptr_t) alignment - 1U;
    if (value > UINTPTR_MAX - mask) {
        return 0;
    }
    return (value + mask) & ~mask;
}

void pf_hsd_obj_arena_bind(void* storage, size_t bytes)
{
    const uintptr_t begin = (uintptr_t) storage;
    if (storage == NULL || bytes == 0 || begin > UINTPTR_MAX - bytes) {
        obj_arena = (NativeObjArena) { 0, 0, 0 };
        return;
    }
    obj_arena = (NativeObjArena) { begin, begin, begin + bytes };
}

size_t pf_hsd_obj_arena_bytes_used(void)
{
    return (size_t) (obj_arena.current - obj_arena.begin);
}

size_t pf_hsd_obj_arena_bytes_remaining(void)
{
    return (size_t) (obj_arena.end - obj_arena.current);
}

int pf_hsd_obj_pool_prepare(
    HSD_ObjAllocData* data,
    size_t object_bytes,
    size_t alignment,
    uint32_t capacity)
{
    if (alignment > UINT32_MAX) {
        return 0;
    }
    HSD_ObjAllocInit(data, object_bytes, (u32) alignment);
    return HSD_ObjAllocAddFree(data, capacity) == (s32) capacity;
}

uint32_t pf_hsd_obj_pool_used(const HSD_ObjAllocData* data)
{
    return data == NULL ? 0 : data->used;
}

void HSD_ObjSetHeap(u32 size, void* ptr)
{
    pf_hsd_obj_arena_bind(ptr, size);
}

s32 HSD_ObjAllocAddFree(HSD_ObjAllocData* data, u32 num)
{
    size_t alignment;
    uintptr_t pool_begin;
    size_t available;
    size_t requested;
    size_t pool_bytes;
    u32 actual;
    u32 index;

    HSD_ASSERT(0xEE, data != NULL);
    if (data == NULL || num == 0 || data->size < sizeof(HSD_ObjAllocLink)) {
        return 0;
    }
    alignment = (size_t) data->align + 1U;
    if (alignment < _Alignof(HSD_ObjAllocLink)) {
        alignment = _Alignof(HSD_ObjAllocLink);
    }
    if (!is_power_of_two(alignment) || num > SIZE_MAX / data->size) {
        return 0;
    }
    pool_begin = align_up(obj_arena.current, alignment);
    if (pool_begin == 0 || pool_begin > obj_arena.end) {
        return 0;
    }
    available = (size_t) (obj_arena.end - pool_begin);
    requested = (size_t) data->size * num;
    pool_bytes = requested < available ? requested : available;
    actual = (u32) (pool_bytes / data->size);
    if (actual == 0) {
        return 0;
    }
    pool_bytes = (size_t) data->size * actual;
    obj_arena.current = pool_begin + pool_bytes;

    for (index = 0; index + 1U < actual; ++index) {
        HSD_ObjAllocLink* current =
            (HSD_ObjAllocLink*) (pool_begin + (size_t) data->size * index);
        current->next = (HSD_ObjAllocLink*) (
            pool_begin + (size_t) data->size * (index + 1U));
    }
    {
        HSD_ObjAllocLink* last = (HSD_ObjAllocLink*) (
            pool_begin + (size_t) data->size * (actual - 1U));
        last->next = data->freehead;
    }
    data->freehead = (HSD_ObjAllocLink*) pool_begin;
    data->free += actual;
    return (s32) actual;
}

void* HSD_ObjAlloc(HSD_ObjAllocData* data)
{
    HSD_ObjAllocLink* result;

    HSD_ASSERT(0x128, data != NULL);
    if (data == NULL ||
        (data->num_limit_flag != 0 && data->used >= data->num_limit)) {
        return NULL;
    }
    if (data->heap_limit_flag != 0) {
        const size_t remaining = pf_hsd_obj_arena_bytes_remaining();
        if (data->heap_limit_num == (u32) -1) {
            if (remaining <= data->heap_limit_size) {
                data->heap_limit_num = data->used + data->free;
            }
        } else if (remaining > data->heap_limit_size) {
            data->heap_limit_num = (u32) -1;
        }
        if (data->used >= data->heap_limit_num) {
            return NULL;
        }
    }
    if (data->free == 0 && HSD_ObjAllocAddFree(data, 1) == 0) {
        return NULL;
    }
    result = data->freehead;
    data->freehead = result->next;
    data->used += 1;
    data->free -= 1;
    if (data->used > data->peak) {
        data->peak = data->used;
    }
    return result;
}

void HSD_ObjFree(HSD_ObjAllocData* data, void* obj)
{
    HSD_ObjAllocLink* link = obj;

    HSD_ASSERT(0x15D, data != NULL);
    HSD_ASSERT(0x15E, obj != NULL);
    if (data == NULL || obj == NULL) {
        return;
    }
    link->next = data->freehead;
    data->freehead = link;
    data->free += 1;
    data->used -= 1;
}

static void remove_allocation_data(HSD_ObjAllocData* data)
{
    HSD_ObjAllocData** current = &alloc_datas;
    while (*current != NULL) {
        if (*current == data) {
            *current = (*current)->next;
        } else {
            current = &(*current)->next;
        }
    }
}

void HSD_ObjAllocInit(HSD_ObjAllocData* data, size_t size, u32 align)
{
    size_t alignment = align;

    HSD_ASSERT(0x185, data != NULL);
    if (data == NULL) {
        return;
    }
    remove_allocation_data(data);
    memset(data, 0, sizeof(*data));
    if (alignment < _Alignof(HSD_ObjAllocLink)) {
        alignment = _Alignof(HSD_ObjAllocLink);
    }
    HSD_ASSERT(0x18A, is_power_of_two(alignment));
    HSD_ASSERT(0x18B, size <= UINT32_MAX);
    data->num_limit = (u32) -1;
    data->heap_limit_num = (u32) -1;
    data->align = (u32) alignment - 1U;
    data->size = (u32) ((size + data->align) & ~(size_t) data->align);
    data->next = alloc_datas;
    alloc_datas = data;
}

void _HSD_ObjAllocForgetMemory(void* low, void* high)
{
    (void) low;
    (void) high;
    alloc_datas = NULL;
    obj_arena = (NativeObjArena) { 0, 0, 0 };
}
