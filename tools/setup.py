#!/usr/bin/env python3
"""Reproduce the supported Linux x86-64 / GCC 11 / i686 build locally."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".toolchains"


def run(*args: object, cwd: Path = ROOT) -> None:
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
        return result.hexdigest()


def host_tool(component: str) -> Path:
    with (ROOT / "dependencies/toolchains.lock.tsv").open() as stream:
        row = next(row for row in csv.DictReader(stream, delimiter="\t")
                   if row["component"] == component and row["platform"] == "linux-x86_64")
    downloads = CACHE / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / row["archive"]
    if not archive.exists():
        partial = archive.with_suffix(".partial")
        print("Downloading", row["url"], flush=True)
        with urllib.request.urlopen(row["url"], timeout=120) as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target)
        if digest(partial) != row["sha256"] or partial.stat().st_size != int(row["size"]):
            raise RuntimeError("Downloaded archive failed its checksum: " + component)
        partial.replace(archive)
    if digest(archive) != row["sha256"] or archive.stat().st_size != int(row["size"]):
        raise RuntimeError("Cached archive failed its checksum: " + str(archive))
    destination = CACHE / (component + "-" + row["version"])
    marker = destination / ".complete"
    if not marker.exists():
        destination.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as source:
                source.extractall(destination)
        else:
            with tarfile.open(archive) as source:
                source.extractall(destination, filter="data")
        marker.write_text(row["sha256"] + "\n")
    executable = next(path for path in destination.rglob(component) if path.is_file())
    executable.chmod(executable.stat().st_mode | 0o111)
    return executable


def checkout(name: str, url: str, revision: str, patch: Path | None = None) -> Path:
    destination = CACHE / "sources" / (name + "-" + revision[:12])
    if not (destination / ".git").exists():
        destination.mkdir(parents=True, exist_ok=True)
        run("git", "init", destination)
        run("git", "-C", destination, "fetch", "--depth=1", url, revision)
        run("git", "-C", destination, "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if actual != revision:
        raise RuntimeError("Unexpected dependency revision: " + name)
    if patch:
        clean = subprocess.run(["git", "-C", str(destination), "apply", "--check", str(patch)], capture_output=True)
        if clean.returncode == 0:
            run("git", "-C", destination, "apply", patch)
        else:
            run("git", "-C", destination, "apply", "--reverse", "--check", patch)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 8))
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/native")
    parser.add_argument("--configure-only", action="store_true")
    parser.add_argument("--assets", type=Path, help="Compile your extracted GALE01 DAT directory (requires .NET 8)")
    parser.add_argument("--replay-tools", action="store_true", help="Install the locked Slippi parser (requires Node.js/npm)")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Use Linux x86-64 or an x86-64 WSL Ubuntu distribution.")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    required = ["git", "gcc-11", "g++-11", "dpkg-deb", "ar", "objcopy", "nm"]
    if args.assets:
        required.append("dotnet")
    if args.replay_tools:
        required.extend(["node", "npm"])
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        parser.error("Missing: " + ", ".join(missing) + ". See docs/setup.md for installation commands.")
    cmake, ninja = host_tool("cmake"), host_tool("ninja")
    spec = json.loads((ROOT / "tools/ssbm_native_import.json").read_text())
    melee = checkout("melee", "https://github.com/doldecomp/melee.git", spec["decomp_revision"])
    aurora_spec = spec["dependencies"]["aurora"]
    patch = ROOT / aurora_spec["patch"]
    if digest(patch) != aurora_spec["patch_sha256"]:
        raise RuntimeError("Aurora patch checksum mismatch")
    aurora = checkout("aurora", aurora_spec["repository"], aurora_spec["revision"], patch)
    run(sys.executable, ROOT / "tools/bootstrap_ssbm_linux_i686.py",
        "--lock", ROOT / "dependencies/ssbm-linux-i686.lock.tsv", "--output", CACHE / "i686")
    sysroot = json.loads((CACHE / "i686/manifest.json").read_text())["sysroot"]
    build = args.build_dir.resolve()
    run(cmake, "-S", ROOT, "-B", build, "-G", "Ninja",
        "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG", "-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG",
        "-DCMAKE_C_COMPILER=" + str(shutil.which("gcc-11")),
        "-DCMAKE_CXX_COMPILER=" + str(shutil.which("g++-11")),
        "-DCMAKE_TOOLCHAIN_FILE=" + str(ROOT / "cmake/PFSSBMNativeI686.cmake"),
        "-DPF_SSBM_I686_SYSROOT=" + sysroot,
        "-DPF_SSBM_DECOMP_SOURCE_DIR=" + str(melee), "-DPF_AURORA_SOURCE_DIR=" + str(aurora),
        "-DPF_BUILD_SSBM_DECOMP_IMPORT=ON", "-DBUILD_TESTING=ON")
    if not args.configure_only:
        run(cmake, "--build", build, "--parallel", args.jobs)
        run(cmake.parent / "ctest", "--test-dir", build, "--output-on-failure")
    if args.replay_tools:
        run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=ROOT / "tools/replay")
    if args.assets:
        revision = "5cf0c4d2d2f0d8d9301f3ed56c3cb826ee80536b"
        hsd = checkout("hsdlib", "https://github.com/barrelofsulfuricacid-gif/HSDLib.git", revision)
        output = ROOT / "build/assets"
        output.mkdir(parents=True, exist_ok=True)
        run("dotnet", "run", "--project", ROOT / "tools/ssbm_asset_compiler",
            "--configuration", "Release", "-p:HSDLibSourceDir=" + str(hsd), "--",
            "--input-root", args.assets.resolve(), "--output", output / "gale01.pack",
            "--manifest", output / "gale01.manifest.json", "--hsdlib-revision", revision)
    print("Setup complete. See README.md for replay usage.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Setup failed:", error, file=sys.stderr)
        raise SystemExit(1)
