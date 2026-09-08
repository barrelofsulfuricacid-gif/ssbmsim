#include <dolphin/gx/GXTexture.h>

/* Pure size calculation from the pinned Dolphin SDK GXTexture.c. This keeps
 * source allocation sizes and object lifecycles exact without providing a GX
 * device, texture upload, or renderer. */
static void pf_gx_get_tex_tile_shift(
    u32 format,
    u32* row_tile_shift,
    u32* column_tile_shift)
{
    switch (format) {
    case GX_TF_I4:
    case GX_TF_C4:
    case GX_TF_CMPR:
    case GX_CTF_R4:
    case GX_CTF_Z4:
        *row_tile_shift = 3;
        *column_tile_shift = 3;
        break;
    case GX_TF_I8:
    case GX_TF_IA4:
    case GX_TF_C8:
    case GX_TF_Z8:
    case GX_CTF_RA4:
    case GX_TF_A8:
    case GX_CTF_R8:
    case GX_CTF_G8:
    case GX_CTF_B8:
    case GX_CTF_Z8M:
    case GX_CTF_Z8L:
        *row_tile_shift = 3;
        *column_tile_shift = 2;
        break;
    case GX_TF_IA8:
    case GX_TF_RGB565:
    case GX_TF_RGB5A3:
    case GX_TF_RGBA8:
    case GX_TF_C14X2:
    case GX_TF_Z16:
    case GX_TF_Z24X8:
    case GX_CTF_RA8:
    case GX_CTF_RG8:
    case GX_CTF_GB8:
    case GX_CTF_Z16L:
        *row_tile_shift = 2;
        *column_tile_shift = 2;
        break;
    default:
        *row_tile_shift = 0;
        *column_tile_shift = 0;
        break;
    }
}

u32 GXGetTexBufferSize(
    u16 width,
    u16 height,
    u32 format,
    GXBool mipmap,
    u8 max_lod)
{
    u32 tile_shift_x;
    u32 tile_shift_y;
    u32 tile_bytes;
    u32 buffer_size;
    u32 nx;
    u32 ny;
    u32 level;

    pf_gx_get_tex_tile_shift(format, &tile_shift_x, &tile_shift_y);
    tile_bytes = format == GX_TF_RGBA8 || format == GX_TF_Z24X8 ? 64U : 32U;
    if (mipmap == GX_TRUE) {
        buffer_size = 0;
        for (level = 0; level < max_lod; ++level) {
            nx = (width + (1U << tile_shift_x) - 1U) >> tile_shift_x;
            ny = (height + (1U << tile_shift_y) - 1U) >> tile_shift_y;
            buffer_size += tile_bytes * nx * ny;
            if (width == 1 && height == 1) {
                break;
            }
            width = width > 1 ? (u16) (width >> 1) : 1;
            height = height > 1 ? (u16) (height >> 1) : 1;
        }
    } else {
        nx = (width + (1U << tile_shift_x) - 1U) >> tile_shift_x;
        ny = (height + (1U << tile_shift_y) - 1U) >> tile_shift_y;
        buffer_size = nx * ny * tile_bytes;
    }
    return buffer_size;
}
