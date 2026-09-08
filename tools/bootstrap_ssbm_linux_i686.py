#!/usr/bin/env python3
"""Materialize the pinned, permission-free Linux i686 native sysroot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePath
import platform
import shutil
import subprocess
import urllib.request


SCHEMA = ("name", "url", "bytes", "sha256")
REQUIRED_OUTPUTS = (
    "usr/lib32/Scrt1.o",
    "usr/lib32/libc.a",
    "usr/lib/gcc/x86_64-linux-gnu/11/32/libgcc.a",
    "usr/lib/gcc/x86_64-linux-gnu/11/32/libstdc++.a",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_lock(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != SCHEMA:
            raise ValueError(f"unexpected i686 lock schema: {reader.fieldnames}")
        entries: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in reader:
            name = row["name"]
            if PurePath(name).name != name or name in seen:
                raise ValueError(f"unsafe or duplicate package name: {name}")
            seen.add(name)
            size = int(row["bytes"])
            digest = row["sha256"].lower()
            if size <= 0 or len(digest) != 64:
                raise ValueError(f"invalid package identity: {name}")
            entries.append(
                {
                    "name": name,
                    "url": row["url"],
                    "bytes": size,
                    "sha256": digest,
                }
            )
    if not entries:
        raise ValueError("empty i686 package lock")
    return entries


def verify_package(path: Path, entry: dict[str, object]) -> None:
    expected_size = int(entry["bytes"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"package size mismatch for {path.name}: "
            f"expected {expected_size}, got {actual_size}"
        )
    expected_hash = str(entry["sha256"])
    actual_hash = sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"package hash mismatch for {path.name}: "
            f"expected {expected_hash}, got {actual_hash}"
        )


def download_package(package_dir: Path, entry: dict[str, object]) -> Path:
    path = package_dir / str(entry["name"])
    if path.is_file():
        verify_package(path, entry)
        return path
    partial = path.with_suffix(path.suffix + ".partial")
    request = urllib.request.Request(
        str(entry["url"]), headers={"User-Agent": "pf-ssbm-i686-bootstrap/1"}
    )
    with urllib.request.urlopen(request, timeout=120) as source:
        with partial.open("wb") as destination:
            shutil.copyfileobj(source, destination)
    verify_package(partial, entry)
    os.replace(partial, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("the SSBM i686 sysroot bootstrap requires Linux x86_64")
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise SystemExit("dpkg-deb is required to extract the pinned packages")

    lock_path = args.lock.resolve()
    entries = load_lock(lock_path)
    lock_sha256 = sha256(lock_path)
    output = args.output.resolve()
    package_dir = output / "packages"
    sysroot = output / f"root-{lock_sha256[:16]}"
    manifest_path = output / "manifest.json"
    package_dir.mkdir(parents=True, exist_ok=True)

    packages = [download_package(package_dir, entry) for entry in entries]
    if not sysroot.exists():
        sysroot.mkdir(parents=True)
        for package in packages:
            subprocess.run(
                [dpkg_deb, "-x", str(package), str(sysroot)], check=True
            )
    for relative in REQUIRED_OUTPUTS:
        if not (sysroot / relative).is_file():
            raise SystemExit(f"incomplete i686 sysroot: missing {relative}")

    manifest = {
        "schema": 1,
        "claim_boundary": "native-linux-i686-toolchain-not-gameplay-coverage",
        "lock": {"path": lock_path.name, "sha256": lock_sha256},
        "packages": entries,
        "sysroot": str(sysroot),
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        "ssbm-linux-i686-sysroot=pass "
        f"packages={len(entries)} root={sysroot} "
        f"sha256={hashlib.sha256(encoded.encode()).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
