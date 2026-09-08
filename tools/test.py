#!/usr/bin/env python3
"""Run tool and source regressions using the dependencies fetched by setup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "tools/ssbm_native_import.json").read_text())
env = os.environ.copy()
for name, revision, variable in [
    ("melee", spec["decomp_revision"], "PF_SSBM_DECOMP_SOURCE_DIR"),
    ("aurora", spec["dependencies"]["aurora"]["revision"], "PF_AURORA_SOURCE_DIR"),
]:
    path = root / ".toolchains/sources" / (name + "-" + revision[:12])
    if not path.is_dir():
        raise SystemExit("Run ./setup.sh first: missing " + name)
    env[variable] = str(path)
env["PF_SSBM_I686_SYSROOT"] = json.loads((root / ".toolchains/i686/manifest.json").read_text())["sysroot"]
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests/tools"], cwd=root, env=env, check=True)
for script in ["test_shared_byte_flags.py", "test_stage_flag_words.py"]:
    subprocess.run([sys.executable, root / "tests/tools" / script], cwd=root, env=env, check=True)
if shutil.which("node"):
    subprocess.run(["node", "--test", "tests/tools/test_ssbm_replay_mods.mjs"], cwd=root, check=True)
else:
    print("Optional JavaScript tests skipped: install Node.js to run them.")
