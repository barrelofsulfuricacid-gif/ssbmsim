#include "joint_trees.h"
#include "mapped_pack.h"
#include "stage_joint_animations.h"
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

[[nodiscard]] std::string object_tree_name(
    std::uint32_t group,
    std::uint32_t state,
    std::uint32_t node)
{
    return "map_head.model_groups[" + std::to_string(group) +
        "].joint_animations[" + std::to_string(state) +
        "].nodes[" + std::to_string(node) + "].object";
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2) {
        std::cerr << "usage: ssbm_stage_joint_animation_pack_test <asset.pack>\n";
        return 2;
    }
    pf::ssbm::MappedPack mapped;
    if (mapped.open(argv[1]) != pf::ssbm::PackStatus::ok) {
        std::cerr << "failed to map asset pack\n";
        return 1;
    }
    pf::ssbm::StageMapHeadsView maps;
    pf::ssbm::StageJointAnimationsView animations;
    pf::ssbm::JointTreesView joints;
    if (!maps.open(mapped.view().find(
            pf::ssbm::SectionKind::stage_data, hash("stage.map_head.v2"))) ||
        !animations.open(mapped.view().find(
            pf::ssbm::SectionKind::animation_data,
            hash("stage.joint_animations.v1"))) ||
        !joints.open(mapped.view().find(
            pf::ssbm::SectionKind::animation_data, hash("joint.trees.v2")))) {
        std::cerr << "invalid legal-stage animation sections\n";
        return 1;
    }

    constexpr std::array<std::string_view, 6> legal_stages{
        "GrNBa.dat", "GrNLa.dat", "GrSt.dat",
        "GrOp.dat", "GrIz.dat", "GrPs.dat"};
    const auto root_hash = hash("map_head");
    std::uint32_t state_count = 0;
    std::uint32_t animated_state_count = 0;
    std::uint32_t data_bytes = 0;
    std::uint32_t canonical_object_references = 0;
    for (const auto path : legal_stages) {
        const auto map = maps.find(hash(path), root_hash);
        if (map.file_name_hash == 0) {
            std::cerr << "missing legal-stage map head: " << path << '\n';
            return 1;
        }
        for (std::uint32_t group_index = 0;
             group_index < map.model_group_count;
             ++group_index) {
            const auto group = maps.model_group(map.first_model_group + group_index);
            for (std::uint32_t state_index = 0;
                 state_index < group.joint_animation_count;
                 ++state_index) {
                const auto set = animations.find(
                    hash(path), root_hash, group_index, state_index);
                if (set.file_name_hash == 0) {
                    std::cerr << "missing legal-stage joint animation: "
                              << path << '\n';
                    return 1;
                }
                ++state_count;
                if (set.root_present) ++animated_state_count;
                for (std::uint32_t local = 0; local < set.node_count; ++local) {
                    const auto node = animations.node(set.first_node + local);
                    if (node.object_model_joint >= 0) {
                        const auto model_tree = joints.find(
                            hash(path), group.joint_tree_name_hash);
                        if (static_cast<std::uint32_t>(
                                node.object_model_joint) >= model_tree.joint_count) {
                            std::cerr << "invalid canonical animation object joint: "
                                      << path << '\n';
                            return 1;
                        }
                        ++canonical_object_references;
                    } else if (node.object_reference_present() &&
                        joints.find(hash(path), hash(object_tree_name(
                            group_index, state_index, local))).joint_count == 0) {
                        std::cerr << "missing animation object joint tree: "
                                  << path << '\n';
                        return 1;
                    }
                    for (std::uint32_t track_index = 0;
                         track_index < node.track_count;
                         ++track_index) {
                        const auto track = animations.track(
                            node.first_track + track_index);
                        const auto bytes = animations.track_data(track);
                        if (bytes.size() != track.data_length) {
                            std::cerr << "invalid animation track bytes\n";
                            return 1;
                        }
                        data_bytes += track.data_length;
                    }
                }
            }
        }
    }
    if (state_count != animations.set_count() || animated_state_count == 0 ||
        animations.node_count() == 0 || animations.track_count() == 0 ||
        data_bytes == 0 || canonical_object_references == 0) {
        std::cerr << "legal-stage joint animation coverage is incomplete\n";
        return 1;
    }
    std::cout << "ssbm-stage-joint-animation-pack=pass states=" << state_count
              << " animated_states=" << animated_state_count
              << " nodes=" << animations.node_count()
              << " tracks=" << animations.track_count()
              << " data_bytes=" << data_bytes
              << " canonical_object_references="
              << canonical_object_references << '\n';
    return 0;
}
