#!/usr/bin/env python3
"""Check tracked public files for host paths and accidentally tracked private data.

Complement this conservative check with Gitleaks and a manual content review.
Optional SSBMSIM_PRIVATE_TERMS is a JSON array of private strings supplied only
in the local environment, never committed into the detector itself.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
terms = json.loads(os.environ.get("SSBMSIM_PRIVATE_TERMS", "[]"))
patterns = [
    ("personal Windows path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s\"<>]+", re.I)),
    ("personal Unix path", re.compile(r"/(?:home|Users)/[^\s\"<>]+")),
    ("Windows drive mount", re.compile(r"/mnt/[a-z]/Users/", re.I)),
    ("private network address", re.compile(r"\b(?:192\.168\.[0-9]+\.[0-9]+|10\.[0-9]+\.[0-9]+\.[0-9]+)\b")),
]
blocked = {".slp", ".iso", ".gcm", ".dat", ".usd", ".pack", ".sav", ".dmp", ".xlsx", ".docx"}
failures = []
for name in filter(None, files):
    path = root / name
    if path.suffix.lower() in blocked or name.startswith((".toolchains/", "build/")):
        failures.append((name, "private/generated artifact"))
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        failures.append((name, "unexpected binary file"))
        continue
    for label, pattern in patterns:
        if pattern.search(text):
            failures.append((name, label))
    if any(term.casefold() in (name + "\n" + text).casefold() for term in terms if term):
        failures.append((name, "private term"))
for name, label in failures:
    print(name + ": " + label)
print("Public-tree check:", len([f for f in files if f]), "files;", len(failures), "findings")
sys.exit(bool(failures))
