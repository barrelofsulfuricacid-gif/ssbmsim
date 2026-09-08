#include "source_graphs.h"

#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 64;
constexpr std::uint32_t known_storage_flags = 0x0fU;

[[nodiscard]] std::uint32_t read_u32(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint32_t value = 0;
    for (std::uint32_t byte = 0; byte < 4; ++byte) {
        value |= static_cast<std::uint32_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] std::uint64_t read_u64(
    std::span<const std::byte> bytes,
    std::uint64_t offset) noexcept
{
    const auto native_offset = static_cast<std::size_t>(offset);
    std::uint64_t value = 0;
    for (std::uint32_t byte = 0; byte < 8; ++byte) {
        value |= static_cast<std::uint64_t>(
            std::to_integer<std::uint8_t>(bytes[native_offset + byte]))
            << (byte * 8U);
    }
    return value;
}

[[nodiscard]] bool multiply_fits(
    std::uint64_t count,
    std::uint64_t stride,
    std::uint64_t& result) noexcept
{
    if (count != 0U && stride > std::numeric_limits<std::uint64_t>::max() / count) {
        return false;
    }
    result = count * stride;
    return true;
}

[[nodiscard]] std::uint64_t align8(std::uint64_t value) noexcept
{
    return (value + 7U) & ~std::uint64_t{7U};
}

[[nodiscard]] bool zero_range(
    std::span<const std::byte> bytes,
    std::uint64_t offset,
    std::uint64_t size) noexcept
{
    if (offset > bytes.size() || size > bytes.size() - offset) return false;
    for (std::uint64_t index = 0; index < size; ++index) {
        if (bytes[static_cast<std::size_t>(offset + index)] != std::byte{0}) {
            return false;
        }
    }
    return true;
}

} // namespace

bool SourceGraphsView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::source_catalog ||
        section.schema_version != source_graphs_schema ||
        section.stride != source_graph_root_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != source_graphs_schema ||
        read_u32(section.bytes, 20) != source_graph_root_record_bytes ||
        read_u32(section.bytes, 24) != source_graph_node_record_bytes ||
        read_u32(section.bytes, 28) != source_graph_edge_record_bytes) {
        return false;
    }
    root_count_ = read_u32(section.bytes, 4);
    node_count_ = read_u32(section.bytes, 8);
    edge_count_ = read_u32(section.bytes, 12);
    word_count_ = read_u32(section.bytes, 16);
    roots_offset_ = read_u64(section.bytes, 32);
    nodes_offset_ = read_u64(section.bytes, 40);
    edges_offset_ = read_u64(section.bytes, 48);
    words_offset_ = read_u64(section.bytes, 56);
    std::uint64_t root_bytes = 0;
    std::uint64_t node_bytes = 0;
    std::uint64_t edge_bytes = 0;
    std::uint64_t word_bytes = 0;
    if (section.count != root_count_ ||
        !multiply_fits(root_count_, source_graph_root_record_bytes, root_bytes) ||
        !multiply_fits(node_count_, source_graph_node_record_bytes, node_bytes) ||
        !multiply_fits(edge_count_, source_graph_edge_record_bytes, edge_bytes) ||
        !multiply_fits(word_count_, sizeof(std::uint32_t), word_bytes) ||
        roots_offset_ != header_bytes ||
        nodes_offset_ != align8(roots_offset_ + root_bytes) ||
        edges_offset_ != align8(nodes_offset_ + node_bytes) ||
        words_offset_ != align8(edges_offset_ + edge_bytes) ||
        words_offset_ > section.bytes.size() ||
        word_bytes != section.bytes.size() - words_offset_) {
        *this = {};
        return false;
    }
    for (std::uint32_t index = 0; index < root_count_; ++index) {
        const auto offset = roots_offset_ +
            static_cast<std::uint64_t>(index) * source_graph_root_record_bytes;
        const auto owner_kind = read_u32(section.bytes, offset + 24);
        const auto owner_index = read_u32(section.bytes, offset + 28);
        const auto node_index = read_u32(section.bytes, offset + 32);
        if (owner_kind > 1U || node_index >= node_count_ ||
            read_u64(section.bytes, offset) == 0U ||
            read_u64(section.bytes, offset + 8) == 0U ||
            read_u64(section.bytes, offset + 16) == 0U ||
            !zero_range(section.bytes, offset + 36, 4)) {
            *this = {};
            return false;
        }
        for (std::uint32_t previous = 0; previous < index; ++previous) {
            const auto candidate = roots_offset_ +
                static_cast<std::uint64_t>(previous) * source_graph_root_record_bytes;
            if (read_u64(section.bytes, candidate) == read_u64(section.bytes, offset) &&
                read_u32(section.bytes, candidate + 24) == owner_kind &&
                read_u32(section.bytes, candidate + 28) == owner_index) {
                *this = {};
                return false;
            }
        }
    }
    std::uint32_t expected_word = 0;
    std::uint32_t expected_edge = 0;
    for (std::uint32_t index = 0; index < node_count_; ++index) {
        const auto offset = nodes_offset_ +
            static_cast<std::uint64_t>(index) * source_graph_node_record_bytes;
        const auto logical_bytes = read_u32(section.bytes, offset);
        const auto first_word = read_u32(section.bytes, offset + 4);
        const auto node_word_count = read_u32(section.bytes, offset + 8);
        const auto first_edge = read_u32(section.bytes, offset + 12);
        const auto node_edge_count = read_u32(section.bytes, offset + 16);
        const auto flags = read_u32(section.bytes, offset + 20);
        const auto required_words = (static_cast<std::uint64_t>(logical_bytes) + 3U) / 4U;
        if (required_words != node_word_count || first_word != expected_word ||
            node_word_count > word_count_ - expected_word ||
            first_edge != expected_edge || node_edge_count > edge_count_ - expected_edge ||
            (flags & ~known_storage_flags) != 0U ||
            !zero_range(section.bytes, offset + 24, 8)) {
            *this = {};
            return false;
        }
        std::uint32_t previous_source_offset = 0;
        for (std::uint32_t local = 0; local < node_edge_count; ++local) {
            const auto edge_offset = edges_offset_ +
                static_cast<std::uint64_t>(expected_edge + local) *
                    source_graph_edge_record_bytes;
            const auto source_offset = read_u32(section.bytes, edge_offset);
            const auto target = read_u32(section.bytes, edge_offset + 4);
            const auto pointer_word = read_u32(section.bytes, words_offset_ +
                static_cast<std::uint64_t>(first_word + source_offset / 4U) * 4U);
            if (source_offset % 4U != 0U || source_offset > logical_bytes ||
                logical_bytes - source_offset < 4U || target >= node_count_ ||
                (local != 0U && source_offset <= previous_source_offset) ||
                pointer_word != 0U) {
                *this = {};
                return false;
            }
            previous_source_offset = source_offset;
        }
        if (logical_bytes % 4U != 0U) {
            const auto final_word = read_u32(section.bytes, words_offset_ +
                static_cast<std::uint64_t>(first_word + node_word_count - 1U) * 4U);
            const auto padding_bits = (4U - logical_bytes % 4U) * 8U;
            const auto padding_mask = (std::uint32_t{1U} << padding_bits) - 1U;
            if ((final_word & padding_mask) != 0U) {
                *this = {};
                return false;
            }
        }
        expected_word += node_word_count;
        expected_edge += node_edge_count;
    }
    if (expected_word != word_count_ || expected_edge != edge_count_) {
        *this = {};
        return false;
    }
    section_ = section;
    return true;
}

bool SourceGraphsView::valid() const noexcept { return !section_.bytes.empty(); }

bool SourceGraphsView::owners_match(const SourceCatalogView& catalog) const noexcept
{
    if (!valid() || !catalog.valid()) return false;
    for (std::uint32_t root_index = 0; root_index < root_count_; ++root_index) {
        const auto candidate = root(root_index);
        bool matched = false;
        for (std::uint32_t source_index = 0;
             source_index < catalog.count();
             ++source_index) {
            const auto source_record = catalog.source(source_index);
            const auto file_hash = stable_name_hash(
                std::as_bytes(std::span(source_record.path)));
            if (candidate.file_name_hash != file_hash) continue;
            const auto owner_count = candidate.owner_kind == 0U
                ? source_record.root_count
                : source_record.reference_count;
            if (candidate.owner_index >= owner_count) return false;
            matched = true;
            break;
        }
        if (!matched) return false;
    }
    return true;
}

std::uint32_t SourceGraphsView::root_count() const noexcept { return root_count_; }
std::uint32_t SourceGraphsView::node_count() const noexcept { return node_count_; }
std::uint32_t SourceGraphsView::edge_count() const noexcept { return edge_count_; }
std::uint32_t SourceGraphsView::word_count() const noexcept { return word_count_; }

SourceGraphRootRecord SourceGraphsView::root(std::uint32_t index) const noexcept
{
    if (!valid() || index >= root_count_) return {};
    const auto offset = roots_offset_ +
        static_cast<std::uint64_t>(index) * source_graph_root_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        read_u64(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
        read_u32(section_.bytes, offset + 32),
    };
}

SourceGraphNodeRecord SourceGraphsView::node(std::uint32_t index) const noexcept
{
    if (!valid() || index >= node_count_) return {};
    const auto offset = nodes_offset_ +
        static_cast<std::uint64_t>(index) * source_graph_node_record_bytes;
    return {
        read_u32(section_.bytes, offset),
        read_u32(section_.bytes, offset + 4),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16),
        read_u32(section_.bytes, offset + 20),
    };
}

SourceGraphEdgeRecord SourceGraphsView::edge(std::uint32_t index) const noexcept
{
    if (!valid() || index >= edge_count_) return {};
    const auto offset = edges_offset_ +
        static_cast<std::uint64_t>(index) * source_graph_edge_record_bytes;
    return {read_u32(section_.bytes, offset), read_u32(section_.bytes, offset + 4)};
}

std::uint32_t SourceGraphsView::word(std::uint32_t index) const noexcept
{
    if (!valid() || index >= word_count_) return 0;
    return read_u32(section_.bytes,
        words_offset_ + static_cast<std::uint64_t>(index) * 4U);
}

std::uint8_t SourceGraphsView::source_byte(
    std::uint32_t node_index,
    std::uint32_t byte_offset) const noexcept
{
    const auto record = node(node_index);
    if (!valid() || node_index >= node_count_ || byte_offset >= record.logical_bytes) {
        return 0;
    }
    const auto value = word(record.first_word + byte_offset / 4U);
    const auto shift = (3U - byte_offset % 4U) * 8U;
    return static_cast<std::uint8_t>(value >> shift);
}

} // namespace pf::ssbm
