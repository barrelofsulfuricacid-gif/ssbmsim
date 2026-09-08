#include "native_player_common.h"

#include "player_common.h"

#include <cstddef>
#include <string_view>

extern "C" void pf_ssbm_reach_unsupported_boundary(const char* name);

namespace pf::ssbm {
namespace {

PlayerCommonView player_common;

} // namespace

bool bind_native_player_common(const AssetPackView& assets) noexcept
{
    player_common = {};
    constexpr std::string_view section_name{"player.common_data.v1"};
    const auto section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(section_name.data()),
        section_name.size()});
    return player_common.open(
        assets.find(SectionKind::player_data, section_hash));
}

} // namespace pf::ssbm

extern "C" void* pf_ssbm_native_player_common_require(void)
{
    const auto data = pf::ssbm::player_common.data();
    if (data.empty()) {
        pf_ssbm_reach_unsupported_boundary("native_player_common_data");
    }
    return const_cast<std::byte*>(data.data());
}
