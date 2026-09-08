#ifndef PF_SSBM_NATIVE_ITEM_COMMON_H
#define PF_SSBM_NATIVE_ITEM_COMMON_H

#include "asset_pack.h"

namespace pf::ssbm {

// Bind each normalized source node once during initialization, preserving
// cross-root identity. Root/handle lookups use this storage without allocation.
[[nodiscard]] bool bind_native_item_common(
    const AssetPackView& assets) noexcept;

} // namespace pf::ssbm

#endif
