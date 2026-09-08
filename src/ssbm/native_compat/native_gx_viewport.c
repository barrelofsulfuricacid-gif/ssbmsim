#include <dolphin/gx/GXTransform.h>
#include <dolphin/gx/GXStruct.h>
#include <dolphin/gx/GXGeometry.h>
#include <dolphin/gx/GXTev.h>
#include <dolphin/gx/GXCull.h>
#include <dolphin/gx/GXPixel.h>
#include <dolphin/gx/GXLighting.h>

/* Source-observable viewport values from GXTransform.c. Hardware upload and
 * device range registers are outside this native state boundary. */
static f32 native_viewport[6];
/* Camera projection values are read back by fog and particle callbacks. */
static f32 native_projection[6];
static GXProjectionType native_projection_type;

void pf_gx_viewport_reset(void)
{
    unsigned int i;
    for (i = 0; i < 6; ++i) {
        native_viewport[i] = 0.0F;
        native_projection[i] = 0.0F;
    }
    native_projection_type = GX_PERSPECTIVE;
}

#ifdef TARGET_PC
void GXSetProjection(const void* matrix, GXProjectionType type)
#else
void GXSetProjection(f32 matrix[4][4], GXProjectionType type)
#endif
{
    const f32 (*mtx)[4] = (const f32 (*)[4]) matrix;
    native_projection_type = type;
    native_projection[0] = mtx[0][0];
    native_projection[2] = mtx[1][1];
    native_projection[4] = mtx[2][2];
    native_projection[5] = mtx[2][3];
    if (type == GX_ORTHOGRAPHIC) {
        native_projection[1] = mtx[0][3];
        native_projection[3] = mtx[1][3];
    } else {
        native_projection[1] = mtx[0][2];
        native_projection[3] = mtx[1][2];
    }
}

void GXGetProjectionv(f32* projection)
{
    unsigned int i;
    projection[0] = native_projection_type;
    for (i = 0; i < 6; ++i) {
        projection[i + 1] = native_projection[i];
    }
}

void GXSetViewportJitter(f32 left, f32 top, f32 width, f32 height,
                         f32 near_z, f32 far_z, u32 field)
{
    if (field == 0) {
        top -= 0.5F;
    }
    native_viewport[0] = left;
    native_viewport[1] = top;
    native_viewport[2] = width;
    native_viewport[3] = height;
    native_viewport[4] = near_z;
    native_viewport[5] = far_z;
}

void GXSetViewport(f32 left, f32 top, f32 width, f32 height,
                   f32 near_z, f32 far_z)
{
    GXSetViewportJitter(left, top, width, height, near_z, far_z, 1U);
}

void GXGetViewportv(f32* viewport)
{
    unsigned int i;
    for (i = 0; i < 6; ++i) {
        viewport[i] = native_viewport[i];
    }
}

/* The pinned gameplay sources never query the SDK scissor cache. Its only
 * reader is the unused GXGetScissor SDK function, absent from the retail
 * symbol map. Keep this device-output boundary separate from viewport state. */
void GXSetScissor(u32 left, u32 top, u32 width, u32 height)
{
    (void) left;
    (void) top;
    (void) width;
    (void) height;
}

/* GXAttr.c writes only the texture-count bits of genMode and device output.
 * No source getter reads those bits; other genMode readers select disjoint
 * cull, TEV-stage and indirect-stage fields. */
void GXSetNumTexGens(u8 count)
{
    (void) count;
}

/* TEV-stage count feeds SDK texture-coordinate uploads and a debug-only
 * overlap assertion. The resulting size cache has no pinned gameplay reader
 * (__GXGetSUTexSize is unused). No native device cache is required. */
void GXSetNumTevStages(u8 count)
{
    (void) count;
}

/* tref/texmapId feed the same SDK upload/debug consumers as stage count. */
void GXSetTevOrder(GXTevStageID stage, GXTexCoordID coord, GXTexMapID map,
                   GXChannelID color)
{
    (void) stage;
    (void) coord;
    (void) map;
    (void) color;
}

/* GXTev.c's operation family only modifies tevc/teva upload caches. There
 * are no getters or gameplay readers of these fields in the pinned sources. */
void GXSetTevOp(GXTevStageID stage, GXTevMode mode)
{
    (void) stage;
    (void) mode;
}

void GXSetTevColorIn(GXTevStageID stage, GXTevColorArg a, GXTevColorArg b,
                     GXTevColorArg c, GXTevColorArg d)
{
    (void) stage;
    (void) a;
    (void) b;
    (void) c;
    (void) d;
}

void GXSetTevAlphaIn(GXTevStageID stage, GXTevAlphaArg a, GXTevAlphaArg b,
                     GXTevAlphaArg c, GXTevAlphaArg d)
{
    (void) stage;
    (void) a;
    (void) b;
    (void) c;
    (void) d;
}

void GXSetTevColorOp(GXTevStageID stage, GXTevOp op, GXTevBias bias,
                     GXTevScale scale, GXBool clamp, GXTevRegID out_reg)
{
    (void) stage;
    (void) op;
    (void) bias;
    (void) scale;
    (void) clamp;
    (void) out_reg;
}

void GXSetTevAlphaOp(GXTevStageID stage, GXTevOp op, GXTevBias bias,
                     GXTevScale scale, GXBool clamp, GXTevRegID out_reg)
{
    (void) stage;
    (void) op;
    (void) bias;
    (void) scale;
    (void) clamp;
    (void) out_reg;
}

/* genMode cull bits feed device output; GXGetCullMode has no pinned
 * gameplay callers. HSD-owned culling state and traversal are preserved. */
void GXSetCullMode(GXCullMode mode)
{
    (void) mode;
}

/* Pixel settings feed only device uploads, including temporary overrides
 * during GXCopyDisp/GXCopyTex. No pinned gameplay getter reads these caches. */
void GXSetAlphaCompare(GXCompare comp0, u8 ref0, GXAlphaOp op,
                       GXCompare comp1, u8 ref1)
{
    (void) comp0;
    (void) ref0;
    (void) op;
    (void) comp1;
    (void) ref1;
}

void GXSetBlendMode(GXBlendMode type, GXBlendFactor src_factor,
                    GXBlendFactor dst_factor, GXLogicOp op)
{
    (void) type;
    (void) src_factor;
    (void) dst_factor;
    (void) op;
}

void GXSetColorUpdate(GXBool enable) { (void) enable; }
void GXSetAlphaUpdate(GXBool enable) { (void) enable; }
void GXSetZCompLoc(GXBool before_tex) { (void) before_tex; }

void GXSetZMode(GXBool compare_enable, GXCompare func, GXBool update_enable)
{
    (void) compare_enable;
    (void) func;
    (void) update_enable;
}

/* GXLight.c channel count/control only produce device output. Count occupies
 * genMode bits 4..6; no pinned source reader consumes those bits. */
void GXSetNumChans(u8 count) { (void) count; }

void GXSetChanCtrl(GXChannelID chan, GXBool enable, GXColorSrc amb_src,
                   GXColorSrc mat_src, u32 light_mask, GXDiffuseFn diff_fn,
                   GXAttnFn attn_fn)
{
    (void) chan;
    (void) enable;
    (void) amb_src;
    (void) mat_src;
    (void) light_mask;
    (void) diff_fn;
    (void) attn_fn;
}

/* Descriptor/format getters are unused by pinned gameplay. Remaining SDK
 * consumers are upload/flush generation and DEBUG-only GXSave/verification.
 * Source-owned mesh descriptors and joint traversal remain outside this bound. */
void GXClearVtxDesc(void) {}
void GXSetVtxDesc(GXAttr attr, GXAttrType type)
{
    (void) attr;
    (void) type;
}
void GXSetVtxAttrFmt(GXVtxFmt fmt, GXAttr attr, GXCompCnt count,
                     GXCompType type, u8 frac)
{
    (void) fmt;
    (void) attr;
    (void) count;
    (void) type;
    (void) frac;
}

/* GXTransform position upload has no native-side consumer. Matrix selection
 * is read only by __GXSetMatrixIndex to produce device output. */
#ifdef TARGET_PC
void GXLoadPosMtxImm(const void* matrix, u32 id)
#else
void GXLoadPosMtxImm(f32 matrix[3][4], u32 id)
#endif
{
    (void) matrix;
    (void) id;
}
void GXSetCurrentMtx(u32 id) { (void) id; }

/* Primitive emission terminates here. GXBegin's SDK dirty-state work only
 * uploads the audited device caches; vertex functions only write FIFO words.
 * No vertex buffer, graphics command stream or emulated device is created. */
void GXBegin(GXPrimitive primitive, GXVtxFmt fmt, u16 count)
{
    (void) primitive;
    (void) fmt;
    (void) count;
}
void GXEnd(void) {}
void GXPosition3f32(f32 x, f32 y, f32 z)
{
    (void) x; (void) y; (void) z;
}
void GXPosition2f32(f32 x, f32 y) { (void) x; (void) y; }
void GXPosition2u8(u8 x, u8 y) { (void) x; (void) y; }
void GXColor4u8(u8 r, u8 g, u8 b, u8 a)
{
    (void) r; (void) g; (void) b; (void) a;
}
void GXTexCoord2f32(f32 s, f32 t) { (void) s; (void) t; }
void GXTexCoord2u8(u8 s, u8 t) { (void) s; (void) t; }
void GXTexCoord1u8(u8 s) { (void) s; }
void GXTexCoord1x16(u16 index) { (void) index; }
void GXTexCoord1x8(u8 index) { (void) index; }

/* GXTev.c constructs two local upload words; there is no readable cache. */
void GXSetZTexture(GXZTexOp op, GXTexFmt fmt, u32 bias)
{
    (void) op;
    (void) fmt;
    (void) bias;
}

/* GXLight.c reads the CPU light object and uploads it without mutating it.
 * Original constructors/getters remain in the imported source provider. */
void GXLoadLightObjImm(GXLightObj* light, GXLightID id)
{
    (void) light;
    (void) id;
}

/* GXPixel.c fog setters construct only local device words. HSD fog objects
 * and the CPU adjustment-table constructor remain separate source state. */
void GXSetFog(GXFogType type, f32 start, f32 end, f32 near_z, f32 far_z,
              GXColor color)
{
    (void) type; (void) start; (void) end;
    (void) near_z; (void) far_z; (void) color;
}

/* Texture matrices are uploaded without changing CPU matrix storage. */
#ifdef TARGET_PC
void GXLoadTexMtxImm(const void* matrix, u32 id, GXTexMtxType type)
#else
void GXLoadTexMtxImm(f32 matrix[][4], u32 id, GXTexMtxType type)
#endif
{
    (void) matrix; (void) id; (void) type;
}

/* suTs0 bits 18/19 affect only device texture offsets; the SDK size getter
 * reads bits 0..15 and has no pinned gameplay callers. */
void GXEnableTexOffsets(GXTexCoordID coord, GXBool line, GXBool point)
{
    (void) coord; (void) line; (void) point;
}

/* Pinned gameplay registers no custom region callbacks. SDK defaults rotate
 * device-cache regions; preloaded upload changes only output-address bits and
 * SDK upload caches. CPU metadata getters do not observe those bits. */
void GXLoadTexObj(GXTexObj* texture, GXTexMapID id)
{
    (void) texture;
    (void) id;
}

/* GXAttr.c emits texture-generation words and updates texture-selection bits
 * in matIdxA/B. Their only consumers are SDK matrix-index uploads; no pinned
 * gameplay reader observes that output cache. */
void GXSetTexCoordGen2(GXTexCoordID coord, GXTexGenType function,
                       GXTexGenSrc source, u32 matrix, GXBool normalize,
                       u32 post_matrix)
{
    (void) coord; (void) function; (void) source;
    (void) matrix; (void) normalize; (void) post_matrix;
}

/* SDK synchronization re-emits peCtrl and resets the device-stream bpSent
 * marker. It neither waits for a gameplay event nor mutates a source object. */
void GXPixModeSync(void) {}

/* The range table is read only to construct output words. Keep its CPU
 * constructor separate; this boundary does not own or change that table. */
void GXSetFogRangeAdj(GXBool enable, u16 center, GXFogAdjTable* table)
{
    (void) enable; (void) center; (void) table;
}

/* GXTev.c color values produce local upload words. Selection/swap setters
 * modify only tevKsel/teva output caches, consumed by the same SDK setters.
 * No CPU color object is mutated and no gameplay getter reads these caches. */
void GXSetTevColor(GXTevRegID id, GXColor color)
{
    (void) id; (void) color;
}
void GXSetTevColorS10(GXTevRegID id, GXColorS10 color)
{
    (void) id; (void) color;
}
void GXSetTevKColor(GXTevKColorID id, GXColor color)
{
    (void) id; (void) color;
}
void GXSetTevKColorSel(GXTevStageID stage, GXTevKColorSel selection)
{
    (void) stage; (void) selection;
}
void GXSetTevKAlphaSel(GXTevStageID stage, GXTevKAlphaSel selection)
{
    (void) stage; (void) selection;
}
void GXSetTevSwapMode(GXTevStageID stage, GXTevSwapSel raster,
                      GXTevSwapSel texture)
{
    (void) stage; (void) raster; (void) texture;
}

/* GXPixel.c destination alpha changes cmode1 bits 0..8, whose only consumers
 * upload cmode1. Dithering changes cmode0's output-only bit 2. */
void GXSetDstAlpha(GXBool enable, u8 alpha)
{
    (void) enable; (void) alpha;
}
void GXSetDither(GXBool enable) { (void) enable; }

/* GXLight.c ambColor/matColor caches only merge RGB/alpha for subsequent
 * uploads by these same setters. They have no pinned gameplay consumers. */
void GXSetChanAmbColor(GXChannelID channel, GXColor color)
{
    (void) channel; (void) color;
}
void GXSetChanMatColor(GXChannelID channel, GXColor color)
{
    (void) channel; (void) color;
}

/* GXAttr.c uploads array base/stride. indexBase/indexStride are consumed
 * only by DEBUG-only GXSave.c; native gameplay owns the source arrays. */
#ifdef TARGET_PC
void GXSetArray(GXAttr attribute, const void* data, u32 size, u8 stride,
                bool little_endian)
{
    (void) attribute; (void) data; (void) size;
    (void) stride; (void) little_endian;
}
#else
void GXSetArray(GXAttr attribute, const void* data, u8 stride)
{
    (void) attribute; (void) data; (void) stride;
}
#endif

/* GXTransform.c reads nine matrix components for output without mutation. */
#ifdef TARGET_PC
void GXLoadNrmMtxImm(const void* matrix, u32 id)
#else
void GXLoadNrmMtxImm(f32 matrix[3][4], u32 id)
#endif
{
    (void) matrix; (void) id;
}

/* GXDisplayList.c flushes the same output caches as GXBegin, then emits a
 * list address and byte count. CPU inspection is DEBUG-only GXSave.c.
 * Headless gameplay neither interprets nor modifies the device list. */
#ifdef TARGET_PC
void GXCallDisplayList(const void* list, u32 byte_count)
#else
void GXCallDisplayList(void* list, u32 byte_count)
#endif
{
    (void) list; (void) byte_count;
}

/* GXFrameBuf.c copy configuration feeds only GXCopyTex's device commands.
 * The actual copy remains a separate boundary requiring destination audit. */
void GXSetTexCopySrc(u16 left, u16 top, u16 width, u16 height)
{
    (void) left; (void) top; (void) width; (void) height;
}
void GXSetTexCopyDst(u16 width, u16 height, GXTexFmt format, GXBool mipmap)
{
    (void) width; (void) height; (void) format; (void) mipmap;
}

/* GXPixel.c updates peCtrl/cmode1 and genMode's AA output bit. Their
 * consumers only upload device state, including temporary copy settings. */
void GXSetPixelFmt(GXPixelFmt format, GXZFmt16 depth_format)
{
    (void) format; (void) depth_format;
}
/* Field mode uploads local words and lpSize bit 22; line/point getters
 * observe separate fields. Texture flushes only re-emit the output mask. */
void GXSetFieldMode(GXBool field_mode, GXBool half_aspect_ratio)
{
    (void) field_mode; (void) half_aspect_ratio;
}

/* GXTexture.c invalidates only device texture caches between output flushes. */
void GXInvalidateTexAll(void) {}

/* Pinned gameplay installs no palette-region callback. GXLoadTlut modifies
 * only device-location bits 0..9 and a region cache consumed by texture
 * uploads; CPU getters observe format bits 10..11, data and entry count. */
#ifdef TARGET_PC
void GXLoadTlut(const GXTlutObj* palette, u32 id)
#else
void GXLoadTlut(GXTlutObj* palette, u32 id)
#endif
{
    (void) palette; (void) id;
}

/* GXGeometry lpSize fields feed raster output. Pinned gameplay has no
 * GXGetLineWidth/GXGetPointSize consumers; HSD's own state cache is retained. */
void GXSetLineWidth(u8 width, GXTexOffset offsets)
{
    (void) width; (void) offsets;
}
void GXSetPointSize(u8 size, GXTexOffset offsets)
{
    (void) size; (void) offsets;
}
