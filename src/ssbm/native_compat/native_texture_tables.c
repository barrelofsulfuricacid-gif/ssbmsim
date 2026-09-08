#include "native_texture_tables.h"

#include <stdint.h>
#include <string.h>

/* Texture objects have fixed startup-reserved slots, each permanently owning
 * its palette pointer table. Cover the full u16 count domain and terminator.
 * The source class allocator retains its live/peak counters and constructors;
 * only its raw storage for HSD_TObj comes from these preallocated slots.
 * Reservation is 256 MiB for tables on i686, plus the texture objects.
 */
enum { texture_slots = 1024, palette_entries = UINT16_MAX + 1U };
static HSD_TObj objects[texture_slots];
static HSD_Tlut* tables[texture_slots][palette_entries];
static unsigned int next_free[texture_slots];
static unsigned char active[texture_slots];
static unsigned int free_head = texture_slots;

static unsigned int find_object(const void* object)
{
    const uintptr_t address = (uintptr_t) object;
    const uintptr_t begin = (uintptr_t) objects;
    uintptr_t offset;
    if (address < begin || address - begin >= sizeof(objects)) {
        return texture_slots;
    }
    offset = address - begin;
    if (offset % sizeof(HSD_TObj) != 0) {
        return texture_slots;
    }
    return (unsigned int) (offset / sizeof(HSD_TObj));
}

void pf_hsd_texture_tables_reset(void)
{
    unsigned int index;
    memset(objects, 0, sizeof(objects));
    memset(tables, 0, sizeof(tables));
    memset(active, 0, sizeof(active));
    for (index = 0; index < texture_slots; ++index) {
        next_free[index] = index + 1U;
    }
    free_head = 0;
}

HSD_Class* pf_hsd_texture_object_take(int bytes)
{
    unsigned int index;
    if (bytes != (int) sizeof(HSD_TObj) || free_head == texture_slots) {
        return NULL;
    }
    index = free_head;
    free_head = next_free[index];
    active[index] = 1;
    return (HSD_Class*) &objects[index];
}

int pf_hsd_texture_object_return(HSD_Class* object)
{
    const unsigned int index = find_object(object);
    if (index == texture_slots || active[index] == 0) {
        return 0;
    }
    active[index] = 0;
    next_free[index] = free_head;
    free_head = index;
    return 1;
}

HSD_Tlut** pf_hsd_texture_table(HSD_TObj* object, unsigned int count)
{
    const unsigned int index = find_object(object);
    if (count > UINT16_MAX || index == texture_slots || active[index] == 0) {
        return NULL;
    }
    return tables[index];
}

int pf_hsd_texture_table_release(HSD_TObj* object)
{
    const unsigned int index = find_object(object);
    return index != texture_slots && active[index] != 0 &&
        object->tluttbl == tables[index];
}
