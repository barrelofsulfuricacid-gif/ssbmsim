#include "native_pad_input.h"
#include "native_numeric.h"

#include "baselib/controller.h"
#include "melee/ft/types.h"

#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <string.h>

static int8_t raw_main_x_current[PF_SSBM_NATIVE_PAD_COUNT];
static int8_t raw_main_x_previous[PF_SSBM_NATIVE_PAD_COUNT];
static int8_t raw_main_x_two_frames_ago[PF_SSBM_NATIVE_PAD_COUNT];
static int8_t raw_main_y_current[PF_SSBM_NATIVE_PAD_COUNT];
static int8_t raw_main_y_previous[PF_SSBM_NATIVE_PAD_COUNT];
static int8_t raw_main_y_two_frames_ago[PF_SSBM_NATIVE_PAD_COUNT];
static uint8_t ucf084_shield_drop_buffer[PF_SSBM_NATIVE_PAD_COUNT];

static int raw_axis_magnitude(s8 axis)
{
    return axis < 0 ? -(int) axis : (int) axis;
}

static u8 normalized_trigger_byte(float value)
{
    if (!(value > 0.0F)) {
        return 0;
    }
    if (value >= 1.0F) {
        return 0xFF;
    }
    return (u8) (value * 255.0F + 0.5F);
}

static void apply_sample(
    HSD_PadStatus* status,
    const PfSsbmNativePadSample* sample,
    u32 previous_buttons)
{
    const u32 changed = previous_buttons ^ sample->buttons;

    status->last_button = previous_buttons;
    status->button = sample->buttons;
    status->trigger = sample->buttons & changed;
    status->release = previous_buttons & changed;
    status->repeat = status->trigger;
    status->repeat_count = 0;
    status->stickX = sample->raw_main_x;
    status->stickY = sample->raw_main_y;
    status->subStickX = sample->raw_c_x;
    status->subStickY = sample->raw_c_y;
    status->analogL = normalized_trigger_byte(sample->left_trigger);
    status->analogR = normalized_trigger_byte(sample->right_trigger);
    status->analogA = 0;
    status->analogB = 0;
    status->nml_stickX = sample->main_x;
    status->nml_stickY = sample->main_y;
    status->nml_subStickX = sample->c_x;
    status->nml_subStickY = sample->c_y;
    status->nml_analogL = sample->left_trigger;
    status->nml_analogR = sample->right_trigger;
    status->nml_analogA = 0.0F;
    status->nml_analogB = 0.0F;
    status->cross_dir = 0;
    status->err = 0;
}

void pf_ssbm_native_pad_reset(void)
{
    memset(HSD_PadMasterStatus, 0, sizeof(HSD_PadMasterStatus));
    memset(HSD_PadCopyStatus, 0, sizeof(HSD_PadCopyStatus));
    memset(HSD_PadGameStatus, 0, sizeof(HSD_PadGameStatus));
    memset(raw_main_x_current, 0, sizeof(raw_main_x_current));
    memset(raw_main_x_previous, 0, sizeof(raw_main_x_previous));
    memset(raw_main_x_two_frames_ago, 0, sizeof(raw_main_x_two_frames_ago));
    memset(raw_main_y_current, 0, sizeof(raw_main_y_current));
    memset(raw_main_y_previous, 0, sizeof(raw_main_y_previous));
    memset(raw_main_y_two_frames_ago, 0, sizeof(raw_main_y_two_frames_ago));
    memset(ucf084_shield_drop_buffer, 0, sizeof(ucf084_shield_drop_buffer));
}

void pf_ssbm_native_apply_pad_samples(
    const PfSsbmNativePadSample samples[PF_SSBM_NATIVE_PAD_COUNT])
{
    size_t index;

    for (index = 0; index < PF_SSBM_NATIVE_PAD_COUNT; ++index) {
        const u32 previous_buttons = HSD_PadGameStatus[index].button;
        raw_main_x_two_frames_ago[index] = raw_main_x_previous[index];
        raw_main_x_previous[index] = raw_main_x_current[index];
        raw_main_x_current[index] = samples[index].raw_main_x;
        raw_main_y_two_frames_ago[index] = raw_main_y_previous[index];
        raw_main_y_previous[index] = raw_main_y_current[index];
        raw_main_y_current[index] = samples[index].raw_main_y;
        apply_sample(
            &HSD_PadMasterStatus[index], &samples[index], previous_buttons);
        apply_sample(
            &HSD_PadCopyStatus[index], &samples[index], previous_buttons);
        apply_sample(
            &HSD_PadGameStatus[index], &samples[index], previous_buttons);
    }
}

int pf_ssbm_native_ucf084_raw_main_x_delta_two_frames(uint8_t port)
{
    if (port >= PF_SSBM_NATIVE_PAD_COUNT) {
        return 0;
    }
    return (int) raw_main_x_current[port] -
           (int) raw_main_x_two_frames_ago[port];
}

int pf_ssbm_native_ucf084_raw_main_x_delta_squared_two_frames(uint8_t port)
{
    const int delta = pf_ssbm_native_ucf084_raw_main_x_delta_two_frames(port);
    return delta * delta;
}

int pf_ssbm_native_ucf084_raw_main_delta_squared_two_frames(uint8_t port)
{
    int delta_x;
    int delta_y;

    if (port >= PF_SSBM_NATIVE_PAD_COUNT) {
        return 0;
    }
    delta_x = (int) raw_main_x_current[port] -
              (int) raw_main_x_two_frames_ago[port];
    delta_y = (int) raw_main_y_current[port] -
              (int) raw_main_y_two_frames_ago[port];
    return delta_x * delta_x + delta_y * delta_y;
}

int pf_ssbm_native_ucf084_shield_drop_radial_qualifies(
    float main_x,
    float main_y)
{
    const float abs_x = main_x < 0.0F ? -main_x : main_x;
    const float abs_y = main_y < 0.0F ? -main_y : main_y;
    const int adjusted_x = (int) PF_SlippiMulAddF32(abs_x, 80.0F, -0.0001F) + 2;
    const int adjusted_y = (int) PF_SlippiMulAddF32(abs_y, 80.0F, -0.0001F) + 2;

    return adjusted_x * adjusted_x + adjusted_y * adjusted_y > 80 * 80;
}

void pf_ssbm_native_ucf084_apply_input_hook(Fighter* fighter)
{
    HSD_PadStatus* pad;
    uint8_t port;
    uint8_t shield_drop_count;
    s8 raw_x;
    s8 raw_y;

    if (fighter == NULL || fighter->x618_player_id >= PF_SSBM_NATIVE_PAD_COUNT) {
        return;
    }
    port = fighter->x618_player_id;
    pad = &HSD_PadGameStatus[port];
    raw_x = pad->stickX;
    raw_y = pad->stickY;
    if (raw_axis_magnitude(raw_x) >= 80 &&
        raw_axis_magnitude(raw_y) <= 6)
    {
        fighter->input.lstick[0].x = raw_x < 0 ? -1.0F : 1.0F;
        fighter->input.lstick[0].y = 0.0F;
    } else if (raw_axis_magnitude(raw_y) >= 80 &&
               raw_axis_magnitude(raw_x) <= 6)
    {
        fighter->input.lstick[0].x = 0.0F;
        fighter->input.lstick[0].y = raw_y < 0 ? -1.0F : 1.0F;
    }

    raw_x = pad->subStickX;
    raw_y = pad->subStickY;
    if (raw_axis_magnitude(raw_x) >= 80 &&
        raw_axis_magnitude(raw_y) <= 6)
    {
        fighter->input.cstick[0].x = raw_x < 0 ? -1.0F : 1.0F;
        fighter->input.cstick[0].y = 0.0F;
    } else if (raw_axis_magnitude(raw_y) >= 80 &&
               raw_axis_magnitude(raw_x) <= 6)
    {
        fighter->input.cstick[0].x = 0.0F;
        fighter->input.cstick[0].y = raw_y < 0 ? -1.0F : 1.0F;
    }

    /*
     * Exact source-level translation of project-slippi/slippi-ssbm-asm
     * fcf47f10 External/UCF 0.84/UCF/UCF Pad Buffer + 1.0 Cardinals.asm
     * at GALE01 0x8006B460. The original C2 body owns a one-byte counter per
     * hardware port at scratch offset port * 12 + 9. It clears the counter
     * outside the shield-drop band, starts it only on a fresh raw-Y motion
     * whose two-frame squared delta is strictly greater than 44^2, and then
     * increments it once per qualifying fighter-input update.
     */
    shield_drop_count = 0;
    if (fighter->input.lstick[0].y <= -0.609375F &&
        pf_ssbm_native_ucf084_shield_drop_radial_qualifies(
            fighter->input.lstick[0].x, fighter->input.lstick[0].y))
    {
        shield_drop_count = ucf084_shield_drop_buffer[port];
        if (shield_drop_count != 0 ||
            (fighter->x671_timer_lstick_tilt_y <= 1 &&
             ((int) raw_main_y_current[port] -
              (int) raw_main_y_two_frames_ago[port]) *
                     ((int) raw_main_y_current[port] -
                      (int) raw_main_y_two_frames_ago[port]) >
                 44 * 44))
        {
            shield_drop_count = (uint8_t) (shield_drop_count + 1U);
        }
    }
    ucf084_shield_drop_buffer[port] = shield_drop_count;
}

uint8_t pf_ssbm_native_ucf084_shield_drop_buffer_count(uint8_t port)
{
    if (port >= PF_SSBM_NATIVE_PAD_COUNT) {
        return 0;
    }
    return ucf084_shield_drop_buffer[port];
}

/*
 * Exact host translation of the pinned UCF 0.84 "DBOOC SquatRv Fix" hook at
 * GALE01 0x800D65EC (slippi-ssbm-asm "External/UCF 0.84/UCF/UCF DBOOC
 * SquatRv Fix.asm"). The hook replaces the vanilla ftCo_SquatRv_CheckInput
 * threshold load (lfs f0, 0x94(r4), verified against the owner disc) with a
 * body that keeps p_ftCommonData->x94 unless the stick tilt on X is fresh
 * this frame (unsigned x670 byte < 1) and the adjusted radial position
 * qualifies, in which case the release threshold relaxes to 0.59
 * (payload word 0x3F170A3D). The radial adjustment (|v| * 80 - 0.0001,
 * truncated toward zero, plus 2, compared against 80 * 80) is the same
 * integer program as the UCF shield-drop radial, reproduced here with its
 * own provenance so each hook translation stands alone.
 */
int pf_ssbm_native_ucf084_dbooc_radial_qualifies(
    float main_x,
    float main_y)
{
    const float abs_x = main_x < 0.0F ? -main_x : main_x;
    const float abs_y = main_y < 0.0F ? -main_y : main_y;
    const int adjusted_x = (int) PF_SlippiMulAddF32(abs_x, 80.0F, -0.0001F) + 2;
    const int adjusted_y = (int) PF_SlippiMulAddF32(abs_y, 80.0F, -0.0001F) + 2;

    return adjusted_x * adjusted_x + adjusted_y * adjusted_y > 80 * 80;
}

float pf_ssbm_native_ucf084_dbooc_squatrv_release_threshold(
    const Fighter* fighter,
    float vanilla_threshold)
{
    if (
        fighter != NULL && fighter->x670_timer_lstick_tilt_x < 1 &&
        pf_ssbm_native_ucf084_dbooc_radial_qualifies(
            fighter->input.lstick[0].x, fighter->input.lstick[0].y))
    {
        return 0.59F;
    }
    return vanilla_threshold;
}
