#ifndef PF_SSBM_NATIVE_EFFECT_BANKS_H
#define PF_SSBM_NATIVE_EFFECT_BANKS_H

#include "asset_pack.h"
#include "native_compat/native_effect_bank_api.h"

namespace pf::ssbm {

[[nodiscard]] bool bind_native_effect_banks(
    const AssetPackView& assets) noexcept;

} // namespace pf::ssbm

#endif
