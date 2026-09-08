#!/usr/bin/env python3
"""Inventory pinned Slippi gameplay injections without inferring qualification.

Textual implementation references are navigation aids only. This audit exposes
missing references; it does not prove equivalent behavior or replay code scope.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "fcf47f10dc244152c2ebaa3a9dec142ea42243b7"
LISTS = ("netplay", "console_core", "console_UCF_084", "console_stages_stadium")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asm-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(
        ["git", "-C", str(args.asm_root), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise SystemExit(f"Unreviewed Slippi revision: {revision}")
    native_files = [*sorted((root / "tools/host_adaptations").glob("*.json")),
                    *sorted((root / "src/ssbm/native_compat").glob("*.[ch]"))]
    native_text = {p: p.read_text() for p in native_files}
    hooks = {}
    lists = []
    for name in LISTS:
        path = args.asm_root / f"Output/InjectionLists/list_{name}.json"
        data = path.read_bytes()
        lists.append({"path": str(path.relative_to(args.asm_root)),
                      "sha256": hashlib.sha256(data).hexdigest()})
        for entry in json.loads(data)["Details"]:
            if "[affects-gameplay]" not in entry.get("Tags", ""):
                continue
            source = entry["Annotation"]
            address = entry["InjectionAddress"].upper()
            key = (address, source)
            if key not in hooks:
                hook_file = args.asm_root / source
                refs = [str(p.relative_to(root)) for p, text in native_text.items()
                        if source in text or f"0x{address}" in text]
                hooks[key] = {
                    "address": "0x" + address, "source": source,
                    "source_sha256": hashlib.sha256(hook_file.read_bytes()).hexdigest(),
                    "profiles": [], "implementation_references": refs,
                    "audit_status": "behavior-and-configuration-review-pending",
                }
            hooks[key]["profiles"].append(name)
    result = {
        "schema": 1, "slippi_revision": revision,
        "scope": "Gameplay-tagged injections in the listed profiles; custom and other recorded code lists require separate review.",
        "claim_boundary": "inventory-and-textual-references-not-behavioral-qualification",
        "injection_lists": lists, "hooks": list(hooks.values()),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"hooks": len(hooks), "without_textual_reference": sum(
        not h["implementation_references"] for h in hooks.values())}))


if __name__ == "__main__":
    main()
