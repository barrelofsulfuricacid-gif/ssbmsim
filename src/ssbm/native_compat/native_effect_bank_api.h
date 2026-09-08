#ifndef PF_SSBM_NATIVE_EFFECT_BANK_API_H
#define PF_SSBM_NATIVE_EFFECT_BANK_API_H

#ifdef __cplusplus
extern "C" {
#endif

int pf_ssbm_native_effect_bank_load(
    int bank,
    const char* file_name,
    const char* root_name,
    void** model_data);
void pf_ssbm_native_effect_bank_require(
    int bank,
    const char* file_name,
    const char* root_name,
    void** model_data);

#ifdef __cplusplus
}
#endif

#endif
