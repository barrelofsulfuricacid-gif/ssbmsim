#ifndef PF_SSBM_NATIVE_STAGE_ASSETS_API_H
#define PF_SSBM_NATIVE_STAGE_ASSETS_API_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PfSsbmNativeStageAssets {
    void* archive_token;
    void* map_head;
    void* collision;
    void* ground_param;
    void* item_data;
    void* yakumono_param;
    void* map_particles;
    void* map_textures;
    void* quake_model_set;
} PfSsbmNativeStageAssets;

int pf_ssbm_native_stage_require(
    const char* disc_path,
    PfSsbmNativeStageAssets* assets);
void* pf_ssbm_native_stage_ground_param_require(const char* disc_path);
void* pf_ssbm_native_stage_collision_require(const char* disc_path);

#ifdef __cplusplus
}
#endif

#endif
