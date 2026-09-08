#include "mapped_pack.h"
#include "player_common.h"

#include <cstddef>
#include <cstdio>
#include <string_view>

namespace {

[[nodiscard]] std::uint64_t name_hash(std::string_view name) noexcept
{
    return pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(name.data()), name.size()});
}

[[nodiscard]] bool run(const char* path) noexcept
{
    pf::ssbm::MappedPack pack;
    if (pack.open(path) != pf::ssbm::PackStatus::ok) {
        return false;
    }
    pf::ssbm::PlayerCommonView common;
    if (!common.open(pack.view().find(
            pf::ssbm::SectionKind::player_data,
            name_hash("player.common_data.v1"))) ||
        common.data().size() != 0x184 ||
        common.file_name_hash() != name_hash("PdPm.dat") ||
        common.root_name_hash() != name_hash("plLoadCommonData")) {
        return false;
    }
    const auto bytes = common.data();
    return bytes[0] == std::byte{0x00} && bytes[1] == std::byte{0x00} &&
        bytes[2] == std::byte{0x20} && bytes[3] == std::byte{0x40};
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2 || !run(argv[1])) {
        std::fputs("ssbm-player-common-pack=fail\n", stderr);
        return 1;
    }
    std::puts("ssbm-player-common-pack=pass");
    return 0;
}
