#!/usr/bin/env python3
"""Write a timestamp-stable inventory of externally provided native symbols."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from plan_native_root_closure import external_definition_index, read_object_list


def encode_topology(object_list: Path, *, nm: Path) -> bytes:
    object_files = read_object_list(object_list.resolve())
    definitions = external_definition_index(object_files, nm=nm.resolve())
    payload = {
        "schema": 1,
        "objects": sorted(path.resolve().name for path in object_files),
        "definitions": [
            {"symbol": symbol, "provider_objects": list(providers)}
            for symbol, providers in definitions.items()
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def write_if_changed(path: Path, data: bytes) -> bool:
    path = path.resolve()
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as temporary:
            temporary.write(data)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-list", required=True, type=Path)
    parser.add_argument("--nm", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    changed = write_if_changed(
        args.output, encode_topology(args.object_list, nm=args.nm)
    )
    print(f"native-provider-topology={'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
