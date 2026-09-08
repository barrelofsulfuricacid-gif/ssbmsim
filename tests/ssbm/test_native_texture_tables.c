#include "native_texture_tables.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define assert(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "texture table check failed at line %d: %s\n", __LINE__, #condition); \
        exit(1); \
    } \
} while (0)

int main(void)
{
    HSD_TObj foreign = { 0 };
    HSD_Tlut palette = { 0 };
    HSD_TObj* first;
    HSD_TObj* second;
    HSD_Tlut** row;
    HSD_Class* held[1024];
    unsigned int i;
    pf_hsd_texture_tables_reset();
    assert(pf_hsd_texture_object_take(1) == NULL);
    first = (HSD_TObj*) pf_hsd_texture_object_take((int) sizeof(HSD_TObj));
    second = (HSD_TObj*) pf_hsd_texture_object_take((int) sizeof(HSD_TObj));
    assert(first != NULL && second != NULL && first != second);
    assert(pf_hsd_texture_table(&foreign, 1) == NULL);
    row = pf_hsd_texture_table(first, UINT16_MAX);
    assert(row != NULL);
    assert(pf_hsd_texture_table(first, UINT16_MAX + 1U) == NULL);
    row[UINT16_MAX - 1U] = &palette;
    row[UINT16_MAX] = NULL;
    assert(pf_hsd_texture_table(second, UINT16_MAX) != row);
    assert(pf_hsd_texture_table(second, UINT16_MAX)[UINT16_MAX - 1U] == NULL);
    first->tluttbl = row;
    assert(pf_hsd_texture_table_release(first));
    first->tluttbl = pf_hsd_texture_table(second, 1);
    assert(!pf_hsd_texture_table_release(first));
    assert(pf_hsd_texture_object_return((HSD_Class*) first));
    assert(!pf_hsd_texture_object_return((HSD_Class*) first));
    assert(pf_hsd_texture_table(first, 1) == NULL);
    assert(pf_hsd_texture_object_take((int) sizeof(HSD_TObj)) == (HSD_Class*) first);
    assert(pf_hsd_texture_table(first, 1) == row);
    assert(!pf_hsd_texture_object_return((HSD_Class*) &foreign));
    assert(!pf_hsd_texture_object_return((HSD_Class*) ((char*) first + 1)));
    assert(pf_hsd_texture_object_return((HSD_Class*) first));
    assert(pf_hsd_texture_object_return((HSD_Class*) second));
    for (i = 0; i < 1024; ++i) {
        held[i] = pf_hsd_texture_object_take((int) sizeof(HSD_TObj));
        assert(held[i] != NULL);
    }
    assert(pf_hsd_texture_object_take((int) sizeof(HSD_TObj)) == NULL);
    for (i = 0; i < 1024; ++i) {
        assert(pf_hsd_texture_object_return(held[i]));
    }
    pf_hsd_texture_tables_reset();
    first = (HSD_TObj*) pf_hsd_texture_object_take((int) sizeof(HSD_TObj));
    assert(pf_hsd_texture_table(first, UINT16_MAX)[UINT16_MAX - 1U] == NULL);
    puts("native-texture-tables=pass full-u16-domain fixed-slots isolation exhaustion reuse reset");
    return 0;
}
