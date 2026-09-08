"""Compile the adapted source query and production Slippi hook together."""

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


def function(text, signature):
    return signature + text.split(signature, 1)[1].split("\n}\n", 1)[0] + "\n}\n"


class WhispySourceTests(unittest.TestCase):
    def test_death_votes_filters_rng_and_bone_side_effects(self):
        decomp = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not decomp or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        spec = json.loads((ROOT / "tools/host_adaptations/ftlib.json").read_text())
        source = (Path(decomp) / spec["source_path"]).read_bytes()
        adapted = apply_adaptation(source, spec).decode()
        native = (ROOT / "src/ssbm/native_compat/native_slippi.c").read_text()
        harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
typedef uint8_t u8;
typedef int32_t s32;
typedef struct {float x,y,z;} Vec3;
typedef struct {int motion_id, x221F_b3, team; float camera_x;} Fighter;
typedef struct HSD_GObj {struct HSD_GObj* next; Fighter* user_data;} HSD_GObj;
static struct {HSD_GObj* fighters;} entities;
#define HSD_GObj_Entities (&entities)
static bool slippi_online_enabled;
static int teams, bones, rng_calls, random_value, self_checks;
static int ftLib_80086FD4(HSD_GObj* a,HSD_GObj* b) {++self_checks; return a==b;}
static int gm_8016B168(void) {return teams;}
static void ftLib_800866DC(HSD_GObj* g,Vec3* v) {++bones; v->x=g->user_data->camera_x;}
static int HSD_Randi(int n) {assert(n==2); ++rng_calls; return random_value;}
'''
        harness += function(native, "uint8_t pf_ssbm_native_slippi_whispy_excludes_fighter(")
        # Preserve upstream sign semantics, including a fighter exactly at center.
        sign_start = adapted.rfind("\n", 0, adapted.index("sgn(float"))
        sign_signature = adapted[sign_start + 1:adapted.index("sgn(float") + len("sgn(")]
        harness += function(adapted, sign_signature)
        harness += function(adapted, "float ftLib_800864A8(")
        harness += r'''
static void expect(Vec3* center,HSD_GObj* excluded,float result,int b,int r,int s) {
 bones=rng_calls=self_checks=0;
 assert(ftLib_800864A8(center,excluded)==result);
 assert(bones==b); assert(rng_calls==r); assert(self_checks==s);
}
int main(void) {
 Fighter a={12,0,0,-30},b={12,0,1,23};
 HSD_GObj second={NULL,&b},first={&second,&a}; Vec3 center={0};
 entities.fighters=&first;
 /* Every death state on either side, with both tie outcomes. Offline retains
    the original vote; online still queries both bones but consumes no RNG. */
 for(int online=0;online<2;++online) for(int death=0;death<=11;++death)
 for(int side=-1;side<=1;side+=2) for(int random=0;random<2;++random) {
  slippi_online_enabled=online; random_value=random;
  a.camera_x=side*30; b.camera_x=-side*23; a.motion_id=12;b.motion_id=death;
  expect(&center,NULL,online?side:(random?1:-1),2,online?0:1,2);
 }
 slippi_online_enabled=true; a.camera_x=-30;b.camera_x=23;
 /* Both dead remains a tie, and first live action 12 is included. */
 for(int random=0;random<2;++random) {
  random_value=random; a.motion_id=0;b.motion_id=11;
  expect(&center,NULL,random?1:-1,2,1,2);
  a.motion_id=b.motion_id=12;expect(&center,NULL,random?1:-1,2,1,2);
 }
 a.camera_x=0;b.motion_id=11;expect(&center,NULL,1,2,0,2);
 /* Original hidden, self, and same-team filters precede the bone query. */
 a.camera_x=-30;b.motion_id=12;b.x221F_b3=1;
 expect(&center,NULL,-1,1,0,2);b.x221F_b3=0;
 expect(&center,&second,-1,1,0,2);
 teams=1;a.team=b.team=1;expect(&center,&second,1,0,1,2);
 teams=0;a.motion_id=-1;b.motion_id=12;expect(&center,NULL,1,2,0,2);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c = Path(temp) / "whispy.c"
            binary = Path(temp) / "whispy"
            c.write_text(harness)
            compiled = subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                                       str(c), "-o", str(binary)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
