#include "native_gobj_runtime.h"

#include "baselib/gobj.h"
#include "baselib/gobjproc.h"
#include "baselib/class.h"
#include "baselib/jobj.h"
#include "baselib/lobj.h"
#include "baselib/memory.h"
#include "baselib/object.h"
#include "native_memory.h"
#include "native_objalloc.h"
#include "native_texture_tables.h"

#include <stdalign.h>
#include <string.h>

extern HSD_ObjAllocData gobj_alloc_data;
extern HSD_ObjAllocData gobjproc_alloc_data;
void pf_gx_viewport_reset(void);

enum {
    native_hsd_memory_size_class_count = 32,
    native_hsd_memory_piece_bytes = 32,
    native_hsd_memory_max_pieces_per_class = 256,
    native_deferred_gobj_capacity = 4096,
    native_deferred_process_capacity = 4096,
};

typedef enum NativeDeferredCaptureState {
    NATIVE_DEFERRED_CAPTURE_IDLE = 0,
    NATIVE_DEFERRED_CAPTURE_RECORDING = 1,
    NATIVE_DEFERRED_CAPTURE_PREPARED = 2,
    NATIVE_DEFERRED_CAPTURE_ACTIVE = 3,
} NativeDeferredCaptureState;

static HSD_GObj* native_deferred_baseline[native_deferred_gobj_capacity];
static HSD_GObjProc*
    native_deferred_processes[native_deferred_process_capacity];
static uint32_t native_deferred_baseline_count;
static uint32_t native_deferred_process_count;
static uint32_t native_deferred_capture_capacity;
static NativeDeferredCaptureState native_deferred_capture_state;

/* HSD_InitComponent normally establishes these pools before any scene. The
 * headless runtime deliberately omits OS, VI, GX, DVD, and audio startup, but
 * source-owned gameplay object construction still requires the same allocator
 * metadata and ID table initialization. */
void HSD_ListInitAllocData(void);
void HSD_AObjInitAllocData(void);
void HSD_FObjInitAllocData(void);
void HSD_IDInitAllocData(void);
void HSD_IDSetup(void);
void HSD_VecInitAllocData(void);
void HSD_MtxInitAllocData(void);
void HSD_RObjInitAllocData(void);
void HSD_RenderInitAllocData(void);
void HSD_ShadowInitAllocData(void);
void HSD_ZListInitAllocData(void);

/* GCC emits this tentative source global as a common symbol. The section
 * slicer cannot materialize common storage, so the native owner supplies the
 * same zero-initialized definition for the rooted archive. */
s32 HSD_GObj_804D783C;

static void native_gobj_remove_object(HSD_Obj* object)
{
    if (object != NULL && ref_DEC(object)) {
        hsdDelete(object);
    }
}

static void native_gobj_initialize_source_state(
    HSD_GObjLibInitDataType* init_data)
{
    static GObjFunc object_functions[] = {
        native_gobj_remove_object,
        (GObjFunc) HSD_LObjRemoveAll,
        (GObjFunc) HSD_JObjRemoveAll,
        native_gobj_remove_object,
    };
    static GObjFuncs function_block = { NULL, 4, object_functions };
    size_t index;
    size_t p_links = (size_t) init_data->p_link_max + 1U;
    size_t gx_links = (size_t) init_data->gx_link_max + 2U;
    size_t priorities = (size_t) init_data->gproc_pri_max + 1U;

    init_data->funcs = &function_block;
    pf_gx_viewport_reset();
    HSD_GObj_CameraKind = 0;
    HSD_GObj_LightKind = 1;
    HSD_GObj_JObjKind = 2;
    HSD_GObj_FogKind = 3;
    HSD_GObjLibInitData = *init_data;

    HSD_GObj_Entities = HSD_MemAlloc(sizeof(HSD_GObj*) * p_links);
    plinklow_gobjs = HSD_MemAlloc(sizeof(HSD_GObj*) * p_links);
    memset(HSD_GObj_Entities, 0, sizeof(HSD_GObj*) * p_links);
    memset(plinklow_gobjs, 0, sizeof(HSD_GObj*) * p_links);

    HSD_GObjGXLinkHead = HSD_MemAlloc(sizeof(HSD_GObj*) * gx_links);
    HSD_GObj_804D7820 = HSD_MemAlloc(sizeof(HSD_GObj*) * gx_links);
    memset(HSD_GObjGXLinkHead, 0, sizeof(HSD_GObj*) * gx_links);
    memset(HSD_GObj_804D7820, 0, sizeof(HSD_GObj*) * gx_links);

    HSD_GObj_804D7840 =
        HSD_MemAlloc(sizeof(HSD_GObjProc*) * priorities);
    HSD_GObj_804D7844 = HSD_MemAlloc(
        sizeof(HSD_GObjProc*) * priorities * p_links);
    memset(HSD_GObj_804D7840, 0, sizeof(HSD_GObjProc*) * priorities);
    memset(
        HSD_GObj_804D7844, 0,
        sizeof(HSD_GObjProc*) * priorities * p_links);

    HSD_GObj_804D7810 = HSD_MemAlloc(sizeof(object_functions));
    for (index = 0; index < sizeof(object_functions) / sizeof(object_functions[0]);
         ++index) {
        HSD_GObj_804D7810[index] = object_functions[index];
    }
    HSD_GObj_804D783C = 0;
    HSD_GObj_804D781C = NULL;
    HSD_GObj_804D7838 = NULL;
    HSD_GObj_804CE3E4.flags = 0;
    HSD_GObj_804D7818 = NULL;
    HSD_GObj_804D7814 = NULL;
}

static int native_collect_gobjs(HSD_GObj** output, uint32_t* count)
{
    uint32_t output_count = 0;
    uint32_t p_link;

    for (p_link = 0; p_link <= HSD_GObjLibInitData.p_link_max; ++p_link) {
        HSD_GObj* gobj = ((HSD_GObj**) HSD_GObj_Entities)[p_link];
        while (gobj != NULL) {
            if (output_count >= native_deferred_capture_capacity) {
                return 0;
            }
            output[output_count++] = gobj;
            gobj = gobj->next;
        }
    }
    *count = output_count;
    return 1;
}

static int native_gobj_was_in_deferred_baseline(HSD_GObj* gobj)
{
    uint32_t index;
    for (index = 0; index < native_deferred_baseline_count; ++index) {
        if (native_deferred_baseline[index] == gobj) {
            return 1;
        }
    }
    return 0;
}

static int checked_add(size_t* value, size_t amount)
{
    if (*value > SIZE_MAX - amount) {
        return 0;
    }
    *value += amount;
    return 1;
}

static int checked_array(size_t* value, size_t count, size_t stride)
{
    if (count != 0 && stride > SIZE_MAX / count) {
        return 0;
    }
    return checked_add(value, count * stride);
}

static int startup_storage_is_sufficient(
    size_t bytes, const HSD_GObjLibInitDataType* init_data)
{
    const size_t p_links = (size_t) init_data->p_link_max + 1U;
    const size_t gx_links = (size_t) init_data->gx_link_max + 2U;
    const size_t priorities = (size_t) init_data->gproc_pri_max + 1U;
    const size_t allocations = 7;
    size_t required = allocations * (_Alignof(max_align_t) - 1U);

    return checked_array(&required, p_links, sizeof(HSD_GObj*)) &&
        checked_array(&required, p_links, sizeof(HSD_GObj*)) &&
        checked_array(&required, gx_links, sizeof(HSD_GObj*)) &&
        checked_array(&required, gx_links, sizeof(HSD_GObj*)) &&
        checked_array(&required, priorities, sizeof(HSD_GObjProc*)) &&
        checked_array(
            &required, priorities * p_links, sizeof(HSD_GObjProc*)) &&
        checked_array(&required, 4, sizeof(GObjFunc)) && required <= bytes;
}

static void native_hsd_initialize_object_allocators(void)
{
    HSD_IDSetup();
    HSD_ListInitAllocData();
    HSD_AObjInitAllocData();
    HSD_FObjInitAllocData();
    HSD_IDInitAllocData();
    HSD_VecInitAllocData();
    HSD_MtxInitAllocData();
    HSD_RObjInitAllocData();
    HSD_RenderInitAllocData();
    HSD_ShadowInitAllocData();
    HSD_ZListInitAllocData();
}

PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_initialize(
    void* startup_storage,
    size_t startup_bytes,
    void* object_storage,
    size_t object_bytes,
    uint32_t gobj_capacity,
    uint32_t process_capacity,
    uint64_t* disabled_process_links)
{
    HSD_GObjLibInitDataType init_data;

    if (startup_storage == NULL || object_storage == NULL ||
        disabled_process_links == NULL || gobj_capacity == 0 ||
        process_capacity == 0 ||
        gobj_capacity > native_deferred_gobj_capacity) {
        return PF_HSD_GOBJ_RUNTIME_INVALID_ARGUMENT;
    }
    /* gm_801A4BD4 raises the Baselib default process-priority ceiling from 2
     * to 0x18 before scene entry. The versus root schedules camera and match
     * processes within that range. */
    init_data =
        (HSD_GObjLibInitDataType) { 0x3F, 0x3F, 0x18, NULL, NULL };
    init_data.unk_2 = disabled_process_links;
    if (!startup_storage_is_sufficient(startup_bytes, &init_data)) {
        return PF_HSD_GOBJ_RUNTIME_STARTUP_ARENA_TOO_SMALL;
    }
    *disabled_process_links = 0;
    native_deferred_baseline_count = 0;
    native_deferred_process_count = 0;
    native_deferred_capture_capacity = gobj_capacity;
    native_deferred_capture_state = NATIVE_DEFERRED_CAPTURE_IDLE;
    pf_hsd_startup_arena_bind(startup_storage, startup_bytes);
    pf_hsd_texture_tables_reset();
    native_gobj_initialize_source_state(&init_data);
    if (pf_hsd_startup_arena_rejected_allocations() != 0) {
        return PF_HSD_GOBJ_RUNTIME_STARTUP_ARENA_TOO_SMALL;
    }

    pf_hsd_obj_arena_bind(object_storage, object_bytes);
    native_hsd_initialize_object_allocators();
    if (!pf_hsd_obj_pool_prepare(
            &gobj_alloc_data,
            sizeof(HSD_GObj),
            alignof(HSD_GObj),
            gobj_capacity) ||
        !pf_hsd_obj_pool_prepare(
            &gobjproc_alloc_data,
            sizeof(HSD_GObjProc),
            alignof(HSD_GObjProc),
            process_capacity)) {
        return PF_HSD_GOBJ_RUNTIME_OBJECT_ARENA_TOO_SMALL;
    }
    return PF_HSD_GOBJ_RUNTIME_OK;
}

PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_begin_deferred_process_capture(void)
{
    if (native_deferred_capture_state != NATIVE_DEFERRED_CAPTURE_IDLE) {
        return PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_STATE;
    }
    if (!native_collect_gobjs(
            native_deferred_baseline, &native_deferred_baseline_count)) {
        return PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_CAPACITY;
    }
    native_deferred_process_count = 0;
    native_deferred_capture_state = NATIVE_DEFERRED_CAPTURE_RECORDING;
    return PF_HSD_GOBJ_RUNTIME_OK;
}

PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_end_deferred_process_capture(void)
{
    uint32_t p_link;

    if (native_deferred_capture_state != NATIVE_DEFERRED_CAPTURE_RECORDING) {
        return PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_STATE;
    }
    for (p_link = 0; p_link <= HSD_GObjLibInitData.p_link_max; ++p_link) {
        HSD_GObj* gobj = ((HSD_GObj**) HSD_GObj_Entities)[p_link];
        while (gobj != NULL) {
            if (!native_gobj_was_in_deferred_baseline(gobj)) {
                HSD_GObjProc* process = gobj->proc;
                while (process != NULL) {
                    if (!process->flags_1) {
                        if (native_deferred_process_count >=
                            native_deferred_process_capacity) {
                            return PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_CAPACITY;
                        }
                        process->flags_1 = 1;
                        native_deferred_processes
                            [native_deferred_process_count++] = process;
                    }
                    process = process->child;
                }
            }
            gobj = gobj->next;
        }
    }
    native_deferred_capture_state = NATIVE_DEFERRED_CAPTURE_PREPARED;
    return PF_HSD_GOBJ_RUNTIME_OK;
}

PfHsdGObjRuntimeStatus
pf_hsd_gobj_runtime_activate_deferred_stage_start(void)
{
    uint32_t index;

    if (native_deferred_capture_state != NATIVE_DEFERRED_CAPTURE_PREPARED) {
        return PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_STATE;
    }
    for (index = 0; index < native_deferred_process_count; ++index) {
        native_deferred_processes[index]->flags_1 = 0;
    }
    native_deferred_capture_state = NATIVE_DEFERRED_CAPTURE_ACTIVE;
    return PF_HSD_GOBJ_RUNTIME_OK;
}

uint32_t pf_hsd_gobj_runtime_deferred_process_count(void)
{
    return native_deferred_process_count;
}

int pf_hsd_gobj_runtime_deferred_stage_start_is_active(void)
{
    return native_deferred_capture_state == NATIVE_DEFERRED_CAPTURE_ACTIVE;
}

PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_finalize_initialization(void)
{
    if (pf_hsd_startup_arena_rejected_allocations() != 0) {
        return PF_HSD_GOBJ_RUNTIME_STARTUP_ARENA_TOO_SMALL;
    }
    pf_hsd_startup_arena_freeze();
    return PF_HSD_GOBJ_RUNTIME_OK;
}

PfHsdGObjRuntimeStatus pf_hsd_gobj_runtime_prewarm_memory_pool(
    uint32_t pieces_per_size_class)
{
    void* pieces[native_hsd_memory_max_pieces_per_class];
    uint32_t size_class;

    if (pieces_per_size_class == 0 ||
        pieces_per_size_class > native_hsd_memory_max_pieces_per_class) {
        return PF_HSD_GOBJ_RUNTIME_INVALID_ARGUMENT;
    }
    for (size_class = 0;
         size_class < native_hsd_memory_size_class_count;
         ++size_class) {
        const s32 piece_bytes =
            (s32) ((size_class + 1U) * native_hsd_memory_piece_bytes);
        uint32_t piece_count = 0;
        for (; piece_count < pieces_per_size_class; ++piece_count) {
            pieces[piece_count] = hsdAllocMemPiece(piece_bytes);
            if (pieces[piece_count] == NULL) {
                while (piece_count != 0) {
                    --piece_count;
                    hsdFreeMemPiece(pieces[piece_count], piece_bytes);
                }
                return PF_HSD_GOBJ_RUNTIME_MEMORY_POOL_TOO_SMALL;
            }
        }
        while (piece_count != 0) {
            --piece_count;
            hsdFreeMemPiece(pieces[piece_count], piece_bytes);
        }
    }
    return PF_HSD_GOBJ_RUNTIME_OK;
}

size_t pf_hsd_gobj_runtime_startup_bytes_used(void)
{
    return pf_hsd_startup_arena_bytes_used();
}

size_t pf_hsd_gobj_runtime_object_bytes_used(void)
{
    return pf_hsd_obj_arena_bytes_used();
}
