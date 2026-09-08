#ifndef PF_SSBM_NATIVE_PAD_INPUT_H
#define PF_SSBM_NATIVE_PAD_INPUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { PF_SSBM_NATIVE_PAD_COUNT = 4 };

struct Fighter;

typedef struct PfSsbmNativePadSample {
    uint32_t buttons;
    float main_x;
    float main_y;
    float c_x;
    float c_y;
    float left_trigger;
    float right_trigger;
    int8_t raw_main_x;
    int8_t raw_main_y;
    int8_t raw_c_x;
    int8_t raw_c_y;
} PfSsbmNativePadSample;

void pf_ssbm_native_pad_reset(void);

void pf_ssbm_native_apply_pad_samples(
    const PfSsbmNativePadSample samples[PF_SSBM_NATIVE_PAD_COUNT]);

int pf_ssbm_native_ucf084_raw_main_x_delta_two_frames(uint8_t port);

int pf_ssbm_native_ucf084_raw_main_x_delta_squared_two_frames(uint8_t port);

int pf_ssbm_native_ucf084_raw_main_delta_squared_two_frames(uint8_t port);

int pf_ssbm_native_ucf084_shield_drop_radial_qualifies(
    float main_x,
    float main_y);

int pf_ssbm_native_ucf084_dbooc_radial_qualifies(
    float main_x,
    float main_y);

float pf_ssbm_native_ucf084_dbooc_squatrv_release_threshold(
    const struct Fighter* fighter,
    float vanilla_threshold);

void pf_ssbm_native_ucf084_apply_input_hook(struct Fighter* fighter);

uint8_t pf_ssbm_native_ucf084_shield_drop_buffer_count(uint8_t port);

#ifdef __cplusplus
}
#endif

#endif
