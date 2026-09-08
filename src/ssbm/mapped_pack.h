#ifndef PF_SSBM_MAPPED_PACK_H
#define PF_SSBM_MAPPED_PACK_H

#include "asset_pack.h"

#include <cstddef>

namespace pf::ssbm {

class MappedPack final {
public:
    MappedPack() noexcept = default;
    MappedPack(const MappedPack&) = delete;
    MappedPack& operator=(const MappedPack&) = delete;
    MappedPack(MappedPack&& other) noexcept;
    MappedPack& operator=(MappedPack&& other) noexcept;
    ~MappedPack() noexcept;

    [[nodiscard]] PackStatus open(const char* path) noexcept;
    void close() noexcept;
    [[nodiscard]] const AssetPackView& view() const noexcept;

private:
    AssetPackView view_{};
    const std::byte* data_{};
    std::size_t size_{};
#if defined(_WIN32)
    void* file_{};
    void* mapping_{};
#else
    int file_{-1};
#endif
};

} // namespace pf::ssbm

#endif
