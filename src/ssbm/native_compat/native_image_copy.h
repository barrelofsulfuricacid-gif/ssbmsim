#ifndef PF_SSBM_NATIVE_IMAGE_COPY_H
#define PF_SSBM_NATIVE_IMAGE_COPY_H

#include <sysdolphin/baselib/tobj.h>

/* Audited texture-only consumers retain the original copy preparation and
 * CPU state-cache updates, while omitting the device's pixel write. */
void pf_hsd_image_desc_copy_without_pixels(HSD_ImageDesc* image, u16 x, u16 y,
                                         GXBool clear, bool sync);

#endif
