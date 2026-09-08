# Setup and troubleshooting

## Supported environment

Ubuntu 22.04 x86-64 with Python 3.10+, GCC/G++ 11, Git, GNU binutils and
`dpkg-deb`. Ubuntu 24.04 may install GCC/G++ 11 from its package repositories,
but the pinned compatibility lane uses GCC 11 and the Ubuntu 22.04 i686 sysroot.
Linux must support 32-bit x86 executables. WSL 2 on x86-64 is supported; ARM
and native Windows/macOS are not established build lanes.

```sh
sudo apt-get update
sudo apt-get install -y git python3 gcc-11 g++-11 binutils dpkg-dev ca-certificates
./setup.sh --jobs 8
```

The script itself runs without sudo and installs only into this checkout.
Internet access to GitHub and archive.ubuntu.com is required on the first run.
Allow several gigabytes for sources, sysroot and build products. Use `--jobs 2`
on memory-constrained machines. `./setup.sh --help` lists options, including
`--configure-only` and `--build-dir`.

The six Aurora headers retain the validated fork content with LF line endings;
the public build fetches the pinned MIT upstream and applies the published
patch. Both source revisions and header bytes are verified during import.
Never disable the source/hash gates to get a build through.

## Optional game asset compiler

Install the .NET 8 SDK using [Microsoft's Linux instructions](https://learn.microsoft.com/dotnet/core/install/linux).
`dotnet --list-sdks` should list an 8.x SDK. Supply the directory containing the
complete extracted files from your GALE01 NTSC 1.02 disc, including fighter,
stage, common and effect archives. Extraction of the disc image itself is outside
this setup script; follow your disc extraction tool's instructions. The compiler
rejects missing required archives. A different disc revision is unsupported.

Release validation used SDK 8.0.424. The asset-compiler directory's `global.json`
pins that version when running commands from that directory.

```sh
./setup.sh --assets /path/to/extracted-game-files
```

This fetches the pinned public HSDLib fork and writes `build/assets/gale01.pack`
and its provenance manifest. Keep both local. Do not upload the input files,
generated pack, game memory dumps, or asset-bearing diagnostics to GitHub.

## Optional replay parser

Install a maintained [Node.js LTS release](https://nodejs.org/en/download) with
npm. Then `./setup.sh --replay-tools` installs the exact package-lock tree using
`npm ci --ignore-scripts`. The parser is offline tooling, outside the native link
graph. It can be installed separately with `npm ci --ignore-scripts --prefix tools/replay`.

## Updating and rebuilding

```sh
git pull --ff-only
./setup.sh
python3 tools/test.py
```

Setup reuses verified downloads and checks dependency revisions. If a dependency
checkout has been edited, keep your work separately and restore it deliberately;
setup does not reset user edits. Changed toolchain/compiler settings require a
new build directory, for example `./setup.sh --build-dir build/native-clean`.
Checksum errors should be investigated against the lock, not bypassed. Remove
only the identified corrupt download from `.toolchains/downloads` before retrying.

On Windows, use WSL Ubuntu 22.04 as the default distribution before invoking
`setup.ps1`, or run `setup.sh` directly inside the chosen distribution. Pass Linux
paths to `--assets`. For speed, clone into WSL's Linux filesystem instead of a
Windows drive mount. No mouse control or Windows compiler setup is needed.
