"""Exercise actual source throw-DI commands at the Slippi determinism boundary."""
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


class NanaThrowDiTests(unittest.TestCase):
    def test_near_zero_and_nonzero_throw_di_command_sequences(self):
        decomp = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not decomp or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        spec = json.loads((ROOT / "tools/host_adaptations/ftCo_0A01.json").read_text())
        adapted = apply_adaptation((Path(decomp) / spec["source_path"]).read_bytes(), spec).decode()
        def function(signature):
            return signature + adapted.split(signature, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        harness = r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <math.h>
typedef int8_t s8;
struct CpuFighter {int x18,x1C,x7C,level,xFA_b1;};
typedef struct {struct CpuFighter cpu; bool x221A_b3; struct {float x,y;} x8c_kb_vel;} Fighter;
enum {CpuCmd_ReleaseR,CpuCmd_Done,CpuCmd_SetLstickX,CpuCmd_SetLstickY,CpuCmd_PressR,CpuCmd_WaitFor};
static int commands[8],values[8],count,neutral;
static void ftCo_800B46B8(Fighter* f,int c,int v) {(void)f;commands[count]=c;values[count++]=v;}
static void ftCo_800B463C(Fighter* f,int c) {ftCo_800B46B8(f,c,0);}
static void ftCo_CpuSetNeutralStick(Fighter* f) {(void)f;++neutral;}
'''
        harness += function("static inline bool ftCo_IsNearlyZero(")
        harness += function("void ftCo_800AC5A0(Fighter* fp)\n")
        harness += r'''
int main(void) {
 Fighter f={.cpu={.x7C=119,.level=9},.x221A_b3=true};
 const float vectors[][2]={{0,0},{1e-6F,0},{0,-1e-6F},{1e-6F,-1e-6F},
                            {1,0},{-1,0},{0,1},{0,-1}};
 const int expected[][2]={{0,0},{0,0},{0,0},{0,0},{0,127},{0,127},{127,0},{-127,0}};
 for(unsigned i=0;i<sizeof(vectors)/sizeof(vectors[0]);++i) for(int press=0;press<2;++press) {
  f.x8c_kb_vel.x=vectors[i][0];f.x8c_kb_vel.y=vectors[i][1];f.cpu.xFA_b1=press;
  count=neutral=0;ftCo_800AC5A0(&f);
  assert(count==4+press && neutral==0);
  assert(commands[0]==CpuCmd_SetLstickX && values[0]==expected[i][0]);
  assert(commands[1]==CpuCmd_SetLstickY && values[1]==expected[i][1]);
  if(press)assert(commands[2]==CpuCmd_PressR);
  assert(commands[2+press]==CpuCmd_WaitFor && values[2+press]==1);
  assert(commands[3+press]==CpuCmd_Done);
 }
 count=neutral=0;f.cpu.x7C=0;f.cpu.xFA_b1=0;ftCo_800AC5A0(&f);
 assert(neutral==1 && count==2 && commands[0]==CpuCmd_WaitFor && commands[1]==CpuCmd_Done);
 count=neutral=0;f.x221A_b3=false;f.cpu.x1C=42;ftCo_800AC5A0(&f);
 assert(f.cpu.x18==42 && count==2 && neutral==0);
 assert(commands[0]==CpuCmd_ReleaseR && commands[1]==CpuCmd_Done);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c, binary = Path(temp) / "throw.c", Path(temp) / "throw"
            c.write_text(harness)
            result = subprocess.run(["cc", "-std=c11", "-O2", "-Wall",
                                     "-Werror=uninitialized", "-Werror=maybe-uninitialized",
                                     "-ffp-contract=off", str(c), "-lm", "-o", str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
