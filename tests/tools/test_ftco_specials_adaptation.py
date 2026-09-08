"""Execute the adapted common side-special entry at its rounding boundary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from apply_source_adaptation import apply_adaptation


class SideSpecialMomentumTests(unittest.TestCase):
    def test_actual_entry_preserves_momentum_rounding_and_call_order(self):
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        decomp = Path(source_root)
        spec = json.loads((ROOT / "tools/host_adaptations/ftCo_SpecialS.json").read_text())
        adapted = apply_adaptation(
            (decomp / spec["source_path"]).read_bytes(), spec).decode()
        body = adapted[adapted.rindex("static void doEnter("):]
        harness = r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
typedef struct Fighter {
    float gr_vel;
    struct { float specials_ground_speed_retention; } co_attrs;
    int kind;
} Fighter;
typedef struct Fighter_GObj { Fighter* user_data; } Fighter_GObj;
static int phase, calls;
static float friction;
static float ft_GetGroundFrictionMultiplier(Fighter* fp) {
    if (phase != 0) phase = -100;
    else phase = 1;
    ++calls;
    return friction;
}
static void enter(Fighter_GObj* g) { if (phase == 1) phase = 2; }
static void (*ftData_SpecialS[])(Fighter_GObj*) = { enter };
'''
        harness += body
        harness += r'''
int main(void) {
    const float speeds[] = { 1.035538673400879F, -1.035538673400879F };
    const uint32_t expected[] = { 0xbe54140eU, 0x3e54140eU };
    for (int i = 0; i < 2; ++i) {
        Fighter f = { speeds[i], { 0.2F }, 0 };
        Fighter_GObj g = { &f };
        uint32_t bits;
        phase = calls = 0; friction = 1.5F;
        doEnter(&g);
        memcpy(&bits, &f.gr_vel, sizeof(bits));
        if (bits != expected[i] || phase != 2 || calls != 1) return 1;
        /* No surface friction preserves momentum exactly. */
        f.gr_vel = speeds[i]; phase = calls = 0; friction = 0.0F;
        doEnter(&g);
        if (f.gr_vel != speeds[i] || phase != 2 || calls != 1) return 2;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cfile = Path(temp) / "entry.c"
            binary = Path(temp) / "entry"
            cfile.write_text(harness)
            subprocess.run([
                "cc", "-std=c11", "-O2", "-fno-fast-math", "-ffp-contract=off",
                "-I", str(ROOT / "src/ssbm/native_compat"),
                "-I", str(decomp / "extern/dolphin/include"),
                str(cfile), "-o", str(binary),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
