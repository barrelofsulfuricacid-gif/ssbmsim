#include "joint_trees.h"

#include <bit>
#include <cstddef>
#include <limits>

namespace pf::ssbm {
namespace {

constexpr std::uint32_t header_bytes = 96;

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

[[nodiscard]] bool range_fits(
    std::uint64_t offset,
    std::uint64_t size,
    std::size_t total) noexcept
{
    return offset <= total && size <= total - offset;
}

[[nodiscard]] bool multiply_fits(
    std::uint64_t count,
    std::uint64_t stride,
    std::uint64_t& result) noexcept
{
    if (count != 0 && stride > std::numeric_limits<std::uint64_t>::max() / count) {
        return false;
    }
    result = count * stride;
    return true;
}

} // namespace

bool JointTreesView::open(SectionView section) noexcept
{
    *this = {};
    if (section.kind != SectionKind::animation_data ||
        section.schema_version != joint_trees_schema ||
        section.stride != joint_record_bytes ||
        section.bytes.size() < header_bytes ||
        read_u32(section.bytes, 0) != joint_trees_schema ||
        read_u32(section.bytes, 20) != joint_tree_record_bytes ||
        read_u32(section.bytes, 24) != joint_record_bytes ||
        read_u32(section.bytes, 28) != joint_reference_record_bytes ||
        read_u32(section.bytes, 32) != joint_rvalue_record_bytes) {
        return false;
    }
    tree_count_ = read_u32(section.bytes, 4);
    joint_count_ = read_u32(section.bytes, 8);
    reference_count_ = read_u32(section.bytes, 12);
    rvalue_count_ = read_u32(section.bytes, 16);
    trees_offset_ = read_u64(section.bytes, 40);
    joints_offset_ = read_u64(section.bytes, 48);
    references_offset_ = read_u64(section.bytes, 56);
    rvalues_offset_ = read_u64(section.bytes, 64);
    blob_offset_ = read_u64(section.bytes, 72);
    std::uint64_t tree_bytes = 0;
    std::uint64_t joint_bytes = 0;
    std::uint64_t reference_bytes = 0;
    std::uint64_t rvalue_bytes = 0;
    if (section.count != joint_count_ ||
        !multiply_fits(tree_count_, joint_tree_record_bytes, tree_bytes) ||
        !multiply_fits(joint_count_, joint_record_bytes, joint_bytes) ||
        !multiply_fits(reference_count_, joint_reference_record_bytes,
            reference_bytes) ||
        !multiply_fits(rvalue_count_, joint_rvalue_record_bytes, rvalue_bytes) ||
        !range_fits(trees_offset_, tree_bytes, section.bytes.size()) ||
        !range_fits(joints_offset_, joint_bytes, section.bytes.size()) ||
        trees_offset_ < header_bytes ||
        joints_offset_ < trees_offset_ + tree_bytes ||
        references_offset_ < joints_offset_ + joint_bytes ||
        rvalues_offset_ < references_offset_ + reference_bytes ||
        blob_offset_ < rvalues_offset_ + rvalue_bytes ||
        blob_offset_ > section.bytes.size()) {
        *this = {};
        return false;
    }
    section_ = section;

    std::uint32_t expected_joint = 0;
    std::uint32_t expected_reference = 0;
    std::uint32_t expected_rvalue = 0;
    for (std::uint32_t tree_index = 0; tree_index < tree_count_; ++tree_index) {
        const auto offset = trees_offset_ +
            static_cast<std::uint64_t>(tree_index) * joint_tree_record_bytes;
        const auto raw_joint_offset = read_u64(section.bytes, offset + 16);
        const auto count = read_u32(section.bytes, offset + 24);
        if (raw_joint_offset < joints_offset_ ||
            (raw_joint_offset - joints_offset_) % joint_record_bytes != 0U ||
            (raw_joint_offset - joints_offset_) / joint_record_bytes != expected_joint ||
            count == 0U || count > joint_count_ - expected_joint) {
            *this = {};
            return false;
        }
        const auto tree_first = expected_joint;
        const auto tree_end = expected_joint + count;
        std::uint32_t non_roots = 0;
        std::uint32_t linked_children = 0;
        for (std::uint32_t local = 0; local < count; ++local) {
            const auto global = tree_first + local;
            const auto joint_offset = joints_offset_ +
                static_cast<std::uint64_t>(global) * joint_record_bytes;
            const auto parent = std::bit_cast<std::int32_t>(
                read_u32(section.bytes, joint_offset));
            const auto first_child = std::bit_cast<std::int32_t>(
                read_u32(section.bytes, joint_offset + 4));
            const auto next_sibling = std::bit_cast<std::int32_t>(
                read_u32(section.bytes, joint_offset + 8));
            const auto name_offset = read_u64(section.bytes, joint_offset + 16);
            const auto name_size = read_u32(section.bytes, joint_offset + 24);
            const auto inverse_present = read_u32(section.bytes, joint_offset + 28);
            const auto display_present = read_u32(section.bytes, joint_offset + 116);
            const auto first_reference = read_u32(section.bytes, joint_offset + 120);
            const auto reference_count = read_u32(section.bytes, joint_offset + 124);
            const auto spline_present = read_u32(section.bytes, joint_offset + 128);
            const auto spline_type = read_u32(section.bytes, joint_offset + 132);
            const auto spline_num_cv = std::bit_cast<std::int32_t>(
                read_u32(section.bytes, joint_offset + 136));
            const auto spline_cv_count = read_u32(section.bytes, joint_offset + 148);
            const auto spline_length_count = read_u32(section.bytes, joint_offset + 152);
            const auto spline_segment_count = read_u32(section.bytes, joint_offset + 156);
            const auto spline_cv_offset = read_u64(section.bytes, joint_offset + 160);
            const auto spline_length_offset = read_u64(section.bytes, joint_offset + 168);
            const auto spline_segment_offset = read_u64(section.bytes, joint_offset + 176);
            std::uint64_t spline_cv_bytes = 0;
            std::uint64_t spline_length_bytes = 0;
            std::uint64_t spline_segment_bytes = 0;
            const bool spline_sizes_valid =
                multiply_fits(spline_cv_count, 12U, spline_cv_bytes) &&
                multiply_fits(spline_length_count, 4U, spline_length_bytes) &&
                multiply_fits(spline_segment_count, 20U, spline_segment_bytes);
            const bool spline_valid = spline_present == 0U
                ? spline_type == 0U && spline_num_cv == 0 &&
                    spline_cv_count == 0U && spline_length_count == 0U &&
                    spline_segment_count == 0U && spline_cv_offset == 0U &&
                    spline_length_offset == 0U && spline_segment_offset == 0U
                : spline_present == 1U && spline_type <= 3U &&
                    spline_num_cv > 1 && spline_sizes_valid &&
                    spline_cv_offset >= blob_offset_ &&
                    spline_length_offset >= blob_offset_ &&
                    spline_segment_offset >= blob_offset_ &&
                    range_fits(spline_cv_offset, spline_cv_bytes,
                        section.bytes.size()) &&
                    range_fits(spline_length_offset, spline_length_bytes,
                        section.bytes.size()) &&
                    range_fits(spline_segment_offset, spline_segment_bytes,
                        section.bytes.size());
            if ((parent != -1 &&
                 (parent < static_cast<std::int32_t>(tree_first) ||
                  parent >= static_cast<std::int32_t>(global))) ||
                (first_child != -1 &&
                 (first_child <= static_cast<std::int32_t>(global) ||
                  first_child >= static_cast<std::int32_t>(tree_end))) ||
                (next_sibling != -1 &&
                 (next_sibling <= static_cast<std::int32_t>(global) ||
                  next_sibling >= static_cast<std::int32_t>(tree_end))) ||
                !range_fits(name_offset, name_size, section.bytes.size()) ||
                name_offset < blob_offset_ || inverse_present > 1U ||
                display_present > 1U || first_reference != expected_reference ||
                reference_count > reference_count_ - expected_reference ||
                !spline_valid) {
                *this = {};
                return false;
            }
            for (std::uint32_t reference_index = 0;
                 reference_index < reference_count;
                 ++reference_index) {
                const auto reference_offset = references_offset_ +
                    static_cast<std::uint64_t>(expected_reference + reference_index) *
                        joint_reference_record_bytes;
                const auto reference_type = read_u32(section.bytes, reference_offset + 4);
                const auto first_rvalue = read_u32(section.bytes, reference_offset + 8);
                const auto rvalue_count = read_u32(section.bytes, reference_offset + 12);
                const auto target = std::bit_cast<std::int32_t>(
                    read_u32(section.bytes, reference_offset + 20));
                const bool type_known = reference_type == 0U ||
                    reference_type == 0x10000000U ||
                    reference_type == 0x20000000U ||
                    reference_type == 0x30000000U ||
                    reference_type == 0x40000000U;
                if (!type_known || first_rvalue != expected_rvalue ||
                    rvalue_count > rvalue_count_ - expected_rvalue ||
                    (reference_type == 0x10000000U &&
                     (target < static_cast<std::int32_t>(tree_first) ||
                      target >= static_cast<std::int32_t>(tree_end))) ||
                    (reference_type != 0x10000000U && target != -1)) {
                    *this = {};
                    return false;
                }
                for (std::uint32_t rvalue_index = 0;
                     rvalue_index < rvalue_count;
                     ++rvalue_index) {
                    const auto rvalue_offset = rvalues_offset_ +
                        static_cast<std::uint64_t>(expected_rvalue + rvalue_index) *
                            joint_rvalue_record_bytes;
                    const auto rvalue_target = std::bit_cast<std::int32_t>(
                        read_u32(section.bytes, rvalue_offset + 4));
                    if (rvalue_target != -1 &&
                        (rvalue_target < static_cast<std::int32_t>(tree_first) ||
                         rvalue_target >= static_cast<std::int32_t>(tree_end))) {
                        *this = {};
                        return false;
                    }
                }
                expected_rvalue += rvalue_count;
            }
            expected_reference += reference_count;
            non_roots += parent == -1 ? 0U : 1U;
            if (next_sibling != -1) {
                const auto sibling_offset = joints_offset_ +
                    static_cast<std::uint64_t>(next_sibling) * joint_record_bytes;
                if (std::bit_cast<std::int32_t>(
                        read_u32(section.bytes, sibling_offset)) != parent) {
                    *this = {};
                    return false;
                }
            }
            std::int32_t child = first_child;
            std::uint32_t chain_count = 0;
            while (child != -1) {
                if (++chain_count > count) {
                    *this = {};
                    return false;
                }
                const auto child_offset = joints_offset_ +
                    static_cast<std::uint64_t>(child) * joint_record_bytes;
                if (std::bit_cast<std::int32_t>(
                        read_u32(section.bytes, child_offset)) !=
                    static_cast<std::int32_t>(global)) {
                    *this = {};
                    return false;
                }
                ++linked_children;
                child = std::bit_cast<std::int32_t>(
                    read_u32(section.bytes, child_offset + 8));
            }
        }
        if (linked_children != non_roots) {
            *this = {};
            return false;
        }
        expected_joint = tree_end;
    }
    if (expected_joint != joint_count_ || expected_reference != reference_count_ ||
        expected_rvalue != rvalue_count_) {
        *this = {};
        return false;
    }
    return true;
}

bool JointTreesView::valid() const noexcept { return !section_.bytes.empty(); }
std::uint32_t JointTreesView::tree_count() const noexcept { return tree_count_; }
std::uint32_t JointTreesView::joint_count() const noexcept { return joint_count_; }
std::uint32_t JointTreesView::reference_count() const noexcept { return reference_count_; }
std::uint32_t JointTreesView::rvalue_count() const noexcept { return rvalue_count_; }

JointTreeRecord JointTreesView::tree(std::uint32_t index) const noexcept
{
    if (!valid() || index >= tree_count_) return {};
    const auto offset = trees_offset_ +
        static_cast<std::uint64_t>(index) * joint_tree_record_bytes;
    return {
        read_u64(section_.bytes, offset),
        read_u64(section_.bytes, offset + 8),
        static_cast<std::uint32_t>((read_u64(section_.bytes, offset + 16) -
            joints_offset_) / joint_record_bytes),
        read_u32(section_.bytes, offset + 24),
    };
}

JointTreeRecord JointTreesView::find(
    std::uint64_t file_name_hash,
    std::uint64_t root_name_hash) const noexcept
{
    for (std::uint32_t index = 0; index < tree_count_; ++index) {
        const auto candidate = tree(index);
        if (candidate.file_name_hash == file_name_hash &&
            (root_name_hash == 0U || candidate.root_name_hash == root_name_hash)) {
            return candidate;
        }
    }
    return {};
}

JointRecord JointTreesView::joint(std::uint32_t index) const noexcept
{
    if (!valid() || index >= joint_count_) return {};
    const auto offset = joints_offset_ +
        static_cast<std::uint64_t>(index) * joint_record_bytes;
    const auto name_offset = read_u64(section_.bytes, offset + 16);
    const auto name_size = read_u32(section_.bytes, offset + 24);
    const auto spline_present = read_u32(section_.bytes, offset + 128) != 0U;
    const auto spline_cv_count = read_u32(section_.bytes, offset + 148);
    const auto spline_length_count = read_u32(section_.bytes, offset + 152);
    const auto spline_segment_count = read_u32(section_.bytes, offset + 156);
    const auto spline_cv_offset = read_u64(section_.bytes, offset + 160);
    const auto spline_length_offset = read_u64(section_.bytes, offset + 168);
    const auto spline_segment_offset = read_u64(section_.bytes, offset + 176);
    JointRecord result{
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 4)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 8)),
        read_u32(section_.bytes, offset + 12),
        {reinterpret_cast<const char*>(section_.bytes.data() + name_offset), name_size},
        read_u32(section_.bytes, offset + 28) != 0U,
        {},
        {},
        read_u32(section_.bytes, offset + 116) != 0U,
        read_u32(section_.bytes, offset + 120),
        read_u32(section_.bytes, offset + 124),
        spline_present,
        read_u32(section_.bytes, offset + 132),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 136)),
        read_u32(section_.bytes, offset + 140),
        read_u32(section_.bytes, offset + 144),
        spline_present
            ? section_.bytes.subspan(static_cast<std::size_t>(spline_cv_offset),
                static_cast<std::size_t>(spline_cv_count) * 12U)
            : std::span<const std::byte>{},
        spline_present
            ? section_.bytes.subspan(static_cast<std::size_t>(spline_length_offset),
                static_cast<std::size_t>(spline_length_count) * 4U)
            : std::span<const std::byte>{},
        spline_present
            ? section_.bytes.subspan(static_cast<std::size_t>(spline_segment_offset),
                static_cast<std::size_t>(spline_segment_count) * 20U)
            : std::span<const std::byte>{},
    };
    for (std::size_t i = 0; i < result.srt_bits.size(); ++i)
        result.srt_bits[i] = read_u32(section_.bytes, offset + 32 + i * 4);
    for (std::size_t i = 0; i < result.inverse_bits.size(); ++i)
        result.inverse_bits[i] = read_u32(section_.bytes, offset + 68 + i * 4);
    return result;
}

JointReferenceRecord JointTreesView::reference(std::uint32_t index) const noexcept
{
    if (!valid() || index >= reference_count_) return {};
    const auto offset = references_offset_ +
        static_cast<std::uint64_t>(index) * joint_reference_record_bytes;
    return {
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        read_u32(section_.bytes, offset + 4),
        read_u32(section_.bytes, offset + 8),
        read_u32(section_.bytes, offset + 12),
        read_u32(section_.bytes, offset + 16),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 20)),
        read_u32(section_.bytes, offset + 24),
        read_u32(section_.bytes, offset + 28),
    };
}

JointRvalueRecord JointTreesView::rvalue(std::uint32_t index) const noexcept
{
    if (!valid() || index >= rvalue_count_) return {};
    const auto offset = rvalues_offset_ +
        static_cast<std::uint64_t>(index) * joint_rvalue_record_bytes;
    return {
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset)),
        std::bit_cast<std::int32_t>(read_u32(section_.bytes, offset + 4)),
    };
}

} // namespace pf::ssbm
