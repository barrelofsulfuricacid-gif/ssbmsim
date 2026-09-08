#include "mapped_pack.h"
#include "stage_ground_params.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string_view>

namespace {

[[nodiscard]] std::uint64_t hash(std::string_view value)
{
    return pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(value.data()), value.size()});
}

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes, std::size_t offset)
{
    return static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset])) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 1])) << 8U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 2])) << 16U) |
        (static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(bytes[offset + 3])) << 24U);
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2) {
        std::cerr << "usage: ssbm_stage_ground_param_pack_test <asset.pack>\n";
        return 2;
    }
    pf::ssbm::MappedPack mapped;
    if (mapped.open(argv[1]) != pf::ssbm::PackStatus::ok) {
        std::cerr << "failed to map asset pack\n";
        return 1;
    }
    constexpr std::string_view section_name{"stage.ground_param.v1"};
    pf::ssbm::StageGroundParamView view;
    if (!view.open(mapped.view().find(
            pf::ssbm::SectionKind::stage_data, hash(section_name))) ||
        view.count() != 71) {
        std::cerr << "invalid stage ground parameter section\n";
        return 1;
    }

    constexpr std::array<std::string_view, 6> legal_stages{
        "GrNBa.dat", "GrNLa.dat", "GrSt.dat",
        "GrOp.dat", "GrIz.dat", "GrPs.dat"};
    for (const auto path : legal_stages) {
        const auto stage = view.find(hash(path));
        const auto image = view.image(stage);
        const auto rows = view.rows(stage);
        if (stage.file_name_hash == 0 ||
            stage.root_name_hash != hash("grGroundParam") ||
            image.size() != pf::ssbm::stage_ground_param_image_bytes ||
            rows.size() != static_cast<std::size_t>(stage.row_count) *
                pf::ssbm::stage_param_row_bytes ||
            stage.row_count == 0 ||
            read_u32(image, 0xB0) != 0 ||
            read_u32(image, 0xB4) != stage.row_count) {
            std::cerr << "invalid legal-stage ground parameters: " << path << '\n';
            return 1;
        }
    }
    std::cout << "ssbm-stage-ground-param-pack=pass stages="
              << legal_stages.size() << " section_records=" << view.count() << '\n';
    return 0;
}
