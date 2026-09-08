#include "baselib/gobj.h"
#include "baselib/gobjproc.h"
#include "baselib/memory.h"
#include "native_competitive_presentation.h"
#include "native_gobj_runtime.h"
#include "native_memory.h"
#include "native_objalloc.h"
#include "native_rng.h"
#include "native_slippi_frame_start.h"

#include <stdalign.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    process_priority_count = 3,
    process_link_count = 15,
    process_capacity = 16,
    object_capacity = 8,
    trace_capacity = 32,
};

extern HSD_ObjAllocData gobj_alloc_data;
extern HSD_ObjAllocData gobjproc_alloc_data;

static alignas(max_align_t) unsigned char startup_arena[16384];
static alignas(max_align_t) unsigned char process_arena[16384];
static uint64_t disabled_process_links;
static uint16_t trace[trace_capacity];
static size_t trace_count;
static unsigned int go_completion_count;

static int check(int condition, const char* message)
{
    if (!condition) {
        fprintf(stderr, "gobj-scheduler failure: %s\n", message);
        return 0;
    }
    return 1;
}

static void record(HSD_GObj* gobj)
{
    if (trace_count < trace_capacity) {
        trace[trace_count++] = gobj->classifier;
    }
}

static void record_and_remove_self(HSD_GObj* gobj)
{
    record(gobj);
    HSD_GObjProc_8038FE24(HSD_GObj_804D7838);
}

static void set_rng_before_frame_start(HSD_GObj* gobj)
{
    (void) gobj;
    pf_ssbm_native_rng_set(UINT32_C(0x22222222));
}

static void set_rng_after_frame_start(HSD_GObj* gobj)
{
    (void) gobj;
    pf_ssbm_native_rng_set(UINT32_C(0x33333333));
}

static void record_go_completion(void)
{
    go_completion_count += 1;
}

static int expect_trace(const uint16_t* expected, size_t count)
{
    if (!check(trace_count == count, "unexpected callback count")) {
        return 0;
    }
    for (size_t index = 0; index < count; ++index) {
        if (!check(trace[index] == expected[index], "callback order mismatch")) {
            return 0;
        }
    }
    trace_count = 0;
    return 1;
}

static int reset_scheduler(void)
{
    HSD_GObjLibInitDataType init_data = {
        .p_link_max = process_link_count - 1,
        .gx_link_max = 0,
        .gproc_pri_max = process_priority_count - 1,
        .funcs = NULL,
        .unk_2 = &disabled_process_links,
    };

    memset(trace, 0, sizeof(trace));
    trace_count = 0;
    disabled_process_links = 0;
    pf_hsd_startup_arena_bind(startup_arena, sizeof(startup_arena));
    HSD_GObj_80391304(&init_data);
    if (!check(
            pf_hsd_startup_arena_rejected_allocations() == 0,
            "source GObj initialization exhausted startup arena")) {
        return 0;
    }
    pf_hsd_startup_arena_freeze();
    pf_hsd_obj_arena_bind(process_arena, sizeof(process_arena));
    if (!check(
            pf_hsd_obj_pool_prepare(
                &gobj_alloc_data,
                sizeof(HSD_GObj),
                alignof(HSD_GObj),
                object_capacity),
            "could not prefill fixed GObj pool") ||
        !check(
            pf_hsd_obj_pool_prepare(
                &gobjproc_alloc_data,
                sizeof(HSD_GObjProc),
                alignof(HSD_GObjProc),
                process_capacity),
            "could not prefill fixed process pool")) {
        return 0;
    }
    return check(
               HSD_GObjLibInitData.p_link_max == process_link_count - 1 &&
                   HSD_GObjLibInitData.gproc_pri_max ==
                       process_priority_count - 1,
               "source GObj initialization lost configured limits") &&
        check(HSD_GObj_Entities != NULL, "source GObj entity table is missing") &&
        check(HSD_GObj_804D7840 != NULL, "source process heads are missing") &&
        check(HSD_GObj_804D7844 != NULL, "source process tails are missing");
}

static int test_priority_link_and_disable_order(void)
{
    HSD_GObj* link0_first;
    HSD_GObj* link0_second;
    HSD_GObj* link1;
    const uint16_t initial[] = { 20, 10, 11, 20 };
    const uint16_t masked[] = { 10, 11 };
    const uint16_t disabled[] = { 20, 10, 20 };
    size_t arena_after_setup;

    if (!reset_scheduler()) {
        return 0;
    }
    link0_first = GObj_Create(10, 0, 10);
    link0_second = GObj_Create(11, 0, 20);
    link1 = GObj_Create(20, 1, 10);
    if (!check(
            link0_first != NULL && link0_second != NULL && link1 != NULL,
            "source GObj creation exhausted fixed pool") ||
        !check(HSD_GObj_SetupProc(link1, record, 1) != NULL, "setup link1") ||
        !check(
            HSD_GObj_SetupProc(link0_second, record, 1) != NULL,
            "setup link0 second") ||
        !check(
            HSD_GObj_SetupProc(link0_first, record, 1) != NULL,
            "setup link0 first") ||
        !check(
            HSD_GObj_SetupProc(link1, record, 0) != NULL,
            "setup higher process priority")) {
        return 0;
    }
    arena_after_setup = pf_hsd_obj_arena_bytes_used();
    HSD_GObj_80390CFC();
    if (!expect_trace(initial, sizeof(initial) / sizeof(initial[0])) ||
        !check(
            pf_hsd_obj_arena_bytes_used() == arena_after_setup,
            "process step grew fixed object arena") ||
        !check(
            pf_hsd_startup_arena_rejected_allocations() == 0,
            "process step attempted startup allocation")) {
        return 0;
    }

    disabled_process_links = UINT64_C(1) << 1;
    HSD_GObj_80390CFC();
    if (!expect_trace(masked, sizeof(masked) / sizeof(masked[0]))) {
        return 0;
    }

    disabled_process_links = 0;
    HSD_GObj_80390C5C(link0_second);
    HSD_GObj_80390CFC();
    return expect_trace(disabled, sizeof(disabled) / sizeof(disabled[0]));
}

static int test_remove_current_process(void)
{
    HSD_GObj* removing;
    HSD_GObj* remaining;
    const uint16_t first[] = { 30, 31 };
    const uint16_t second[] = { 31 };
    size_t arena_after_setup;

    if (!reset_scheduler()) {
        return 0;
    }
    removing = GObj_Create(30, 0, 10);
    remaining = GObj_Create(31, 0, 20);
    if (!check(removing != NULL && remaining != NULL, "source GObj creation") ||
        !check(
            HSD_GObj_SetupProc(removing, record_and_remove_self, 0) != NULL,
            "setup self-removing process") ||
        !check(
            HSD_GObj_SetupProc(remaining, record, 0) != NULL,
            "setup remaining process")) {
        return 0;
    }
    arena_after_setup = pf_hsd_obj_arena_bytes_used();
    HSD_GObj_80390CFC();
    if (!expect_trace(first, sizeof(first) / sizeof(first[0])) ||
        !check(
            pf_hsd_obj_pool_used(&gobjproc_alloc_data) == 1,
            "removed process was not freed") ||
        !check(
            pf_hsd_obj_arena_bytes_used() == arena_after_setup,
            "removal step grew fixed object arena") ||
        !check(
            pf_hsd_startup_arena_rejected_allocations() == 0,
            "removal step attempted startup allocation")) {
        return 0;
    }
    HSD_GObj_80390CFC();
    return expect_trace(second, sizeof(second) / sizeof(second[0]));
}

static int test_initialization_freeze_boundary(void)
{
    void* allocation;
    size_t bytes_after_allocation;

    if (!check(
            pf_hsd_gobj_runtime_initialize(
                startup_arena,
                sizeof(startup_arena),
                process_arena,
                sizeof(process_arena),
                object_capacity,
                process_capacity,
                &disabled_process_links) == PF_HSD_GOBJ_RUNTIME_OK,
            "wrapper initialization failed") ||
        !check(
            (allocation = HSD_MemAlloc(32)) != NULL,
            "match-construction allocation was frozen too early")) {
        return 0;
    }
    bytes_after_allocation = pf_hsd_startup_arena_bytes_used();
    HSD_Free(allocation);
    if (!check(
            pf_hsd_startup_arena_bytes_used() == bytes_after_allocation,
            "startup arena unexpectedly reused a released block") ||
        !check(
            pf_hsd_gobj_runtime_finalize_initialization() ==
                PF_HSD_GOBJ_RUNTIME_OK,
            "wrapper initialization finalization failed") ||
        !check(
            HSD_MemAlloc(32) == NULL,
            "post-initialization allocation was accepted")) {
        return 0;
    }
    HSD_Free(allocation);
    return check(
        pf_hsd_startup_arena_rejected_allocations() == 1,
        "post-initialization allocation rejection was not recorded");
}

static int test_slippi_frame_start_scheduler_boundary(void)
{
    HSD_GObj* before;
    HSD_GObj* after;
    uint32_t captured_seed = 0;
    size_t arena_after_setup;

    pf_ssbm_native_slippi_frame_start_reset();
    if (!reset_scheduler()) {
        return 0;
    }
    before = GObj_Create(60, 6, 0);
    after = GObj_Create(80, 8, 0);
    if (!check(before != NULL && after != NULL, "source GObj creation") ||
        !check(
            HSD_GObj_SetupProc(before, set_rng_before_frame_start, 0) != NULL,
            "setup pre-FrameStart process") ||
        !check(
            HSD_GObj_SetupProc(after, set_rng_after_frame_start, 0) != NULL,
            "setup post-FrameStart process")) {
        return 0;
    }
    pf_ssbm_native_slippi_frame_start_install();
    if (!check(
            pf_ssbm_native_slippi_frame_start_installed(),
            "FrameStart process installation failed")) {
        return 0;
    }

    arena_after_setup = pf_hsd_obj_arena_bytes_used();
    pf_ssbm_native_rng_set(UINT32_C(0x11111111));
    pf_ssbm_native_slippi_frame_start_begin_frame();
    HSD_GObj_80390CFC();
    return check(
               pf_ssbm_native_slippi_frame_start_take(&captured_seed),
               "FrameStart process did not capture RNG") &&
        check(
               captured_seed == UINT32_C(0x22222222),
               "FrameStart did not observe RNG between PLink 6 and PLink 8") &&
        check(
               pf_ssbm_native_rng_get() == UINT32_C(0x33333333),
               "post-FrameStart process did not execute") &&
        check(
               pf_hsd_obj_arena_bytes_used() == arena_after_setup,
               "FrameStart scheduler step grew fixed object arena") &&
        check(
               pf_hsd_startup_arena_rejected_allocations() == 0,
               "FrameStart scheduler step attempted startup allocation");
}

static int test_deferred_stage_start_processes(void)
{
    HSD_GObj* baseline;
    HSD_GObj* deferred_first;
    HSD_GObj* deferred_second;
    const uint16_t before_activation[] = { 40 };
    const uint16_t after_activation[] = { 40, 41, 42 };
    size_t arena_after_setup;

    if (!check(
            pf_hsd_gobj_runtime_initialize(
                startup_arena,
                sizeof(startup_arena),
                process_arena,
                sizeof(process_arena),
                object_capacity,
                process_capacity,
                &disabled_process_links) == PF_HSD_GOBJ_RUNTIME_OK,
            "deferred wrapper initialization failed")) {
        return 0;
    }
    baseline = GObj_Create(40, 0, 0);
    if (!check(baseline != NULL, "deferred baseline GObj creation") ||
        !check(
            HSD_GObj_SetupProc(baseline, record, 0) != NULL,
            "deferred baseline process setup") ||
        !check(
            pf_hsd_gobj_runtime_begin_deferred_process_capture() ==
                PF_HSD_GOBJ_RUNTIME_OK,
            "deferred capture begin failed")) {
        return 0;
    }
    deferred_first = GObj_Create(41, 1, 0);
    deferred_second = GObj_Create(42, 2, 0);
    if (!check(
            deferred_first != NULL && deferred_second != NULL,
            "deferred GObj creation") ||
        !check(
            HSD_GObj_SetupProc(deferred_first, record, 0) != NULL,
            "first deferred process setup") ||
        !check(
            HSD_GObj_SetupProc(deferred_second, record, 0) != NULL,
            "second deferred process setup") ||
        !check(
            pf_hsd_gobj_runtime_end_deferred_process_capture() ==
                PF_HSD_GOBJ_RUNTIME_OK,
            "deferred capture end failed") ||
        !check(
            pf_hsd_gobj_runtime_deferred_process_count() == 2,
            "deferred process inventory mismatch") ||
        !check(
            pf_hsd_gobj_runtime_finalize_initialization() ==
                PF_HSD_GOBJ_RUNTIME_OK,
            "deferred initialization finalization failed")) {
        return 0;
    }

    arena_after_setup = pf_hsd_obj_arena_bytes_used();
    HSD_GObj_80390CFC();
    if (!expect_trace(
            before_activation,
            sizeof(before_activation) / sizeof(before_activation[0])) ||
        !check(
            pf_hsd_gobj_runtime_activate_deferred_stage_start() ==
                PF_HSD_GOBJ_RUNTIME_OK,
            "deferred process activation failed") ||
        !check(
            pf_hsd_gobj_runtime_deferred_stage_start_is_active(),
            "deferred process activation state was not retained")) {
        return 0;
    }
    HSD_GObj_80390CFC();
    return expect_trace(
               after_activation,
               sizeof(after_activation) / sizeof(after_activation[0])) &&
        check(
               pf_hsd_obj_arena_bytes_used() == arena_after_setup,
               "deferred activation grew fixed object arena") &&
        check(
               pf_hsd_startup_arena_rejected_allocations() == 0,
               "deferred activation attempted startup allocation") &&
        check(
               pf_hsd_gobj_runtime_activate_deferred_stage_start() ==
                   PF_HSD_GOBJ_RUNTIME_DEFERRED_CAPTURE_STATE,
               "second deferred activation did not fail closed");
}

static int test_headless_go_banner_completion_timing(void)
{
    size_t arena_after_schedule;
    unsigned int frame;

    go_completion_count = 0;
    if (!reset_scheduler() ||
        !check(
            pf_ifStatus_headless_schedule_go_completion(record_go_completion),
            "headless GO completion setup failed")) {
        return 0;
    }
    arena_after_schedule = pf_hsd_obj_arena_bytes_used();
    for (frame = 1; frame < 40; ++frame) {
        HSD_GObj_80390CFC();
        if (!check(
                go_completion_count == 0,
                "headless GO completion fired before source frame")) {
            return 0;
        }
    }
    HSD_GObj_80390CFC();
    HSD_GObj_80390CFC();
    return check(
               go_completion_count == 1,
               "headless GO completion did not fire exactly once") &&
        check(
               !pf_ifStatus_headless_go_completion_failed(),
               "headless GO completion reported a scheduler failure") &&
        check(
               pf_hsd_obj_pool_used(&gobj_alloc_data) == 0 &&
                   pf_hsd_obj_pool_used(&gobjproc_alloc_data) == 0,
               "headless GO completion did not release its GObj and process") &&
        check(
               pf_hsd_obj_arena_bytes_used() == arena_after_schedule,
               "headless GO completion grew fixed object arena") &&
        check(
               pf_hsd_startup_arena_rejected_allocations() == 0,
               "headless GO completion attempted startup allocation");
}

int main(void)
{
    if (!test_priority_link_and_disable_order() ||
        !test_remove_current_process() ||
        !test_initialization_freeze_boundary() ||
        !test_slippi_frame_start_scheduler_boundary() ||
        !test_deferred_stage_start_processes() ||
        !test_headless_go_banner_completion_timing()) {
        return 1;
    }
    printf(
        "gobj-scheduler=pass source_units=7 object_pool=%u process_pool=%u "
        "ordering_cases=5\n",
        (unsigned) object_capacity,
        (unsigned) process_capacity);
    return 0;
}
