# ssbmsim

A native, headless Super Smash Bros. Melee research simulator targeting
**GALE01 NTSC 1.02 with UCF 0.84**. It compiles pinned gameplay source into
native C/C++.

**Work in progress:** full canonical equivalence is not established.

## Quick start

Supported build: **Linux x86-64, GCC/G++ 11**, including Ubuntu 22.04 in WSL.
The runtime uses a 32-bit ABI to preserve imported layouts. No GUI is required.

```sh
# On Ubuntu 22.04 / WSL Ubuntu 22.04, install system prerequisites once:
sudo apt-get update
sudo apt-get install -y git python3 gcc-11 g++-11 binutils dpkg-dev ca-certificates

git clone https://github.com/barrelofsulfuricacid-gif/ssbmsim.git
cd ssbmsim
./setup.sh
```

Setup downloads checksum-pinned CMake, Ninja and an i686 sysroot, fetches pinned
public source dependencies, applies the checked-in Aurora compatibility patch,
builds the native runner and runs its CTest suite. Downloads stay in
`.toolchains/`; build output stays in `build/`. It does not change global Git
settings or install hooks. Rerun `./setup.sh` after `git pull --ff-only`.

On Windows, install WSL with `wsl --install -d Ubuntu-22.04` and follow the Linux
commands inside Ubuntu. A Windows checkout can also use `./setup.ps1` with its
default WSL distribution; a checkout in WSL's Linux filesystem builds faster.
Native Windows, macOS and ARM gameplay builds are not supported.

## Run a replay

Bring your own **extracted GALE01 NTSC 1.02 game files** and `.slp` recording.
No disc images, extracted game assets, private replay corpus, or prebuilt asset
packs are distributed here. Install .NET 8 and Node.js/npm as described in
[setup](docs/setup.md), then run:

```sh
./setup.sh --replay-tools --assets /path/to/extracted-game-files
python3 tools/ssbm_native_full_match.py /path/to/match.slp \
  --parser-prefix tools/replay \
  --runner build/native/ssbm_native_replay_runner \
  --asset-pack build/assets/gale01.pack \
  --report build/match-report.json
```

The asset compiler runs once; replay execution consumes the resulting pack.
The command validates replay admission, runs the native simulation, and compares
recorded fields. A divergence or unsupported path is a diagnostic result, not a
successful qualification. See [replay validation](docs/replays.md) for scope,
configuration and the separate Dolphin oracle workflow.

## Contribute

Start with [CONTRIBUTING.md](CONTRIBUTING.md), the
[architecture](docs/architecture/ssbm_native_runtime.md), and
[dependency provenance](docs/dependencies.md). Public contributions use the same
setup and tests as CI. Original project code is under [0BSD](LICENSE);
third-party code retains its own terms in [THIRD_PARTY.md](THIRD_PARTY.md).
