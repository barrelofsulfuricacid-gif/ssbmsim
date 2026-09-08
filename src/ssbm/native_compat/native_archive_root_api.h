#ifndef PF_SSBM_NATIVE_ARCHIVE_ROOT_API_H
#define PF_SSBM_NATIVE_ARCHIVE_ROOT_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void* pf_ssbm_native_archive_root_require(
    const char* file_name,
    const char* root_name);
void* pf_ssbm_native_archive_root_optional(
    const char* file_name,
    const char* root_name);

void* pf_ssbm_native_archive_handle_require(const char* file_name);

void pf_ssbm_native_archive_costume_require(
    const char* file_name,
    const char* joint_name,
    const char* matanim_joint_name,
    void** joint,
    void** matanim_joint,
    void** archive_handle);

void* pf_ssbm_native_archive_public_root_require(
    void* archive_handle,
    const char* root_name);

uint64_t pf_ssbm_native_archive_stub_file(const void* archive_handle);

#ifdef __cplusplus
}
#endif

#endif
