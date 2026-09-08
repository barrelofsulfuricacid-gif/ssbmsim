#ifndef PF_SSBM_NATIVE_FIGHTER_STATE_H
#define PF_SSBM_NATIVE_FIGHTER_STATE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PfSsbmNativeFighterState {
    uint8_t present;
    int32_t action_state_id;
    float position_x;
    float position_y;
    float facing_direction;
    float damage_percent;
    float shield_health;
    float self_velocity_x;
    float self_velocity_y;
    float attack_velocity_x;
    float attack_velocity_y;
    float hitlag_remaining;
    float animation_frame;
    uint16_t ground_id;
    uint16_t ground_id_reserved;
    int32_t stocks_remaining;
    uint8_t jumps_remaining;
    uint8_t is_airborne;
    uint8_t reserved[2];
} PfSsbmNativeFighterState;

uint8_t pf_ssbm_native_read_fighter_state(
    uint32_t player_index,
    PfSsbmNativeFighterState* state);

uint8_t pf_ssbm_native_read_subfighter_state(
    uint32_t player_index,
    PfSsbmNativeFighterState* state);

#ifdef __cplusplus
}
#endif

#endif
