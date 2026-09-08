"""Source and exact-bit checks for both grounded shield displacement paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from apply_source_adaptation import apply_adaptation  # noqa: E402


class FtCoGuardAdaptationTests(unittest.TestCase):
    def test_both_grounded_displacements_match_captured_bits(self) -> None:
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        decomp = Path(source_root)
        spec = json.loads((ROOT / "tools/host_adaptations/ftCo_Guard.json").read_text())
        adapted = apply_adaptation((decomp / spec["source_path"]).read_bytes(), spec).decode()
        # Both source-owned floor projections must use the same arithmetic
        # boundary. Inspect actual adapted functions, not a model of them.
        harness = '''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
typedef struct { float x, y; } Vec;
typedef struct { Vec cur_pos; struct { Vec lstick[2]; } input;
    struct { struct { Vec normal; } floor; } coll_data; } Fighter;
typedef struct { float x4C0, sdi_pos_scale, x4BC; } Common;
static Common common = { 0.66F, 6.0F, 3.0F };
static Common* p_ftCommonData = &common;
'''
        functions = ["ftCo_80093240", "ftCo_800932DC"]
        for name in functions:
            body = adapted.split(f"void {name}(", 1)[1].split("\n}\n", 1)[0]
            self.assertEqual(body.count("PF_SlippiMulAddF32("), 2, name)
            self.assertNotRegex(body, r"cur_pos\.[xy]\s*\+=", name)
            block = re.search(r"float scaled_input =.*?fp->cur_pos\.y\s*=.*?;", body, re.S)
            self.assertIsNotNone(block, name)
            harness += f"static void {name}(Fighter* fp) {{\n{block.group()}\n}}\n"
        harness += "int main(void) {\n"
        # First fixture is the synchronized FoD shield-SDI capture. Second is
        # the earlier frozen-Stadium ASDI witness. Reflections and a rotated
        # floor exercise both signs and the Y projection with the same bits.
        cases = [(functions[0], 0.737500011920929, -7.248723030090332,
                  -4.328222751617432),
                 (functions[1], struct.unpack(">f", bytes.fromhex("3f366666"))[0],
                  struct.unpack(">f", bytes.fromhex("3ff5fa8e"))[0],
                  struct.unpack(">f", bytes.fromhex("40554701"))[0])]
        for name, stick, previous, expected in cases:
            for sign in [1, -1]:
                for axis in ["x", "y"]:
                    bits = struct.unpack("<I", struct.pack("<f", expected * sign))[0]
                    normal = ("f.coll_data.floor.normal.y=0x1.fffffep-1F;"
                              if axis == "x" else
                              "f.coll_data.floor.normal.x=-0x1.fffffep-1F;")
                    harness += (f"{{ Fighter f={{0}}; f.cur_pos.{axis}={previous*sign!r}F;"
                                f"f.input.lstick[0].x={stick*sign!r}F; {normal}"
                                f"{name}(&f); uint32_t bits; memcpy(&bits,&f.cur_pos.{axis},4);"
                                f"if(bits!=0x{bits:08x}U)return 1; }}\n")
        harness += "return 0; }\n"
        with tempfile.TemporaryDirectory() as temp:
            cfile, binary = Path(temp) / "guard.c", Path(temp) / "guard"
            cfile.write_text(harness)
            subprocess.run(["cc", "-std=c11", "-O2", "-fno-fast-math", "-ffp-contract=off",
                            "-I", str(ROOT / "src/ssbm/native_compat"),
                            "-I", str(decomp / "extern/dolphin/include"), str(cfile),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True)

    def test_dol_instruction_boundary_is_pinned(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_Guard.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            adaptation["evidence"]["dol_sha1"],
            "08e0bf20134dfcb260699671004527b2d6bb1a45",
        )
        self.assertIn("0x80093324", adaptation["evidence"]["instructions"])
        self.assertIn("0x80093334", adaptation["evidence"]["instructions"])
        self.assertIn("0x80093348", adaptation["evidence"]["instructions"])

    def test_pinned_source_preserves_two_roundings_then_fuses(self) -> None:
        path = ROOT / "tools/host_adaptations/ftCo_Guard.json"
        adaptation = json.loads(path.read_text(encoding="utf-8"))
        source_root = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not source_root:
            self.skipTest("requires PF_SSBM_DECOMP_SOURCE_DIR")
        source = Path(source_root) / adaptation["source_path"]
        adapted = apply_adaptation(source.read_bytes(), adaptation).decode("utf-8")

        self.assertIn(
            "float scaled_input =\n"
            "                fp->input.lstick[0].x * p_ftCommonData->x4BC;",
            adapted,
        )
        self.assertIn(
            "PF_SlippiMulAddF32(fp->coll_data.floor.normal.y, scl, fp->cur_pos.x);",
            adapted,
        )
        self.assertIn(
            "PF_SlippiMulAddF32(-fp->coll_data.floor.normal.x, scl, fp->cur_pos.y);",
            adapted,
        )
        self.assertNotIn(
            "float scl = p_ftCommonData->x4C0 *\n"
            "                        (fp->input.lstick[0].x * p_ftCommonData->x4BC);",
            adapted,
        )


if __name__ == "__main__":
    unittest.main()
