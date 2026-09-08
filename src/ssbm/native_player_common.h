#ifndef PF_SSBM_NATIVE_PLAYER_COMMON_H
#define PF_SSBM_NATIVE_PLAYER_COMMON_H

#include "asset_pack.h"
#include "native_compat/native_player_common_api.h"

namespace pf::ssbm {

[[nodiscard]] bool bind_native_player_common(
    const AssetPackView& assets) noexcept;

} // namespace pf::ssbm

#endif
