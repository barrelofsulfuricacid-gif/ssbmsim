"""Exercise the actual star-KO launch expression against captured state bits."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from apply_source_adaptation import apply_adaptation


class StarKoVelocityTests(unittest.TestCase):
    def test_camera_relative_launch_matches_four_captured_cases(self):
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        decomp = Path(source_root)
        spec = json.loads((ROOT / "tools/host_adaptations/ft_0D31.json").read_text())
        adapted = apply_adaptation(
            (decomp / spec["source_path"]).read_bytes(), spec).decode()
        expression = next(r["new"] for r in spec["replacements"]
                          if "Stage_GetCamBoundsTopOffset()" in r["old"])
        self.assertIn(expression, adapted)
        # Values are from finalized Slippi star-KO frames; the scale, duration,
        # and camera bound were independently read from synchronized oracle RAM.
        cases = [
            (250.90736389160156, -1.0531336069107056),
            (250.44313049316406, -1.0495625734329224),
            (250.98033142089844, -1.0536948442459106),
            (252.67662048339844, -1.06674325466156),
        ]
        harness = r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
typedef struct Fighter { struct { float y; } self_vel, cur_pos; } Fighter;
static float Stage_GetCamBoundsTopOffset(void) { return 190.0F; }
static float launch(float y) {
    Fighter f = { { 0 }, { y } }; Fighter* fp = &f;
    int32_t data[5] = { 0, 130, 0, 0, 0 };
    const float scale = 0.6F; memcpy(data + 4, &scale, sizeof(scale));
'''
        harness += expression + "\nreturn f.self_vel.y;\n}\nint main(void) {\n"
        for position, velocity in cases:
            bits = struct.unpack("<I", struct.pack("<f", velocity))[0]
            harness += (f"{{float v=launch({position!r}F); uint32_t bits; "
                        f"memcpy(&bits,&v,4); if(bits!=0x{bits:08x}U)return 1;}}\n")
        harness += "return 0;\n}\n"
        with tempfile.TemporaryDirectory() as temp:
            cfile, binary = Path(temp) / "launch.c", Path(temp) / "launch"
            cfile.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-O2", "-fno-fast-math",
                "-fno-strict-aliasing", "-ffp-contract=off",
                "-I", str(ROOT / "src/ssbm/native_compat"),
                "-I", str(decomp / "extern/dolphin/include"),
                str(cfile), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
