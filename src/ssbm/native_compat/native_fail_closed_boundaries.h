#ifndef PF_SSBM_NATIVE_FAIL_CLOSED_BOUNDARIES_H
#define PF_SSBM_NATIVE_FAIL_CLOSED_BOUNDARIES_H

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*PfSsbmUnsupportedBoundaryHandler)(const char* name);

extern char const* volatile pf_ssbm_last_unsupported_boundary;
extern char const* volatile pf_ssbm_last_unsupported_detail;

void pf_ssbm_reach_unsupported_boundary(const char* name);
void pf_ssbm_set_unsupported_boundary_handler(
    PfSsbmUnsupportedBoundaryHandler handler);

#ifdef __cplusplus
}
#endif

#endif
