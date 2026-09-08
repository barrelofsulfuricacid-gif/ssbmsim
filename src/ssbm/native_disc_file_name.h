#ifndef PF_SSBM_NATIVE_DISC_FILE_NAME_H
#define PF_SSBM_NATIVE_DISC_FILE_NAME_H

#include <cstddef>
#include <cstdint>
#include <string_view>

namespace pf::ssbm {

// Melee's DVD helpers accept paths such as "/GrPs" and resolve the DAT
// extension before opening the file.  Native archive lookups bypass those
// helpers, so reproduce that filename contract while hashing without an
// allocation or filesystem access.
[[nodiscard]] inline std::uint64_t native_disc_file_name_hash(
    const char* disc_path) noexcept
{
    if (disc_path == nullptr) return 0;

    std::string_view name{disc_path};
    const auto slash = name.find_last_of("/\\");
    if (slash != std::string_view::npos) name.remove_prefix(slash + 1);

    constexpr std::uint64_t fnv_offset = 14695981039346656037ULL;
    constexpr std::uint64_t fnv_prime = 1099511628211ULL;
    std::uint64_t value = fnv_offset;
    const auto append = [&value](char byte) noexcept {
        value ^= static_cast<std::uint8_t>(byte);
        value *= fnv_prime;
    };
    for (const char byte : name) append(byte);
    if (name.find('.') == std::string_view::npos) {
        for (const char byte : std::string_view{".dat"}) append(byte);
    }
    return value;
}

} // namespace pf::ssbm

#endif
