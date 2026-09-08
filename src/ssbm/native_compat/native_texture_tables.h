#ifndef PF_SSBM_NATIVE_TEXTURE_TABLES_H
#define PF_SSBM_NATIVE_TEXTURE_TABLES_H

#include "baselib/tobj.h"

void pf_hsd_texture_tables_reset(void);
HSD_Class* pf_hsd_texture_object_take(int bytes);
int pf_hsd_texture_object_return(HSD_Class* object);
HSD_Tlut** pf_hsd_texture_table(HSD_TObj* object, unsigned int count);
int pf_hsd_texture_table_release(HSD_TObj* object);

#endif
