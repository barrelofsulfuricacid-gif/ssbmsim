#include "native_slippi.h"

#include "ft/types.h"
#include "gr/stage.h"

static bool slippi_neutral_spawns_enabled;
static bool slippi_online_enabled;
static bool slippi_frozen_stadium_enabled;
static bool slippi_stadium_preload_loaded;
static int slippi_stadium_preloaded_transformation;

extern int HSD_Randi(int maximum);

typedef struct PfSsbmNativeNeutralSpawn
{
    float x;
    float y;
} PfSsbmNativeNeutralSpawn;

typedef struct PfSsbmNativeStageNeutralSpawns
{
    int stage_kind;
    PfSsbmNativeNeutralSpawn singles[4];
    PfSsbmNativeNeutralSpawn teams[4];
} PfSsbmNativeStageNeutralSpawns;

/* project-slippi/slippi-ssbm-asm External/NeutralSpawn/NeutralSpawn.asm,
 * revision fcf47f10dc244152c2ebaa3a9dec142ea42243b7. Keep the source table
 * order and literals intact: these coordinates replace the ordinary stage
 * spawn points at the GALE01 0x8016E510 hook. */
static const PfSsbmNativeStageNeutralSpawns neutral_spawn_table[] = {
    { 0x20,
      { { -60.0F, 10.0F }, { 60.0F, 10.0F }, { -20.0F, 10.0F },
        { 20.0F, 10.0F } },
      { { -60.0F, 10.0F }, { -20.0F, 10.0F }, { 60.0F, 10.0F },
        { 20.0F, 10.0F } } },
    { 0x1F,
      { { -38.8F, 35.2F }, { 38.8F, 35.2F }, { 0.0F, 8.0F },
        { 0.0F, 62.4F } },
      { { -38.8F, 35.2F }, { -38.8F, 5.0F }, { 38.8F, 35.2F },
        { 38.8F, 5.0F } } },
    { 0x08,
      { { -42.0F, 26.6F }, { 42.0F, 28.0F }, { 0.0F, 46.9F },
        { 0.0F, 4.9F } },
      { { -42.0F, 26.6F }, { -42.0F, 5.0F }, { 42.0F, 28.0F },
        { 42.0F, 5.0F } } },
    { 0x1C,
      { { -46.6F, 37.2F }, { 47.4F, 37.3F }, { 0.0F, 7.0F },
        { 0.0F, 58.5F } },
      { { -46.6F, 37.2F }, { -46.6F, 5.0F }, { 47.4F, 37.3F },
        { 47.4F, 5.0F } } },
    { 0x02,
      { { -41.25F, 21.0F }, { 41.25F, 27.0F }, { 0.0F, 5.25F },
        { 0.0F, 48.0F } },
      { { -41.25F, 21.0F }, { -41.25F, 5.0F }, { 41.25F, 27.0F },
        { 41.25F, 5.0F } } },
    { 0x03,
      { { -40.0F, 32.0F }, { 40.0F, 32.0F }, { 70.0F, 7.0F },
        { -70.0F, 7.0F } },
      { { -40.0F, 32.0F }, { -40.0F, 5.0F }, { 40.0F, 32.0F },
        { 40.0F, 5.0F } } },
};

void pf_ssbm_native_slippi_configure(
    uint8_t neutral_spawns_enabled,
    uint8_t online_enabled)
{
    slippi_neutral_spawns_enabled = neutral_spawns_enabled;
    slippi_online_enabled = online_enabled;
}

void pf_ssbm_native_slippi_stadium_configure(uint8_t frozen_stadium_enabled)
{
    slippi_frozen_stadium_enabled = frozen_stadium_enabled;
    slippi_stadium_preload_loaded = false;
    slippi_stadium_preloaded_transformation = 5;
}

uint8_t pf_ssbm_native_slippi_whispy_excludes_fighter(int32_t motion_id)
{
    /* Slippi fcf47f10dc244152c2ebaa3a9dec142ea42243b7,
     * Online/Core/WhispyBlowDirFix/WhispyBlowDirFix.asm, 0x8008653C.
     * The signed comparison covers every death action, including star and
     * camera KOs. The caller must first preserve the original bone query. */
    return slippi_online_enabled && motion_id <= 0xB;
}

void pf_ssbm_native_slippi_stadium_mark_preloaded(void)
{
    slippi_stadium_preload_loaded = true;
}

void pf_ssbm_native_slippi_stadium_reset_preload(void)
{
    slippi_stadium_preload_loaded = false;
}

int pf_ssbm_native_slippi_stadium_preload(int current_transformation)
{
    /* project-slippi/slippi-ssbm-asm Common/Preload Stadium
     * Transformations/Core/Load Transformation.asm, revision
     * fcf47f10dc244152c2ebaa3a9dec142ea42243b7. The console hook executes at
     * GALE01 0x801D45EC before the original Stadium case-0 decrement. Its
     * asynchronous DAT request is already satisfied by the resident native
     * asset pack, but its chosen transform and gameplay RNG draw remain
     * observable. */
    static const int transformations[] = { 3, 4, 9, 6 };

    if (!slippi_stadium_preload_loaded) {
        do {
            slippi_stadium_preloaded_transformation =
                transformations[HSD_Randi(4)];
        } while (slippi_stadium_preloaded_transformation ==
                 current_transformation);
        slippi_stadium_preload_loaded = true;
    }
    return slippi_stadium_preloaded_transformation;
}

uint8_t pf_ssbm_native_slippi_stadium_is_frozen(void)
{
    return slippi_frozen_stadium_enabled;
}

uint8_t pf_ssbm_native_slippi_stadium_monitor(
    const Fighter* fighter,
    HSD_GObj* stage_gobj,
    PfSsbmNativeStadiumMonitorPredicate vanilla_predicate)
{
    /* project-slippi/slippi-ssbm-asm
     * Common/PSCameraIndependentMonitor/PSCameraIndependentMonitor.asm,
     * revision fcf47f10dc244152c2ebaa3a9dec142ea42243b7. The hook at
     * GALE01 0x801D24FC preserves the replaced function call because it
     * updates the jumbotron image position, then replaces only its
     * camera-dependent transition result with inclusive world bounds. */
    (void) vanilla_predicate(stage_gobj);

    if (fighter->cur_pos.x < -120.0F || fighter->cur_pos.x > 120.0F ||
        fighter->cur_pos.y > 80.0F || fighter->cur_pos.y < -20.0F) {
        return false;
    }
    return true;
}

uint8_t pf_ssbm_native_slippi_neutral_spawn(
    int stage_kind,
    uint8_t is_teams,
    unsigned int spawn_order,
    float* out_x,
    float* out_y,
    float* out_facing)
{
    unsigned int stage_index;

    if (!slippi_neutral_spawns_enabled || spawn_order >= 4 || out_x == NULL ||
        out_y == NULL || out_facing == NULL) {
        return false;
    }
    for (stage_index = 0;
         stage_index <
         sizeof(neutral_spawn_table) / sizeof(neutral_spawn_table[0]);
         ++stage_index) {
        const PfSsbmNativeStageNeutralSpawns* stage =
            &neutral_spawn_table[stage_index];
        const PfSsbmNativeNeutralSpawn* spawn;
        if (stage->stage_kind != stage_kind) {
            continue;
        }
        spawn = is_teams ? &stage->teams[spawn_order]
                         : &stage->singles[spawn_order];
        *out_x = spawn->x;
        *out_y = spawn->y;
        *out_facing = spawn->x <= 0.0F ? 1.0F : -1.0F;
        return true;
    }
    return false;
}

int pf_ssbm_native_slippi_brawl_offscreen_damage(
    const Fighter* fp,
    PfSsbmNativeMagnifyPredicate vanilla_predicate)
{
    if (!slippi_online_enabled) {
        return vanilla_predicate(fp->player_id) != 0;
    }

    // project-slippi/slippi-ssbm-asm Online/Core/BrawlOffscreenDamage.asm,
    // revision fcf47f10dc244152c2ebaa3a9dec142ea42243b7. The upstream
    // Home-Run Contest exemption cannot be reached because native match
    // admission accepts competitive legal stages only.
    if (fp->x221F_b1 || fp->motion_id == 4 || fp->motion_id == 6) {
        return false;
    }
    if (fp->cur_pos.x < Stage_GetCamBoundsLeftOffset()) {
        return true;
    }
    if (fp->cur_pos.x > Stage_GetCamBoundsRightOffset()) {
        return true;
    }
    if (fp->cur_pos.y > Stage_GetCamBoundsTopOffset()) {
        return true;
    }
    if (fp->cur_pos.y < Stage_GetCamBoundsBottomOffset()) {
        return true;
    }
    return false;
}
