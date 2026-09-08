#include "native_stage_assets.h"

#include "native_compat/native_archive_root_api.h"
#include "native_compat/native_fail_closed_boundaries.h"
#include "native_disc_file_name.h"
#include "stage_ground_params.h"
#include "stage_collision.h"
#include "stage_joint_animations.h"
#include "stage_map_heads.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string_view>
#include <vector>

extern "C" void pf_ssbm_reach_unsupported_boundary(const char* name);

namespace pf::ssbm {
namespace {

struct BoundGroundParam {
    std::uint64_t file_name_hash{};
    alignas(4) std::array<std::byte, stage_ground_param_image_bytes> image{};
    std::vector<std::byte> rows{};
};

struct BoundCollision {
    std::uint64_t file_name_hash{};
    alignas(4) std::array<std::byte, 0x30> image{};
    std::vector<std::byte> vertices{};
    std::vector<std::byte> lines{};
    std::vector<std::byte> groups{};
};

std::vector<BoundGroundParam> ground_params;
std::vector<BoundCollision> collisions;
StageMapHeadsView map_heads;
StageJointAnimationsView joint_animations;

void write_u32(std::span<std::byte> bytes, std::size_t offset,
    std::uint32_t value) noexcept
{
    bytes[offset] = static_cast<std::byte>(value & 0xffU);
    bytes[offset + 1] = static_cast<std::byte>((value >> 8U) & 0xffU);
    bytes[offset + 2] = static_cast<std::byte>((value >> 16U) & 0xffU);
    bytes[offset + 3] = static_cast<std::byte>((value >> 24U) & 0xffU);
}

void write_i16(std::span<std::byte> bytes, std::size_t offset,
    std::int16_t value) noexcept
{
    const auto bits = static_cast<std::uint16_t>(value);
    bytes[offset] = static_cast<std::byte>(bits & 0xffU);
    bytes[offset + 1] = static_cast<std::byte>((bits >> 8U) & 0xffU);
}

void write_range(std::span<std::byte> bytes, std::size_t offset,
    StageCollisionRange range) noexcept
{
    write_i16(bytes, offset, range.offset);
    write_i16(bytes, offset + 2, range.count);
}

} // namespace

bool bind_native_stage_assets(const AssetPackView& assets) noexcept
{
    ground_params.clear();
    collisions.clear();
    map_heads = {};
    joint_animations = {};
    constexpr std::string_view section_name{"stage.ground_param.v1"};
    const auto section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(section_name.data()),
        section_name.size()});
    StageGroundParamView source;
    if (!source.open(assets.find(SectionKind::stage_data, section_hash))) {
        return false;
    }
    constexpr std::string_view collision_section_name{"stage.collision.v1"};
    const auto collision_section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(collision_section_name.data()),
        collision_section_name.size()});
    StageCollisionView collision_source;
    if (!collision_source.open(
            assets.find(SectionKind::stage_data, collision_section_hash))) {
        return false;
    }
    constexpr std::string_view map_head_section_name{"stage.map_head.v2"};
    const auto map_head_section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(map_head_section_name.data()),
        map_head_section_name.size()});
    if (!map_heads.open(
            assets.find(SectionKind::stage_data, map_head_section_hash))) {
        return false;
    }
    constexpr std::string_view animation_section_name{
        "stage.joint_animations.v1"};
    const auto animation_section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(animation_section_name.data()),
        animation_section_name.size()});
    if (!joint_animations.open(assets.find(
            SectionKind::animation_data, animation_section_hash))) {
        return false;
    }
    std::uint32_t expected_animation_sets = 0;
    for (std::uint32_t map_index = 0;
         map_index < map_heads.count();
         ++map_index) {
        const auto map = map_heads.map(map_index);
        for (std::uint32_t group_index = 0;
             group_index < map.model_group_count;
             ++group_index) {
            const auto group = map_heads.model_group(
                map.first_model_group + group_index);
            for (std::uint32_t state_index = 0;
                 state_index < group.joint_animation_count;
                 ++state_index) {
                if (joint_animations.find(
                        map.file_name_hash,
                        map.root_name_hash,
                        group_index,
                        state_index).file_name_hash == 0) {
                    map_heads = {};
                    joint_animations = {};
                    return false;
                }
                ++expected_animation_sets;
            }
        }
    }
    if (expected_animation_sets != joint_animations.set_count()) {
        map_heads = {};
        joint_animations = {};
        return false;
    }
    try {
        ground_params.reserve(source.count());
        for (std::uint32_t index = 0; index < source.count(); ++index) {
            const auto record = source.record(index);
            const auto image = source.image(record);
            const auto rows = source.rows(record);
            BoundGroundParam bound;
            bound.file_name_hash = record.file_name_hash;
            std::memcpy(bound.image.data(), image.data(), image.size());
            bound.rows.assign(rows.begin(), rows.end());
            ground_params.push_back(std::move(bound));
        }
        collisions.reserve(collision_source.count());
        for (std::uint32_t index = 0; index < collision_source.count(); ++index) {
            const auto record = collision_source.record(index);
            BoundCollision bound;
            bound.file_name_hash = record.file_name_hash;
            bound.vertices.resize(
                static_cast<std::size_t>(record.vertex_count) * stage_collision_vertex_bytes);
            bound.lines.resize(
                static_cast<std::size_t>(record.line_count) * stage_collision_line_bytes);
            bound.groups.resize(
                static_cast<std::size_t>(record.group_count) * stage_collision_group_bytes);
            for (std::uint32_t item = 0; item < record.vertex_count; ++item) {
                const auto vertex = collision_source.vertex(record, item);
                const auto offset = static_cast<std::size_t>(item) * stage_collision_vertex_bytes;
                write_u32(bound.vertices, offset, vertex.x_bits);
                write_u32(bound.vertices, offset + 4, vertex.y_bits);
            }
            for (std::uint32_t item = 0; item < record.line_count; ++item) {
                const auto line = collision_source.line(record, item);
                const auto offset = static_cast<std::size_t>(item) * stage_collision_line_bytes;
                write_i16(bound.lines, offset, line.vertex_1);
                write_i16(bound.lines, offset + 2, line.vertex_2);
                write_i16(bound.lines, offset + 4, line.next);
                write_i16(bound.lines, offset + 6, line.previous);
                write_i16(bound.lines, offset + 8, line.next_alternate);
                write_i16(bound.lines, offset + 10, line.previous_alternate);
                write_i16(bound.lines, offset + 12, line.collision_flags);
                // The pack keeps the two source bytes as semantic fields, but
                // the imported code reads them together as MapLine::lo_flags.
                // On PowerPC the properties byte is the high byte and the
                // material byte is the low byte.  Reverse their byte placement
                // when materializing the little-endian native MapLine so the
                // resulting u16 retains the original numeric value.
                bound.lines[offset + 14] = static_cast<std::byte>(line.material);
                bound.lines[offset + 15] = static_cast<std::byte>(line.properties);
            }
            for (std::uint32_t item = 0; item < record.group_count; ++item) {
                const auto group = collision_source.group(record, item);
                const auto offset = static_cast<std::size_t>(item) * stage_collision_group_bytes;
                write_range(bound.groups, offset, group.top);
                write_range(bound.groups, offset + 4, group.bottom);
                write_range(bound.groups, offset + 8, group.right);
                write_range(bound.groups, offset + 12, group.left);
                write_range(bound.groups, offset + 16, group.dynamic);
                write_u32(bound.groups, offset + 20, group.x_min_bits);
                write_u32(bound.groups, offset + 24, group.y_min_bits);
                write_u32(bound.groups, offset + 28, group.x_max_bits);
                write_u32(bound.groups, offset + 32, group.y_max_bits);
                write_range(bound.groups, offset + 36, group.vertices);
            }
            write_u32(bound.image, 4, record.vertex_count);
            write_u32(bound.image, 12, record.line_count);
            write_range(bound.image, 0x10, record.top);
            write_range(bound.image, 0x14, record.bottom);
            write_range(bound.image, 0x18, record.right);
            write_range(bound.image, 0x1C, record.left);
            write_range(bound.image, 0x20, record.dynamic);
            write_u32(bound.image, 0x28, record.group_count);
            collisions.push_back(std::move(bound));
        }
    } catch (...) {
        ground_params.clear();
        collisions.clear();
        map_heads = {};
        joint_animations = {};
        return false;
    }

    if constexpr (sizeof(void*) == sizeof(std::uint32_t)) {
        for (auto& bound : ground_params) {
            const auto pointer = reinterpret_cast<std::uintptr_t>(
                bound.rows.empty() ? nullptr : bound.rows.data());
            write_u32(bound.image, 0xB0, static_cast<std::uint32_t>(pointer));
        }
        for (auto& bound : collisions) {
            write_u32(bound.image, 0x00, static_cast<std::uint32_t>(
                reinterpret_cast<std::uintptr_t>(bound.vertices.data())));
            write_u32(bound.image, 0x08, static_cast<std::uint32_t>(
                reinterpret_cast<std::uintptr_t>(bound.lines.data())));
            write_u32(bound.image, 0x24, static_cast<std::uint32_t>(
                reinterpret_cast<std::uintptr_t>(bound.groups.data())));
        }
    }
    return true;
}

extern "C" void* pf_ssbm_native_stage_collision_require(
    const char* disc_path)
{
    using namespace pf::ssbm;
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary("native_stage_requires_32_bit_abi");
    }
    const auto wanted = native_disc_file_name_hash(disc_path);
    for (auto& stage : collisions) {
        if (stage.file_name_hash == wanted) {
            return stage.image.data();
        }
    }
    pf_ssbm_reach_unsupported_boundary("native_stage_collision");
    return nullptr;
}

} // namespace pf::ssbm

extern "C" int pf_ssbm_native_stage_require(
    const char* disc_path,
    PfSsbmNativeStageAssets* assets)
{
    using namespace pf::ssbm;
    if (assets == nullptr) {
        return 0;
    }
    *assets = {};
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary("native_stage_requires_32_bit_abi");
    }
    const auto wanted = native_disc_file_name_hash(disc_path);
    assets->archive_token =
        pf_ssbm_native_archive_handle_require(disc_path);
    for (auto& stage : ground_params) {
        if (stage.file_name_hash == wanted) {
            assets->ground_param = stage.image.data();
            break;
        }
    }
    for (auto& stage : collisions) {
        if (stage.file_name_hash == wanted) {
            assets->collision = stage.image.data();
            break;
        }
    }
    if (assets->ground_param == nullptr || assets->collision == nullptr) {
        pf_ssbm_last_unsupported_detail = disc_path;
        pf_ssbm_reach_unsupported_boundary("native_stage_core_assets");
    }
    const auto map_head = map_heads.find(wanted);
    if (map_head.file_name_hash == 0) {
        pf_ssbm_reach_unsupported_boundary("native_stage_map_head");
    }
    assets->map_head = pf_ssbm_native_archive_root_require(disc_path, "map_head");
    if (assets->map_head == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_stage_jobj_runtime_graph");
    }
    assets->quake_model_set = pf_ssbm_native_archive_root_optional(
        disc_path, "quake_model_set");
    assets->item_data = pf_ssbm_native_archive_root_optional(
        disc_path, "itemdata");
    assets->map_particles = pf_ssbm_native_archive_root_optional(
        disc_path, "map_ptcl");
    assets->map_textures = pf_ssbm_native_archive_root_optional(
        disc_path, "map_texg");
    assets->yakumono_param = pf_ssbm_native_archive_root_optional(
        disc_path, "yakumono_param");
    if (assets->yakumono_param == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_stage_yakumono_param");
    }
    return 1;
}

extern "C" void* pf_ssbm_native_stage_ground_param_require(
    const char* disc_path)
{
    using namespace pf::ssbm;
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary("native_stage_requires_32_bit_abi");
    }
    const auto wanted = native_disc_file_name_hash(disc_path);
    for (auto& stage : ground_params) {
        if (stage.file_name_hash == wanted) {
            return stage.image.data();
        }
    }
    pf_ssbm_reach_unsupported_boundary("native_stage_ground_param");
    return nullptr;
}
