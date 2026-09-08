#include "ft/types.h"
#include "lb/types.h"

#include <stdint.h>
#include <stdio.h>

typedef union RawCommandWord {
    uint32_t alignment;
    unsigned char bytes[4];
} RawCommandWord;

static RawCommandWord raw_word(uint32_t value)
{
    RawCommandWord result;
    result.bytes[0] = (unsigned char) (value >> 24U);
    result.bytes[1] = (unsigned char) (value >> 16U);
    result.bytes[2] = (unsigned char) (value >> 8U);
    result.bytes[3] = (unsigned char) value;
    return result;
}

int main(void)
{
    const RawCommandWord timer = raw_word((2U << 26U) | 2U);
    const RawCommandWord hurt =
        raw_word((0x1CU << 26U) | (3U << 18U) | 0x1010U);
    const RawCommandWord pair = raw_word(0x1234FEDCU);
    const RawCommandWord gfx_pair = raw_word(0x04071234U);
    const RawCommandWord signed_pair = raw_word(0x80017FFFU);
    const RawCommandWord byte_pair = raw_word(0x12345678U);
    const RawCommandWord unk_fx = raw_word(0xDEAD0407U);
    const RawCommandWord color = raw_word(12U << 26U);
    const struct Command_02* timer_command =
        (const struct Command_02*) timer.bytes;
    const struct gmScriptEventDefault* event =
        (const struct gmScriptEventDefault*) timer.bytes;
    const struct set_hurt_state* hurt_command =
        (const struct set_hurt_state*) hurt.bytes;
    const struct spawn_gfx_2* pair_command =
        (const struct spawn_gfx_2*) pair.bytes;
    const struct spawn_gfx_1* gfx_pair_command =
        (const struct spawn_gfx_1*) gfx_pair.bytes;
    const struct spawn_hitbox_1* hitbox_pair_command =
        (const struct spawn_hitbox_1*) pair.bytes;
    const struct spawn_hitbox_2* signed_pair_command =
        (const struct spawn_hitbox_2*) signed_pair.bytes;
    const struct sound_effect_2* sound_command =
        (const struct sound_effect_2*) byte_pair.bytes;
    const struct stage_sfx_2* stage_pair_command =
        (const struct stage_sfx_2*) pair.bytes;
    const struct stage_sfx_3* stage_bytes_command =
        (const struct stage_sfx_3*) byte_pair.bytes;
    const struct unk_fx_0* unk_fx_command =
        (const struct unk_fx_0*) unk_fx.bytes;
    const union ColorOverlay_x8_t* color_command =
        (const union ColorOverlay_x8_t*) color.bytes;
    union CmdUnion pointer_command;
    RawCommandWord materialized_pointer;
    struct MotionState motion_state = {
        .anim_id = 0,
        .x4_flags = 0,
        ._ = UINT32_C(0x13A55AC3),
    };
    void* const expected_pointer = (void*) (uintptr_t) 0x12345678U;

    pointer_command.Command_05.ptr = expected_pointer;
    materialized_pointer.alignment = (uint32_t) (uintptr_t) expected_pointer;
    if (timer_command->code != 2U || timer_command->value != 2U ||
        event->opcode != 2U || event->value1 != 2U ||
        hurt_command->opcode != 0x1CU || hurt_command->bone_idx != 3U ||
        hurt_command->state != 0x1010U ||
        pair_command->offsetZ != (int16_t) 0x1234 ||
        pair_command->offsetY != (int16_t) 0xFEDC ||
        gfx_pair_command->gfxID != UINT16_C(0x0407) ||
        gfx_pair_command->unkFloat != UINT16_C(0x1234) ||
        hitbox_pair_command->size != UINT16_C(0x1234) ||
        hitbox_pair_command->z_offset != (int16_t) 0xFEDC ||
        signed_pair_command->y_offset != (int16_t) 0x8001 ||
        signed_pair_command->x_offset != (int16_t) 0x7FFF ||
        sound_command->padding != UINT16_C(0x1234) ||
        sound_command->volume != UINT8_C(0x56) ||
        sound_command->panning != UINT8_C(0x78) ||
        stage_pair_command->x0_b0_15 != UINT16_C(0x1234) ||
        stage_pair_command->x2_b0_15 != UINT16_C(0xFEDC) ||
        stage_bytes_command->x0_b0_15 != UINT16_C(0x1234) ||
        stage_bytes_command->x2_b0_7 != UINT8_C(0x56) ||
        stage_bytes_command->x3_b0_7 != UINT8_C(0x78) ||
        (((uint16_t) unk_fx_command->x2_b0_7 << 8U) |
         unk_fx_command->x3_b0_7) != UINT16_C(0x0407) ||
        color_command->unk.unk != 12U || color_command->unk.timer != 0U ||
        motion_state.move_id != UINT8_C(0x13) ||
        !motion_state.x9_b0 || motion_state.x9_b1 ||
        !motion_state.x9_b2 || motion_state.x9_b3 ||
        motion_state.x9_b4 || !motion_state.x9_b5 ||
        motion_state.x9_b6 || !motion_state.x9_b7 ||
        motion_state.xA != UINT8_C(0x5A) ||
        motion_state.xB != UINT8_C(0xC3) ||
        pointer_command.Command_05.ptr != expected_pointer ||
        ((const struct Command_05*) materialized_pointer.bytes)->ptr !=
            expected_pointer ||
        ((const struct Command_07*) materialized_pointer.bytes)->ptr !=
            expected_pointer) {
        fprintf(stderr,
                "native-command-layout=fail timer=%u/%u event=%u/%u "
                "hurt=%u/%u/%u pair=%d/%d gfx=%u/%u hitbox=%u/%d "
                "sound=%u/%u/%u stage=%u/%u/%u/%u/%u color=%u/%u "
                "motion=%u/%u/%u pointer=%p\n",
                timer_command->code, timer_command->value,
                event->opcode, event->value1,
                hurt_command->opcode, hurt_command->bone_idx,
                hurt_command->state, pair_command->offsetZ,
                pair_command->offsetY, gfx_pair_command->gfxID,
                gfx_pair_command->unkFloat, hitbox_pair_command->size,
                hitbox_pair_command->z_offset, sound_command->padding,
                sound_command->volume, sound_command->panning,
                stage_pair_command->x0_b0_15,
                stage_pair_command->x2_b0_15,
                stage_bytes_command->x0_b0_15,
                stage_bytes_command->x2_b0_7,
                stage_bytes_command->x3_b0_7, color_command->unk.unk,
                color_command->unk.timer, motion_state.move_id,
                motion_state.xA, motion_state.xB,
                ((const struct Command_07*) materialized_pointer.bytes)->ptr);
        return 1;
    }
    puts("native-command-layout=pass words=4 motion=1 pointer=1");
    return 0;
}
