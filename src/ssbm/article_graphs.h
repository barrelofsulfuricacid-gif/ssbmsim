#ifndef PF_SSBM_ARTICLE_GRAPHS_H
#define PF_SSBM_ARTICLE_GRAPHS_H

#include "asset_pack.h"

#include <cstdint>

namespace pf::ssbm {

inline constexpr std::uint32_t article_graphs_schema = 1;
inline constexpr std::uint32_t article_graph_root_record_bytes = 40;
inline constexpr std::uint32_t article_graph_node_record_bytes = 32;
inline constexpr std::uint32_t article_graph_edge_record_bytes = 8;

enum class ArticleGraphRootKind : std::uint32_t {
    extension = 1,
    animation = 2,
    material_animation = 3,
    state_parameters = 4,
};

struct ArticleGraphRootRecord {
    std::uint64_t file_name_hash{};
    std::uint64_t root_name_hash{};
    std::uint32_t group_kind{};
    std::uint32_t slot_index{};
    std::uint32_t state_index{};
    ArticleGraphRootKind kind{};
    std::uint32_t node_index{};
};

struct ArticleGraphNodeRecord {
    std::uint32_t logical_bytes{};
    std::uint32_t first_word{};
    std::uint32_t word_count{};
    std::uint32_t first_edge{};
    std::uint32_t edge_count{};
    std::uint32_t storage_flags{};
};

struct ArticleGraphEdgeRecord {
    std::uint32_t source_byte_offset{};
    std::uint32_t target_node{};
};

class ArticleGraphsView final {
public:
    [[nodiscard]] bool open(SectionView section) noexcept;
    [[nodiscard]] bool valid() const noexcept;
    [[nodiscard]] std::uint32_t root_count() const noexcept;
    [[nodiscard]] std::uint32_t node_count() const noexcept;
    [[nodiscard]] std::uint32_t edge_count() const noexcept;
    [[nodiscard]] std::uint32_t word_count() const noexcept;
    [[nodiscard]] ArticleGraphRootRecord root(std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleGraphRootRecord find_root(
        std::uint64_t file_name_hash,
        std::uint64_t root_name_hash,
        std::uint32_t group_kind,
        std::uint32_t slot_index,
        std::uint32_t state_index,
        ArticleGraphRootKind kind) const noexcept;
    [[nodiscard]] ArticleGraphNodeRecord node(std::uint32_t index) const noexcept;
    [[nodiscard]] ArticleGraphEdgeRecord edge(std::uint32_t index) const noexcept;
    [[nodiscard]] std::uint32_t word(std::uint32_t index) const noexcept;
    [[nodiscard]] std::uint8_t source_byte(
        std::uint32_t node_index,
        std::uint32_t byte_offset) const noexcept;

private:
    SectionView section_{};
    std::uint32_t root_count_{};
    std::uint32_t node_count_{};
    std::uint32_t edge_count_{};
    std::uint32_t word_count_{};
    std::uint64_t roots_offset_{};
    std::uint64_t nodes_offset_{};
    std::uint64_t edges_offset_{};
    std::uint64_t words_offset_{};
};

} // namespace pf::ssbm

#endif
