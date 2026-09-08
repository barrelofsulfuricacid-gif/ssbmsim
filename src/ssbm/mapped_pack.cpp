#include "mapped_pack.h"

#include <span>
#include <utility>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace pf::ssbm {

MappedPack::MappedPack(MappedPack&& other) noexcept
{
    *this = std::move(other);
}

MappedPack& MappedPack::operator=(MappedPack&& other) noexcept
{
    if (this != &other) {
        close();
        view_ = other.view_;
        data_ = other.data_;
        size_ = other.size_;
#if defined(_WIN32)
        file_ = other.file_;
        mapping_ = other.mapping_;
        other.file_ = nullptr;
        other.mapping_ = nullptr;
#else
        file_ = other.file_;
        other.file_ = -1;
#endif
        other.view_ = {};
        other.data_ = nullptr;
        other.size_ = 0;
    }
    return *this;
}

MappedPack::~MappedPack() noexcept
{
    close();
}

PackStatus MappedPack::open(const char* path) noexcept
{
    close();
    if (path == nullptr || path[0] == '\0') {
        return PackStatus::bad_layout;
    }
#if defined(_WIN32)
    const auto file = CreateFileA(
        path,
        GENERIC_READ,
        FILE_SHARE_READ,
        nullptr,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return PackStatus::bad_layout;
    }
    LARGE_INTEGER length{};
    if (GetFileSizeEx(file, &length) == 0 || length.QuadPart <= 0) {
        CloseHandle(file);
        return PackStatus::too_small;
    }
    const auto mapping = CreateFileMappingA(file, nullptr, PAGE_READONLY, 0, 0, nullptr);
    if (mapping == nullptr) {
        CloseHandle(file);
        return PackStatus::bad_layout;
    }
    const auto data = static_cast<const std::byte*>(
        MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0));
    if (data == nullptr) {
        CloseHandle(mapping);
        CloseHandle(file);
        return PackStatus::bad_layout;
    }
    file_ = file;
    mapping_ = mapping;
    data_ = data;
    size_ = static_cast<std::size_t>(length.QuadPart);
#else
    const auto file = ::open(path, O_RDONLY);
    if (file < 0) {
        return PackStatus::bad_layout;
    }
    struct stat status {};
    if (fstat(file, &status) != 0 || status.st_size <= 0) {
        ::close(file);
        return PackStatus::too_small;
    }
    const auto size = static_cast<std::size_t>(status.st_size);
    const auto mapped = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, file, 0);
    if (mapped == MAP_FAILED) {
        ::close(file);
        return PackStatus::bad_layout;
    }
    file_ = file;
    data_ = static_cast<const std::byte*>(mapped);
    size_ = size;
#endif
    const auto result = view_.open({data_, size_});
    if (result != PackStatus::ok) {
        close();
    }
    return result;
}

void MappedPack::close() noexcept
{
    view_ = {};
#if defined(_WIN32)
    if (data_ != nullptr) {
        UnmapViewOfFile(data_);
    }
    if (mapping_ != nullptr) {
        CloseHandle(mapping_);
    }
    if (file_ != nullptr) {
        CloseHandle(file_);
    }
    file_ = nullptr;
    mapping_ = nullptr;
#else
    if (data_ != nullptr) {
        munmap(const_cast<std::byte*>(data_), size_);
    }
    if (file_ >= 0) {
        ::close(file_);
    }
    file_ = -1;
#endif
    data_ = nullptr;
    size_ = 0;
}

const AssetPackView& MappedPack::view() const noexcept
{
    return view_;
}

} // namespace pf::ssbm
