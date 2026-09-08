# Dependency pins and setup prior art

Reviewed for this public release on 2026-09-08. Prefer existing Git, CMake,
CTest, npm lockfiles and Gitleaks workflows; the small setup wrapper coordinates
the project's unusual GCC 11/i686 ABI and hash-checked source adaptation.

| Dependency | Pin | Compatibility / provenance |
| --- | --- | --- |
| doldecomp/melee | `ae5898ee0dfda41b34fdf846f7d680a33e14779d` | Native gameplay authority; [getting started](https://doldecomp.github.io/melee/getting_started.html), [repository](https://github.com/doldecomp/melee) |
| Aurora | `f8573d34e632aea81039526a728b34f373d247ef` plus `dependencies/aurora-strict-c.patch` | MIT host SDK headers; [upstream](https://github.com/encounter/aurora); patch preserves all six header contents with normalized LF hashes |
| HSDLib fork | `5cf0c4d2d2f0d8d9301f3ed56c3cb826ee80536b` | MIT offline asset graph reader; [fork](https://github.com/barrelofsulfuricacid-gif/HSDLib), [upstream](https://github.com/Ploaj/HSDLib) |
| CMake / Ninja | 4.4.0 / 1.13.2 | Existing checksum locks retained; [CMake releases](https://github.com/Kitware/CMake/releases), [Ninja releases](https://github.com/ninja-build/ninja/releases) |
| Linux i686 sysroot | `dependencies/ssbm-linux-i686.lock.tsv` | GCC 11/Ubuntu package sizes and SHA-256 verified before extraction |
| Slippi parser | 9.1.2 | `tools/replay/package-lock.json`; [upstream](https://github.com/project-slippi/slippi-js) |
| Gitleaks release audit | v8.30.1 | [releases](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), [issues](https://github.com/gitleaks/gitleaks/issues); redact output when scanning secrets |

[CMake presets](https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html)
and standard configure/build/CTest commands were reviewed. The retired project's
presets selected unrelated SDL/web targets and machine-oriented toolchain setup;
the public entry point configures only the current native simulator. It uses the
same CMake target graph and does not introduce another build system.

The native ABI cannot be replaced by a generic host compiler preset without
changing structure layouts. The existing package bootstrap is reused for that
reason. A plain Git diff of the Aurora header fixes replaces a dependency on
private Git history. Upstream revision and patched header hashes remain checked.
No dependency pin floats automatically; upgrading requires source/readiness
validation and review. Automated force-pushing of private vendor branches is
not included in this public release.

Gitleaks detects credentials, while `tools/check_public_tree.py` covers accidental
host paths and private artifacts. Neither guarantees discovery of every kind of
personal information; human review remains part of preparing public diagnostics.
