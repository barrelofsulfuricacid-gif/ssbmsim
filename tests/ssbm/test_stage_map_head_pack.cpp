#include "joint_trees.h"
#include "mapped_pack.h"
#include "stage_map_heads.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>
#include <string_view>

namespace {

[[nodiscard]] std::uint64_t hash(std::string_view value)
{
    return pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(value.data()), value.size()});
}

[[nodiscard]] std::string model_tree_name(
    std::string_view root_name,
    std::uint32_t index)
{
    return std::string{root_name} + ".model_groups[" +
        std::to_string(index) + "].jobj";
}

[[nodiscard]] std::string general_tree_name(
    std::string_view root_name,
    std::uint32_t index)
{
    return std::string{root_name} + ".general_points[" +
        std::to_string(index) + "].jobj";
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2) {
        std::cerr << "usage: ssbm_stage_map_head_pack_test <asset.pack>\n";
        return 2;
    }
    pf::ssbm::MappedPack mapped;
    if (mapped.open(argv[1]) != pf::ssbm::PackStatus::ok) {
        std::cerr << "failed to map asset pack\n";
        return 1;
    }
    pf::ssbm::StageMapHeadsView maps;
    if (!maps.open(mapped.view().find(
            pf::ssbm::SectionKind::stage_data, hash("stage.map_head.v2"))) ||
        maps.count() == 0 || maps.model_group_count() == 0 ||
        maps.general_point_count() == 0) {
        std::cerr << "invalid stage map-head section\n";
        return 1;
    }
    pf::ssbm::JointTreesView joints;
    if (!joints.open(mapped.view().find(
            pf::ssbm::SectionKind::animation_data, hash("joint.trees.v2")))) {
        std::cerr << "invalid joint-tree section\n";
        return 1;
    }

    constexpr std::array<std::string_view, 6> legal_stages{
        "GrNBa.dat", "GrNLa.dat", "GrSt.dat",
        "GrOp.dat", "GrIz.dat", "GrPs.dat"};
    constexpr std::string_view root_name{"map_head"};
    std::uint32_t checked_groups = 0;
    std::uint32_t checked_general_groups = 0;
    std::uint32_t checked_points = 0;
    std::uint32_t checked_aliases = 0;
    for (const auto path : legal_stages) {
        const auto map = maps.find(hash(path), hash(root_name));
        if (map.file_name_hash == 0 || map.general_group_count == 0 ||
            map.model_group_count == 0) {
            std::cerr << "missing legal-stage map head: " << path << '\n';
            return 1;
        }
        if (path == "GrPs.dat" && map.model_group_count < 10U) {
            std::cerr << "truncated Pokemon Stadium model groups: "
                      << map.model_group_count << '\n';
            return 1;
        }
        for (std::uint32_t local = 0; local < map.general_group_count; ++local) {
            const auto group = maps.general_group(map.first_general_group + local);
            ++checked_general_groups;
            checked_points += group.point_count;
            if (group.linked_model_group >= 0) ++checked_aliases;
            if (group.root_node_present &&
                joints.find(hash(path), hash(general_tree_name(root_name, local))).joint_count == 0) {
                std::cerr << "missing general-point joint tree: " << path << '\n';
                return 1;
            }
        }
        for (std::uint32_t local = 0; local < map.model_group_count; ++local) {
            const auto group = maps.model_group(map.first_model_group + local);
            if (path == "GrPs.dat" &&
                (local == 0U || local == 1U || local == 2U || local == 5U) &&
                !group.root_node_present()) {
                std::cerr << "missing Pokemon Stadium startup model group: "
                          << local << '\n';
                return 1;
            }
            if (group.root_node_present() &&
                joints.find(hash(path), hash(model_tree_name(root_name, local))).joint_count == 0) {
                std::cerr << "missing model-group joint tree: " << path << '\n';
                return 1;
            }
            checked_groups += 1;
        }
    }
    if (checked_groups == 0 || checked_points == 0 ||
        checked_aliases != checked_general_groups) {
        std::cerr << "legal-stage gameplay topology mismatch: groups="
                  << checked_groups << " points=" << checked_points
                  << " aliases=" << checked_aliases << '\n';
        return 1;
    }
    std::cout << "ssbm-stage-map-head-pack=pass stages=" << legal_stages.size()
              << " model_groups=" << checked_groups
              << " general_points=" << checked_points
              << " aliased_general_roots=" << checked_aliases << '\n';
    return 0;
}
