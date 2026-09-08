#include "effect_particles.h"
#include "mapped_pack.h"

#include <cstddef>
#include <cstdio>
#include <span>
#include <string_view>

namespace {

[[nodiscard]] std::uint64_t name_hash(std::string_view name) noexcept
{
    return pf::ssbm::stable_name_hash({
        reinterpret_cast<const std::byte*>(name.data()), name.size()});
}

[[nodiscard]] bool run(const char* path) noexcept
{
    pf::ssbm::MappedPack pack;
    const auto pack_status = pack.open(path);
    if (pack_status != pf::ssbm::PackStatus::ok) {
        std::fprintf(stderr, "ssbm-effect-pack=map-fail status=%u\n",
            static_cast<unsigned>(pack_status));
        return false;
    }
    const auto section = pack.view().find(
        pf::ssbm::SectionKind::effect_data,
        name_hash("effect.particle_banks.v2"));
    pf::ssbm::EffectParticleView effects;
    if (!effects.open(section) || effects.bank_count() == 0 ||
        effects.generator_count() == 0) {
        std::fputs("ssbm-effect-pack=view-fail\n", stderr);
        return false;
    }
    const auto common = effects.find(name_hash("EfCoData.dat"));
    const auto menu = effects.find(name_hash("EfMnData.dat"));
    const auto peach = effects.find(name_hash("EfPeData.dat"));
    if (common.file_name_hash == 0 || menu.file_name_hash == 0 ||
        peach.file_name_hash == 0 || common.generator_count == 0 ||
        (common.presence_flags & 1U) == 0 ||
        peach.generator_count != 0 || peach.texture_count != 0 ||
        peach.model_count != 1 || peach.presence_flags != 0) {
        std::fputs("ssbm-effect-pack=required-bank-fail\n", stderr);
        return false;
    }
    std::printf(
        "ssbm-effect-pack=peach start=%d generators=%u textures=%u models=%u flags=%u\n",
        peach.effect_id_start, peach.generator_count, peach.texture_count,
        peach.model_count, peach.presence_flags);
    bool found_generator = false;
    for (std::uint32_t index = 0; index < common.generator_count; ++index) {
        const auto generator = effects.generator(common, index);
        if (generator.present) {
            found_generator = !generator.bytecode.empty();
            break;
        }
    }
    if (!found_generator) {
        std::fputs("ssbm-effect-pack=generator-fail\n", stderr);
    }
    return found_generator;
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2 || !run(argv[1])) {
        std::fputs("ssbm-effect-pack=fail\n", stderr);
        return 1;
    }
    std::puts("ssbm-effect-pack=pass");
    return 0;
}
