# Third-party provenance and license boundaries

The root 0BSD license covers original ssbmsim contributions only. It does not
relicense upstream source, source-derived adaptations, patches, or game data.
Existing notices in source files remain authoritative.

| Component | Provenance / terms | Distribution |
| --- | --- | --- |
| Aurora | MIT; [upstream](https://github.com/encounter/aurora) | Fetched at setup; header patch included, with [license](dependencies/Aurora.LICENSE) |
| HSDLib | MIT; [public fork](https://github.com/barrelofsulfuricacid-gif/HSDLib) | Fetched only for asset compilation |
| doldecomp/melee | [upstream](https://github.com/doldecomp/melee); no top-level license grant identified | Fetched at setup; imported/derived logic is not relicensed by 0BSD |
| CMake | BSD-3-Clause; [upstream](https://github.com/Kitware/CMake) | Downloaded release includes its notices |
| Ninja | Apache-2.0; [upstream](https://github.com/ninja-build/ninja) | Downloaded release |
| GCC/glibc/libstdc++ sysroot | Upstream GPL/LGPL and applicable runtime exceptions; package-specific copyright files | Downloaded Ubuntu packages retain their notices |
| @slippi/slippi-js | MIT; [upstream](https://github.com/project-slippi/slippi-js) | Optional npm dependency with package lock |
| Slippi Dolphin / ExiAI | GPL-2.0 family; [fork](https://github.com/vladfi1/slippi-Ishiiruka) | Optional external oracle; patch files preserve upstream terms |
| libmelee | LGPL-3.0 family; [fork](https://github.com/vladfi1/libmelee) | Optional oracle tooling |

Numerical helpers, compatibility code and adaptations may retain additional
upstream provenance in their file comments. Consult those references before
redistribution. No license to Nintendo game assets is provided. Disc images,
extracted archives, generated asset packs and private replays are excluded.

Exact source revisions and setup choices are documented in
[dependencies](docs/dependencies.md). A permissive license on original code does
not imply that a combined gameplay build has the same license.
