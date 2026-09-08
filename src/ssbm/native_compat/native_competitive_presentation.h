#ifndef PF_SSBM_NATIVE_COMPETITIVE_PRESENTATION_H
#define PF_SSBM_NATIVE_COMPETITIVE_PRESENTATION_H

#ifdef __cplusplus
extern "C" {
#endif

int pf_ifStatus_headless_initialize(void);
void pf_ifStatus_headless_respawn_reset(int slot);
int pf_ifStatus_headless_schedule_go_completion(void (*callback)(void));
int pf_ifStatus_headless_go_completion_failed(void);

#ifdef __cplusplus
}
#endif

#endif
