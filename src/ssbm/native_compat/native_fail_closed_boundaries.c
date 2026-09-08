#include "native_fail_closed_boundaries.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

#if defined(__clang__) || defined(__GNUC__)
#define PF_NORETURN __attribute__((noreturn))
#else
#define PF_NORETURN
#endif

char const* volatile pf_ssbm_last_unsupported_boundary;
char const* volatile pf_ssbm_last_unsupported_detail;
static PfSsbmUnsupportedBoundaryHandler pf_ssbm_unsupported_boundary_handler;

PF_NORETURN void pf_ssbm_reach_unsupported_boundary(const char* name)
{
    pf_ssbm_last_unsupported_boundary = name;
    if (pf_ssbm_unsupported_boundary_handler != NULL) {
        pf_ssbm_unsupported_boundary_handler(name);
    }
    abort();
}

void pf_ssbm_set_unsupported_boundary_handler(
    PfSsbmUnsupportedBoundaryHandler handler)
{
    pf_ssbm_unsupported_boundary_handler = handler;
}

#define PF_FAIL_CLOSED_BOUNDARY(name)                                         \
    PF_NORETURN void name(void);                                              \
    PF_NORETURN void name(void)                                               \
    {                                                                         \
        pf_ssbm_reach_unsupported_boundary(#name);                            \
    }

/* Platform services that must be replaced by asset-pack or deterministic
 * native services before the original match root may execute them. */
PF_FAIL_CLOSED_BOUNDARY(ARQPostRequest)
bool AXDriverKeyOff(int voice)
{
    (void) voice;
    return false;
}
bool AXDriverStop(void)
{
    return false;
}
int AXDriver_8038CFF4(
    int sound_id,
    unsigned char volume,
    unsigned char pan,
    int track,
    int channel)
{
    (void) sound_id;
    (void) volume;
    (void) pan;
    (void) track;
    (void) channel;
    return -1;
}
bool AXDriver_8038D2B4(int voice, unsigned char pan)
{
    (void) voice;
    (void) pan;
    return false;
}
bool AXDriver_8038D3B8(int voice, unsigned char volume)
{
    (void) voice;
    (void) volume;
    return false;
}
bool AXDriver_8038D4E4(int voice, short pitch)
{
    (void) voice;
    (void) pitch;
    return false;
}
bool AXDriver_8038D9D8(int voice)
{
    (void) voice;
    return false;
}
bool AXDriver_8038E6C0(int channel)
{
    (void) channel;
    return false;
}
bool AXDriver_8038E844(int channel)
{
    (void) channel;
    return false;
}
PF_FAIL_CLOSED_BOUNDARY(AXDriver_8038E5D4)
PF_FAIL_CLOSED_BOUNDARY(AXDriver_8038E5DC)
bool AXDriver_8038E8EC(const char* path, unsigned char volume, int track)
{
    (void) path;
    (void) volume;
    (void) track;
    return true;
}
PF_FAIL_CLOSED_BOUNDARY(AXFreeVoice)
PF_FAIL_CLOSED_BOUNDARY(DVDClose)
int DVDConvertPathToEntrynum(const char* path)
{
    pf_ssbm_last_unsupported_detail = path;
    pf_ssbm_reach_unsupported_boundary("DVDConvertPathToEntrynum");
    return -1;
}
PF_FAIL_CLOSED_BOUNDARY(DVDFastOpen)
void HSD_AudioSFXKeyOffTrack(int track)
{
    (void) track;
}
void HSD_AudioSFXKeyOffAll(void) {}
PF_FAIL_CLOSED_BOUNDARY(HSD_DevComCancelEx)
PF_FAIL_CLOSED_BOUNDARY(HSD_DevComRequest)
PF_NORETURN void HSD_Panic(char* file, unsigned int line, char* message)
{
    static char detail[512];
    (void) snprintf(detail, sizeof(detail), "%s:%u: %s",
        file != NULL ? file : "<unknown>", line,
        message != NULL ? message : "");
    pf_ssbm_last_unsupported_detail = detail;
    pf_ssbm_reach_unsupported_boundary("HSD_Panic");
}
PF_FAIL_CLOSED_BOUNDARY(OSAllocFromHeap)
PF_FAIL_CLOSED_BOUNDARY(OSCheckHeap)
static int pf_ssbm_native_interrupts_enabled = 1;
int OSDisableInterrupts(void)
{
    const int previous = pf_ssbm_native_interrupts_enabled;
    pf_ssbm_native_interrupts_enabled = 0;
    return previous;
}
PF_FAIL_CLOSED_BOUNDARY(OSFreeToHeap)
PF_FAIL_CLOSED_BOUNDARY(OSGetTime)
int OSRestoreInterrupts(int level)
{
    const int previous = pf_ssbm_native_interrupts_enabled;
    pf_ssbm_native_interrupts_enabled = level != 0;
    return previous;
}
PF_FAIL_CLOSED_BOUNDARY(VIGetNextField)

/* Debug, menu, trophy, renderer, and particle-output boundaries. */
PF_FAIL_CLOSED_BOUNDARY(DevText_Create)
PF_FAIL_CLOSED_BOUNDARY(DevText_Erase)
PF_FAIL_CLOSED_BOUNDARY(DevText_HideBackground)
PF_FAIL_CLOSED_BOUNDARY(DevText_HideCursor)
PF_FAIL_CLOSED_BOUNDARY(DevText_HideText)
PF_FAIL_CLOSED_BOUNDARY(DevText_Printf)
PF_FAIL_CLOSED_BOUNDARY(DevText_SetBGColor)
PF_FAIL_CLOSED_BOUNDARY(DevText_SetCursorX)
PF_FAIL_CLOSED_BOUNDARY(DevText_SetCursorXY)
PF_FAIL_CLOSED_BOUNDARY(DevText_SetScale)
PF_FAIL_CLOSED_BOUNDARY(DevText_SetTextColor)
PF_FAIL_CLOSED_BOUNDARY(DevText_ShowBackground)
PF_FAIL_CLOSED_BOUNDARY(DevText_ShowText)
PF_FAIL_CLOSED_BOUNDARY(GXColor1u16)
PF_FAIL_CLOSED_BOUNDARY(GXColor1x16)
PF_FAIL_CLOSED_BOUNDARY(GXColor1x8)
PF_FAIL_CLOSED_BOUNDARY(GXColor3u8)
PF_FAIL_CLOSED_BOUNDARY(GXCopyTex)
PF_FAIL_CLOSED_BOUNDARY(GXInitFogAdjTable)
PF_FAIL_CLOSED_BOUNDARY(GXNormal3f32)
PF_FAIL_CLOSED_BOUNDARY(GXSetIndTexCoordScale)
PF_FAIL_CLOSED_BOUNDARY(GXSetIndTexMtx)
PF_FAIL_CLOSED_BOUNDARY(GXSetIndTexOrder)
PF_FAIL_CLOSED_BOUNDARY(GXSetNumIndStages)
PF_FAIL_CLOSED_BOUNDARY(GXSetTevClampMode)
PF_FAIL_CLOSED_BOUNDARY(GXSetTevDirect)
PF_FAIL_CLOSED_BOUNDARY(GXSetTevIndirect)
PF_FAIL_CLOSED_BOUNDARY(HSD_SisLib_803A945C)
PF_FAIL_CLOSED_BOUNDARY(Toy_803048C0)
PF_FAIL_CLOSED_BOUNDARY(Toy_803049F4)
PF_FAIL_CLOSED_BOUNDARY(Toy_80304A58)
PF_FAIL_CLOSED_BOUNDARY(Toy_80304B0C)
PF_FAIL_CLOSED_BOUNDARY(Toy_80304CC8)
PF_FAIL_CLOSED_BOUNDARY(Toy_80305058)
PF_FAIL_CLOSED_BOUNDARY(Toy_803060BC)
PF_FAIL_CLOSED_BOUNDARY(Toy_80306A48)
PF_FAIL_CLOSED_BOUNDARY(Toy_803124BC)
PF_FAIL_CLOSED_BOUNDARY(hsd_80391A04)
PF_FAIL_CLOSED_BOUNDARY(mn_8022F3D8)

/* These objects are zeroed state carriers. Any legal-match execution that
 * requires their presentation contents must be promoted above this boundary. */
unsigned int HSD_VIData[256];
void* Toy_sbss_804D6EAC;
void* Toy_sbss_804D6EB0;

/* These stage hooks are unreachable for the six accepted legal stages. */
PF_FAIL_CLOSED_BOUNDARY(grBigBlue_801EF7D8)
bool grBigBlue_801EF844(int line_id)
{
    (void) line_id;
    return false;
}
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2A6C)
PF_FAIL_CLOSED_BOUNDARY(grPushOn_80219204)
PF_FAIL_CLOSED_BOUNDARY(grCastle_801CDF54)
PF_FAIL_CLOSED_BOUNDARY(grCastle_801D0FF0)
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801DDCF0)
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2AF4)
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2B80)
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2C34)
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2D14)
bool grCorneria_801E2D90(int line_id)
{
    (void) line_id;
    return false;
}
PF_FAIL_CLOSED_BOUNDARY(grCorneria_801E2FCC)
PF_FAIL_CLOSED_BOUNDARY(grGarden_80203624)
PF_FAIL_CLOSED_BOUNDARY(grGreatBay_801F66A4)
PF_FAIL_CLOSED_BOUNDARY(grHomeRun_8021EF10)
PF_FAIL_CLOSED_BOUNDARY(grIceMt_801FA6D8)
PF_FAIL_CLOSED_BOUNDARY(grIceMt_801FA728)
bool grInishie1_801FCAAC(int line_id)
{
    (void) line_id;
    return false;
}
PF_FAIL_CLOSED_BOUNDARY(grInishie2_801FD448)
PF_FAIL_CLOSED_BOUNDARY(grInishie2_801FD4CC)
PF_FAIL_CLOSED_BOUNDARY(grKinokoRoute_802087B0)
PF_FAIL_CLOSED_BOUNDARY(grKongo_801D8058)
PF_FAIL_CLOSED_BOUNDARY(grKongo_801D8270)
PF_FAIL_CLOSED_BOUNDARY(grKongo_801D828C)
PF_FAIL_CLOSED_BOUNDARY(grOldKongo_802105AC)
PF_FAIL_CLOSED_BOUNDARY(grOldKongo_802105C8)
PF_FAIL_CLOSED_BOUNDARY(grRCruise_80201918)
PF_FAIL_CLOSED_BOUNDARY(grRCruise_80201988)
int grVenom_80206D10(int line_id)
{
    (void) line_id;
    return 0;
}
PF_FAIL_CLOSED_BOUNDARY(grZebes_801DCCC8)
