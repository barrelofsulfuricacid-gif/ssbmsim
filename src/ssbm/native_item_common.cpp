#include "native_item_common.h"

#include "native_compat/native_fail_closed_boundaries.h"
#include "native_disc_file_name.h"
#include "source_catalog.h"
#include "source_graphs.h"

#include <algorithm>
#include <limits>
#include <tuple>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <string_view>
#include <vector>

extern "C" {
alignas(32) unsigned char HSD_SisLib_FontAtlas[287 * 512];
}

namespace pf::ssbm {
namespace {

// One native image per source node preserves aliases between public roots.
struct BoundNode {
    std::span<std::byte> image{};
};
std::vector<BoundNode> archive_nodes;
std::vector<std::vector<std::byte>> archive_storage;
void* item_common_data{};
void* fighter_common_data{};
SourceGraphsView archive_graphs;

struct CachedArchiveHandle {
    std::uint64_t file_name_hash{};
};

std::deque<CachedArchiveHandle> archive_handles;

[[nodiscard]] std::uint64_t hash_name(std::string_view name) noexcept
{
    return stable_name_hash({
        reinterpret_cast<const std::byte*>(name.data()), name.size()});
}

void write_u32(
    std::span<std::byte> bytes,
    std::size_t offset,
    std::uint32_t value) noexcept
{
    bytes[offset] = static_cast<std::byte>(value & 0xffU);
    bytes[offset + 1] = static_cast<std::byte>((value >> 8U) & 0xffU);
    bytes[offset + 2] = static_cast<std::byte>((value >> 16U) & 0xffU);
    bytes[offset + 3] = static_cast<std::byte>((value >> 24U) & 0xffU);
}

[[nodiscard]] SourceGraphRootRecord find_root(
    const SourceGraphsView& source,
    std::uint64_t file_name_hash,
    std::uint64_t root_name_hash) noexcept
{
    for (std::uint32_t index = 0; index < source.root_count(); ++index) {
        const auto candidate = source.root(index);
        if (candidate.owner_kind == 0U &&
            candidate.file_name_hash == file_name_hash &&
            candidate.root_name_hash == root_name_hash) {
            return candidate;
        }
    }
    return {};
}

[[nodiscard]] bool validate_public_root(
    const SourceGraphsView& source,
    std::uint32_t root_node) noexcept
{
    if (root_node >= source.node_count()) return false;
    const auto node = source.node(root_node);
    if (node.logical_bytes != 0x18U || node.edge_count != 6U) return false;
    for (std::uint32_t local = 0; local < node.edge_count; ++local) {
        const auto edge = source.edge(node.first_edge + local);
        if (edge.source_byte_offset != local * 4U) return false;
    }
    const auto common = source.edge(node.first_edge).target_node;
    return common < source.node_count() &&
        source.node(common).logical_bytes >= 0x160U;
}

[[nodiscard]] bool validate_pointer_table_root(
    const SourceGraphsView& source,
    std::uint32_t root_node,
    std::uint32_t pointer_count) noexcept
{
    if (root_node >= source.node_count()) return false;
    const auto node = source.node(root_node);
    if (node.logical_bytes < pointer_count * 4U ||
        node.edge_count < pointer_count) return false;
    for (std::uint32_t local = 0; local < pointer_count; ++local) {
        const auto edge = source.edge(node.first_edge + local);
        if (edge.source_byte_offset != local * 4U) return false;
    }
    return true;
}

[[nodiscard]] bool materialize_graphs(const SourceGraphsView& source,
    SectionView storage)
{
    const auto bytes = storage.bytes;
    if (storage.schema_version != 1 || storage.count != source.node_count() ||
        storage.stride != 12 || bytes.size() != 16ULL + 12ULL * source.node_count()) return false;
    const auto read = [&](std::size_t offset) {
        std::uint32_t value = 0;
        for (unsigned i = 0; i < 4; ++i)
            value |= std::to_integer<std::uint32_t>(bytes[offset + i]) << (8U * i);
        return value;
    };
    const auto groups = read(8);
    if (read(0) != 1 || read(4) != source.node_count() || read(12) != 12 ||
        groups > source.node_count() || (groups == 0 && source.node_count() != 0)) return false;
    struct Placement { std::uint32_t group, offset, extent; };
    std::vector<Placement> placements;
    std::vector<std::uint32_t> sizes(groups, std::numeric_limits<std::uint32_t>::max());
    std::vector<std::tuple<std::uint32_t, std::uint32_t, std::uint32_t>> ranges;
    for (std::uint32_t i = 0; i < source.node_count(); ++i) {
        const auto record = std::size_t{16} + std::size_t{i} * 12U;
        const Placement placement{read(record), read(record + 4U), read(record + 8U)};
        const auto length = source.node(i).logical_bytes;
        if (placement.group >= groups || placement.offset > placement.extent ||
            length > placement.extent - placement.offset) return false;
        auto& extent = sizes[placement.group];
        if (extent != std::numeric_limits<std::uint32_t>::max() && extent != placement.extent) return false;
        extent = placement.extent;
        placements.push_back(placement);
        ranges.emplace_back(placement.group, placement.offset, placement.offset + length);
    }
    std::sort(ranges.begin(), ranges.end());
    std::vector<std::uint32_t> ends(groups);
    for (const auto& [group, begin, end] : ranges) {
        if (begin != ends[group]) return false; // Reject overlaps and unrepresented gaps.
        ends[group] = end;
    }
    if (ends != sizes) return false;
    archive_storage.resize(groups);
    for (std::uint32_t i = 0; i < groups; ++i)
        archive_storage[i].resize(static_cast<std::size_t>(sizes[i]) + 32U);
    archive_nodes.resize(source.node_count());
    for (std::uint32_t index = 0; index < source.node_count(); ++index) {
        const auto input = source.node(index);
        auto& image = archive_nodes[index].image;
        const auto placement = placements[index];
        image = std::span<std::byte>(archive_storage[placement.group]).subspan(
            placement.offset, input.logical_bytes);
        for (std::uint32_t offset = 0; offset < input.logical_bytes; ++offset)
            image[offset] = static_cast<std::byte>(source.source_byte(index, offset));
    }
    if constexpr (sizeof(void*) == sizeof(std::uint32_t)) {
        for (std::uint32_t index = 0; index < source.node_count(); ++index) {
            const auto input = source.node(index);
            for (std::uint32_t local = 0; local < input.edge_count; ++local) {
                const auto edge = source.edge(input.first_edge + local);
                const auto pointer = reinterpret_cast<std::uintptr_t>(
                    archive_nodes[edge.target_node].image.data());
                write_u32(archive_nodes[index].image, edge.source_byte_offset,
                    static_cast<std::uint32_t>(pointer));
            }
        }
    }
    return true;
}

[[nodiscard]] void* require_archive_root(std::uint64_t file_hash,
                                       std::uint64_t root_hash)
{
    const auto root = find_root(archive_graphs, file_hash, root_hash);
    if (root.file_name_hash == 0U || root.node_index >= archive_nodes.size()) {
        pf_ssbm_reach_unsupported_boundary("native_archive_root_missing");
        return nullptr;
    }
    return archive_nodes[root.node_index].image.data();
}

[[nodiscard]] CachedArchiveHandle* require_archive_handle(std::uint64_t file_hash)
{
    for (auto& handle : archive_handles) {
        if (handle.file_name_hash == file_hash) return &handle;
    }
    pf_ssbm_reach_unsupported_boundary("native_archive_handle_missing");
    return nullptr;
}

} // namespace

bool bind_native_item_common(const AssetPackView& assets) noexcept
{
    archive_nodes.clear();
    archive_storage.clear();
    item_common_data = nullptr;
    fighter_common_data = nullptr;
    archive_graphs = {};
    archive_handles.clear();

    const auto font = assets.find(SectionKind::source_catalog,
        hash_name("sis.font_atlas.v1"));
    if (font.schema_version != 1 || font.count != 287 || font.stride != 512 ||
        font.bytes.size() != sizeof(HSD_SisLib_FontAtlas)) return false;
    std::memcpy(HSD_SisLib_FontAtlas, font.bytes.data(), font.bytes.size());

    constexpr std::string_view catalog_name{"source.catalog.v1"};
    constexpr std::string_view graphs_name{"source.graphs.v2"};
    SourceCatalogView catalog;
    SourceGraphsView graphs;
    if (!catalog.open(assets.find(SectionKind::source_catalog,
            hash_name(catalog_name))) ||
        !graphs.open(assets.find(SectionKind::source_catalog,
            hash_name(graphs_name))) ||
        !graphs.owners_match(catalog)) {
        return false;
    }

    const auto item_root = find_root(graphs, hash_name("ItCo.dat"),
        hash_name("itPublicData"));
    const auto fighter_root = find_root(graphs, hash_name("PlCo.dat"),
        hash_name("ftLoadCommonData"));
    if (item_root.file_name_hash == 0U ||
        !validate_public_root(graphs, item_root.node_index) ||
        fighter_root.file_name_hash == 0U ||
        !validate_pointer_table_root(graphs, fighter_root.node_index, 23U)) {
        return false;
    }

    try {
        if (!materialize_graphs(graphs, assets.find(SectionKind::source_catalog,
                hash_name("source.storage.v1")))) return false;
        for (std::uint32_t index = 0; index < graphs.root_count(); ++index) {
            const auto file = graphs.root(index).file_name_hash;
            bool found = false;
            for (const auto& handle : archive_handles)
                if (handle.file_name_hash == file) { found = true; break; }
            if (!found) archive_handles.push_back({file});
        }
        item_common_data = archive_nodes[item_root.node_index].image.data();
        fighter_common_data = archive_nodes[fighter_root.node_index].image.data();
        archive_graphs = graphs;
        return true;
    } catch (...) {
        archive_nodes.clear();
    archive_storage.clear();
        item_common_data = nullptr;
        fighter_common_data = nullptr;
        archive_graphs = {};
        archive_handles.clear();
        return false;
    }
}

} // namespace pf::ssbm

extern "C" void* pf_ssbm_native_item_common_require(void)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_item_common_requires_32_bit_abi");
    }
    if (pf::ssbm::item_common_data == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_item_common_data");
    }
    return pf::ssbm::item_common_data;
}

extern "C" void* pf_ssbm_native_fighter_common_require(void)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_fighter_common_requires_32_bit_abi");
    }
    if (pf::ssbm::fighter_common_data == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_fighter_common_data");
    }
    return pf::ssbm::fighter_common_data;
}

extern "C" void* pf_ssbm_native_archive_root_require(
    const char* file_name,
    const char* root_name)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_archive_root_requires_32_bit_abi");
    }
    if (!pf::ssbm::archive_graphs.valid() || file_name == nullptr ||
        root_name == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_archive_root_arguments");
    }
    const auto file_hash = pf::ssbm::native_disc_file_name_hash(file_name);
    const auto root_hash = pf::ssbm::hash_name(root_name);
    pf_ssbm_last_unsupported_detail = file_name;
    void* result = pf::ssbm::require_archive_root(file_hash, root_hash);
    pf_ssbm_last_unsupported_detail = nullptr;
    return result;
}

extern "C" void* pf_ssbm_native_archive_root_optional(
    const char* file_name,
    const char* root_name)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_archive_root_requires_32_bit_abi");
    }
    if (!pf::ssbm::archive_graphs.valid() || file_name == nullptr ||
        root_name == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_archive_root_arguments");
    }
    const auto file_hash = pf::ssbm::native_disc_file_name_hash(file_name);
    const auto root_hash = pf::ssbm::hash_name(root_name);
    const auto source_root = pf::ssbm::find_root(
        pf::ssbm::archive_graphs, file_hash, root_hash);
    if (source_root.file_name_hash == 0U) {
        return nullptr;
    }
    return pf::ssbm::require_archive_root(file_hash, root_hash);
}

extern "C" void* pf_ssbm_native_archive_handle_require(
    const char* file_name)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_archive_handle_requires_32_bit_abi");
    }
    if (!pf::ssbm::archive_graphs.valid() || file_name == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_archive_handle_arguments");
    }
    pf_ssbm_last_unsupported_detail = file_name;
    auto* result = pf::ssbm::require_archive_handle(
        pf::ssbm::native_disc_file_name_hash(file_name));
    pf_ssbm_last_unsupported_detail = nullptr;
    return result;
}

extern "C" void pf_ssbm_native_archive_costume_require(
    const char* file_name,
    const char* joint_name,
    const char* matanim_joint_name,
    void** joint,
    void** matanim_joint,
    void** archive_handle)
{
    if constexpr (sizeof(void*) != sizeof(std::uint32_t)) {
        pf_ssbm_reach_unsupported_boundary(
            "native_archive_costume_requires_32_bit_abi");
    }
    if (!pf::ssbm::archive_graphs.valid() || file_name == nullptr ||
        joint_name == nullptr || joint == nullptr || matanim_joint == nullptr ||
        archive_handle == nullptr) {
        pf_ssbm_reach_unsupported_boundary("native_archive_costume_arguments");
        return;
    }
    const auto file_hash = pf::ssbm::native_disc_file_name_hash(file_name);
    pf_ssbm_last_unsupported_detail = file_name;
    *joint = pf::ssbm::require_archive_root(
        file_hash, pf::ssbm::hash_name(joint_name));
    *matanim_joint = matanim_joint_name == nullptr
        ? nullptr
        : pf::ssbm::require_archive_root(
              file_hash, pf::ssbm::hash_name(matanim_joint_name));
    *archive_handle = pf::ssbm::require_archive_handle(file_hash);
    pf_ssbm_last_unsupported_detail = nullptr;
}

extern "C" void* pf_ssbm_native_archive_public_root_require(
    void* archive_handle,
    const char* root_name)
{
    if (archive_handle == nullptr || root_name == nullptr) {
        pf_ssbm_reach_unsupported_boundary(
            "native_archive_public_root_arguments");
        return nullptr;
    }
    for (auto& handle : pf::ssbm::archive_handles) {
        if (&handle == archive_handle) {
            return pf::ssbm::require_archive_root(handle.file_name_hash,
                pf::ssbm::hash_name(root_name));
        }
    }
    pf_ssbm_reach_unsupported_boundary(
        "native_archive_public_root_unknown_handle");
    return nullptr;
}

extern "C" std::uint64_t pf_ssbm_native_archive_stub_file(
    const void* archive_handle)
{
    if (archive_handle == nullptr) return 0U;
    for (auto& handle : pf::ssbm::archive_handles) {
        if (&handle == archive_handle) return handle.file_name_hash;
    }
    return 0U;
}
