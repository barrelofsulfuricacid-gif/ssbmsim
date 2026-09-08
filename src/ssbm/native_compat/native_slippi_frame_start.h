#ifndef PF_SSBM_NATIVE_SLIPPI_FRAME_START_H
#define PF_SSBM_NATIVE_SLIPPI_FRAME_START_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void pf_ssbm_native_slippi_frame_start_reset(void);
void pf_ssbm_native_slippi_frame_start_install(void);
uint8_t pf_ssbm_native_slippi_frame_start_installed(void);
void pf_ssbm_native_slippi_frame_start_begin_frame(void);
uint8_t pf_ssbm_native_slippi_frame_start_take(uint32_t* out_seed);

#ifdef __cplusplus
}
#endif

#endif
