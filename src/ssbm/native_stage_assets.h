#ifndef PF_SSBM_NATIVE_STAGE_ASSETS_H
#define PF_SSBM_NATIVE_STAGE_ASSETS_H

#include "asset_pack.h"
#include "native_compat/native_stage_assets_api.h"

namespace pf::ssbm {

[[nodiscard]] bool bind_native_stage_assets(
    const AssetPackView& assets) noexcept;

} // namespace pf::ssbm

#endif
