#include "native_effect_banks.h"

#include "effect_particles.h"
#include "native_compat/native_archive_root_api.h"
#include "native_compat/native_fail_closed_boundaries.h"

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <span>
#include <string_view>

extern "C" {
void* HSD_MemAlloc(std::intptr_t size);
void pf_ps_install_native_bank(
    int bank,
    void** command_lists,
    int command_count,
    void** texture_groups,
    void* particle_references);
}

namespace pf::ssbm {
namespace {

EffectParticleView effect_banks;
std::array<bool, 65> loaded_banks{};
std::byte texture_present_sentinel{};

struct NativeCommandList {
    std::uint16_t type_flags;
    std::uint16_t texture_group;
    std::uint16_t generator_life;
    std::uint16_t particle_life;
    std::uint32_t kind;
    std::array<std::uint32_t, effect_particle_scalar_count> scalar_bits;
};

struct NativeTextureGroup {
    std::uint32_t image_count;
    std::uint32_t format;
    std::uint32_t palette_format;
    std::uint32_t width;
    std::uint32_t height;
    std::uint16_t palette_count;
    std::uint16_t palette_flags;
};

static_assert(sizeof(NativeCommandList) == 0x3C);
static_assert(sizeof(NativeTextureGroup) == 0x18);

[[nodiscard]] void* startup_allocate(std::size_t size) noexcept
{
    if (size == 0 ||
        size > static_cast<std::size_t>(
            std::numeric_limits<std::intptr_t>::max())) {
        return nullptr;
    }
    return HSD_MemAlloc(static_cast<std::intptr_t>(size));
}

template <typename T>
[[nodiscard]] T* startup_array(std::size_t count) noexcept
{
    if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) {
        return nullptr;
    }
    auto* result = static_cast<T*>(startup_allocate(count * sizeof(T)));
    if (result != nullptr) {
        std::memset(result, 0, count * sizeof(T));
    }
    return result;
}

[[nodiscard]] std::uint64_t name_hash(const char* value) noexcept
{
    if (value == nullptr) {
        return 0;
    }
    const std::string_view text{value};
    return stable_name_hash({
        reinterpret_cast<const std::byte*>(text.data()), text.size()});
}

[[nodiscard]] void* effect_model_table(
    const char* file_name,
    const char* root_name)
{
    // The public effect DAT root starts with the particle and texture-bank
    // pointers. Retail efAsync_LoadSync publishes &root->data (offset 0x08),
    // the first EF_EffectDesc, because efLib indexes lookup->data directly as
    // the descriptor array.
    auto* root = static_cast<std::byte*>(
        pf_ssbm_native_archive_root_require(file_name, root_name));
    return root + 0x08;
}

} // namespace

bool bind_native_effect_banks(const AssetPackView& assets) noexcept
{
    effect_banks = {};
    loaded_banks.fill(false);
    constexpr std::string_view section_name{"effect.particle_banks.v2"};
    const auto section_hash = stable_name_hash({
        reinterpret_cast<const std::byte*>(section_name.data()),
        section_name.size()});
    return effect_banks.open(
        assets.find(SectionKind::effect_data, section_hash));
}

} // namespace pf::ssbm

extern "C" int pf_ssbm_native_effect_bank_load(
    int bank,
    const char* file_name,
    const char* root_name,
    void** model_data)
{
    using namespace pf::ssbm;
    if (!effect_banks.valid()) {
        pf_ssbm_reach_unsupported_boundary("native_effect_asset_pack");
    }
    if (bank < 0 || bank >= static_cast<int>(loaded_banks.size()) ||
        file_name == nullptr || root_name == nullptr || model_data == nullptr) {
        return 0;
    }
    if (loaded_banks[static_cast<std::size_t>(bank)]) {
        *model_data = effect_model_table(file_name, root_name);
        return 1;
    }

    const auto source_bank = effect_banks.find(name_hash(file_name));
    if (source_bank.file_name_hash == 0 ||
        source_bank.generator_index > effect_banks.generator_count() ||
        source_bank.generator_count > effect_banks.generator_count() -
            source_bank.generator_index ||
        source_bank.texture_index > effect_banks.texture_count() ||
        source_bank.texture_count > effect_banks.texture_count() -
            source_bank.texture_index) {
        return 0;
    }

    const auto command_count = static_cast<std::uint64_t>(
        static_cast<std::uint32_t>(source_bank.effect_id_start)) +
        source_bank.generator_count;
    if (source_bank.effect_id_start < 0 ||
        command_count > static_cast<std::uint64_t>(
            std::numeric_limits<int>::max())) {
        return 0;
    }
    void** command_lists = nullptr;
    if (command_count != 0) {
        command_lists = startup_array<void*>(
            static_cast<std::size_t>(command_count));
    }
    void** texture_groups = nullptr;
    if (source_bank.texture_count != 0) {
        texture_groups = startup_array<void*>(source_bank.texture_count);
    }
    if ((command_count != 0 && command_lists == nullptr) ||
        (source_bank.texture_count != 0 && texture_groups == nullptr)) {
        return 0;
    }

    for (std::uint32_t index = 0;
         index < source_bank.generator_count;
         ++index) {
        const auto source = effect_banks.generator(source_bank, index);
        if (!source.present) {
            continue;
        }
        const auto bytes = sizeof(NativeCommandList) + source.bytecode.size();
        auto* command = static_cast<NativeCommandList*>(
            startup_allocate(bytes));
        if (command == nullptr) {
            return 0;
        }
        command->type_flags = source.type_flags;
        command->texture_group =
            std::bit_cast<std::uint16_t>(source.texture_group);
        command->generator_life =
            std::bit_cast<std::uint16_t>(source.generator_life);
        command->particle_life =
            std::bit_cast<std::uint16_t>(source.particle_life);
        command->kind = (source.kind & 0xF1FFFFFFU) | 0x08000000U;
        command->scalar_bits = source.scalar_bits;
        std::memcpy(command + 1, source.bytecode.data(), source.bytecode.size());
        command_lists[static_cast<std::size_t>(source_bank.effect_id_start) +
            index] = command;
    }

    for (std::uint32_t index = 0;
         index < source_bank.texture_count;
         ++index) {
        const auto source = effect_banks.texture(source_bank, index);
        const auto pointer_count = static_cast<std::size_t>(source.image_count) +
            source.palette_count;
        const auto bytes = sizeof(NativeTextureGroup) +
            pointer_count * sizeof(void*);
        auto* texture = static_cast<NativeTextureGroup*>(
            startup_allocate(bytes));
        if (texture == nullptr) {
            return 0;
        }
        *texture = {
            source.image_count,
            source.format,
            source.palette_format,
            source.width,
            source.height,
            source.palette_count,
            source.palette_flags,
        };
        auto** pointers = reinterpret_cast<void**>(texture + 1);
        for (std::size_t pointer = 0; pointer < pointer_count; ++pointer) {
            pointers[pointer] = &texture_present_sentinel;
        }
        texture_groups[index] = texture;
    }

    if ((source_bank.presence_flags & 3U) != 0) {
        pf_ps_install_native_bank(
            bank,
            command_lists,
            static_cast<int>(command_count),
            texture_groups,
            nullptr);
    }
    loaded_banks[static_cast<std::size_t>(bank)] = true;
    *model_data = effect_model_table(file_name, root_name);
    return 1;
}

extern "C" void pf_ssbm_native_effect_bank_require(
    int bank,
    const char* file_name,
    const char* root_name,
    void** model_data)
{
    if (!pf_ssbm_native_effect_bank_load(
            bank, file_name, root_name, model_data)) {
        pf_ssbm_reach_unsupported_boundary("native_effect_bank_missing");
    }
}
