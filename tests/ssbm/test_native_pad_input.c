#include "native_pad_input.h"
#include "native_rng.h"

#include "baselib/controller.h"
#include "baselib/random.h"
#include "melee/ft/types.h"

#include <stdio.h>
#include <string.h>

static int status_matches(
    const HSD_PadStatus* status,
    const PfSsbmNativePadSample* sample,
    u32 previous,
    u32 trigger,
    u32 release)
{
    return status->button == sample->buttons &&
           status->last_button == previous && status->trigger == trigger &&
           status->release == release && status->repeat == trigger &&
           status->stickX == sample->raw_main_x &&
           status->stickY == sample->raw_main_y &&
           status->subStickX == sample->raw_c_x &&
           status->subStickY == sample->raw_c_y &&
           status->nml_stickX == sample->main_x &&
           status->nml_stickY == sample->main_y &&
           status->nml_subStickX == sample->c_x &&
           status->nml_subStickY == sample->c_y &&
           status->nml_analogL == sample->left_trigger &&
           status->nml_analogR == sample->right_trigger && status->err == 0;
}

int main(void)
{
    Fighter fighter;
    PfSsbmNativePadSample samples[PF_SSBM_NATIVE_PAD_COUNT];
    const u32 first_buttons = HSD_PAD_A | HSD_PAD_L;
    const u32 second_buttons = HSD_PAD_B | HSD_PAD_R;
    const u32 initial_seed = 0x12345678U;
    const u32 expected_seed = initial_seed * 214013U + 2531011U;

    pf_ssbm_native_pad_reset();
    memset(&fighter, 0, sizeof(fighter));
    memset(samples, 0, sizeof(samples));
    samples[0].buttons = first_buttons;
    samples[0].main_x = 0.75F;
    samples[0].main_y = -0.5F;
    samples[0].c_x = -0.25F;
    samples[0].c_y = 1.0F;
    samples[0].left_trigger = 0.5F;
    samples[0].right_trigger = 0.25F;
    samples[0].raw_main_x = 72;
    samples[0].raw_main_y = -48;
    samples[0].raw_c_x = -24;
    samples[0].raw_c_y = 96;
    pf_ssbm_native_apply_pad_samples(samples);

    if (!status_matches(
            &HSD_PadMasterStatus[0], &samples[0], 0, first_buttons, 0) ||
        !status_matches(
            &HSD_PadCopyStatus[0], &samples[0], 0, first_buttons, 0) ||
        !status_matches(
            &HSD_PadGameStatus[0], &samples[0], 0, first_buttons, 0) ||
        HSD_PadGameStatus[0].analogL != 128 ||
        HSD_PadGameStatus[0].analogR != 64) {
        fputs("native-pad-input=first-frame-fail\n", stderr);
        return 1;
    }

    samples[0].buttons = second_buttons;
    pf_ssbm_native_apply_pad_samples(samples);
    if (!status_matches(
            &HSD_PadGameStatus[0], &samples[0], first_buttons,
            second_buttons, first_buttons) ||
        HSD_PadMasterStatus[1].button != 0 ||
        HSD_PadCopyStatus[1].trigger != 0 ||
        HSD_PadGameStatus[1].release != 0) {
        fputs("native-pad-input=edge-fail\n", stderr);
        return 1;
    }

    samples[0].raw_main_x = -20;
    pf_ssbm_native_apply_pad_samples(samples);
    if (pf_ssbm_native_ucf084_raw_main_x_delta_two_frames(0) != -92 ||
        pf_ssbm_native_ucf084_raw_main_x_delta_two_frames(
            PF_SSBM_NATIVE_PAD_COUNT) != 0) {
        fputs("native-pad-input=ucf-history-fail\n", stderr);
        return 1;
    }

    HSD_PadGameStatus[0].stickX = 94;
    HSD_PadGameStatus[0].stickY = 6;
    HSD_PadGameStatus[0].subStickX = -6;
    HSD_PadGameStatus[0].subStickY = -80;
    fighter.x618_player_id = 0;
    fighter.input.lstick[0].x = 0.9875F;
    fighter.input.lstick[0].y = 0.075F;
    fighter.input.cstick[0].x = -0.075F;
    fighter.input.cstick[0].y = 0.9875F;
    pf_ssbm_native_ucf084_apply_input_hook(&fighter);
    if (fighter.input.lstick[0].x != 1.0F ||
        fighter.input.lstick[0].y != 0.0F ||
        fighter.input.cstick[0].x != 0.0F ||
        fighter.input.cstick[0].y != -1.0F)
    {
        fputs("native-pad-input=ucf-cardinal-snap-fail\n", stderr);
        return 1;
    }

    HSD_PadGameStatus[0].stickX = 79;
    HSD_PadGameStatus[0].stickY = 6;
    fighter.input.lstick[0].x = 0.9875F;
    fighter.input.lstick[0].y = 0.075F;
    pf_ssbm_native_ucf084_apply_input_hook(&fighter);
    if (fighter.input.lstick[0].x != 0.9875F ||
        fighter.input.lstick[0].y != 0.075F)
    {
        fputs("native-pad-input=ucf-cardinal-boundary-fail\n", stderr);
        return 1;
    }

    if (!pf_ssbm_native_ucf084_shield_drop_radial_qualifies(
            0.675F, -0.725F) ||
        pf_ssbm_native_ucf084_shield_drop_radial_qualifies(
            0.6875F, -0.7F))
    {
        fputs("native-pad-input=ucf-shield-drop-radial-fail\n", stderr);
        return 1;
    }

    pf_ssbm_native_pad_reset();
    memset(&fighter, 0, sizeof(fighter));
    memset(samples, 0, sizeof(samples));
    fighter.x618_player_id = 0;
    fighter.x671_timer_lstick_tilt_y = 1;
    fighter.input.lstick[0].x = 0.7625F;
    fighter.input.lstick[0].y = -0.625F;
    samples[0].main_x = fighter.input.lstick[0].x;
    samples[0].main_y = fighter.input.lstick[0].y;
    samples[0].raw_main_x = 61;
    samples[0].raw_main_y = -50;
    pf_ssbm_native_apply_pad_samples(samples);
    pf_ssbm_native_ucf084_apply_input_hook(&fighter);
    if (pf_ssbm_native_ucf084_shield_drop_buffer_count(0) != 1) {
        fputs("native-pad-input=ucf-shield-drop-buffer-start-fail\n", stderr);
        return 1;
    }
    pf_ssbm_native_apply_pad_samples(samples);
    pf_ssbm_native_ucf084_apply_input_hook(&fighter);
    if (pf_ssbm_native_ucf084_shield_drop_buffer_count(0) != 2 ||
        pf_ssbm_native_ucf084_shield_drop_buffer_count(
            PF_SSBM_NATIVE_PAD_COUNT) != 0)
    {
        fputs("native-pad-input=ucf-shield-drop-buffer-extend-fail\n", stderr);
        return 1;
    }

    pf_ssbm_native_pad_reset();
    fighter.x671_timer_lstick_tilt_y = 1;
    samples[0].raw_main_y = -44;
    pf_ssbm_native_apply_pad_samples(samples);
    pf_ssbm_native_ucf084_apply_input_hook(&fighter);
    if (pf_ssbm_native_ucf084_shield_drop_buffer_count(0) != 0) {
        fputs("native-pad-input=ucf-shield-drop-buffer-boundary-fail\n", stderr);
        return 1;
    }

    pf_ssbm_native_rng_set(initial_seed);
    (void) HSD_Rand();
    if (pf_ssbm_native_rng_get() != expected_seed) {
        fputs("native-pad-input=rng-fail\n", stderr);
        return 1;
    }

    puts("native-pad-input=pass players=4 edges=2 raw-axes=4 "
         "ucf-history=1 ucf-cardinals=2 ucf-shield-drop=2 rng=1");
    return 0;
}
