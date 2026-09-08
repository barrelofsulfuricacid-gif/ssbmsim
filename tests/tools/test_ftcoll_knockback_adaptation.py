"""Cross-check actual source knockback entry points and a captured oracle value."""
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


def function(source, signature):
    return signature + source.split(signature, 1)[1].split("\n}\n", 1)[0] + "\n}\n"


class KnockbackSourceTests(unittest.TestCase):
    def test_expanded_and_shared_formulas_match_across_input_classes(self):
        decomp = os.environ.get("PF_SSBM_DECOMP_SOURCE_DIR")
        if not decomp or not shutil.which("cc"):
            self.skipTest("requires cc and PF_SSBM_DECOMP_SOURCE_DIR")
        spec = json.loads((ROOT / "tools/host_adaptations/ftcoll.json").read_text())
        source = (Path(decomp) / spec["source_path"]).read_bytes()
        adapted = apply_adaptation(source, spec).decode()
        capture = function(adapted, "float ftColl_80079C70(")
        self.assertEqual(capture.count("PF_SlippiMulAddF32("), 6)
        harness = r'''
#include "native_numeric.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define PAD_STACK(n)
typedef struct {float weight;} Attributes;
typedef struct {float x1830_percent,x1838_percentTemp;} Damage;
typedef struct {Attributes co_attrs; Damage dmg; int player_id; bool x2225_b7,x2224_b2;} Fighter;
typedef struct {u32 x24,x28,x2C;} HitCapsule;
typedef struct {float xF4,xF8,x108,x110,x114,x118,x11C,x120; int x6D4,x6D8[1];} ftCommonData;
static ftCommonData common={0.01F,2,2500,0.1F,0.05F,10,1.4F,18,150,{300}};
static ftCommonData* p_ftCommonData=&common;
static float defense=1,attack=1,stage=1;
static float Player_GetDefenseRatio(int id) {(void)id;return defense;}
static float Player_GetAttackRatio(int id) {(void)id;return attack;}
static float gm_8016B248(void) {return stage;}
static uint32_t bits(float x) {uint32_t b;memcpy(&b,&x,4);return b;}
'''
        macro = "#define KNOCKBACK(" + adapted.split("#define KNOCKBACK(", 1)[1].split("\n\n", 1)[0]
        harness += macro + "\n"
        harness += function(adapted, "static inline s32 ftColl_GetDamageCount(")
        for name in ["ftColl_80079AB0", "ftColl_80079C70", "ftColl_80079EA8"]:
            harness += function(adapted, "float " + name + "(")
        harness += function(source.decode(), "float ftColl_80079C70(").replace(
            "ftColl_80079C70", "unadapted_capture")
        harness += r'''
int main(void) {
 Fighter victim={.co_attrs={88},.dmg={29.739999771118164F,0}},attacker={0};
 HitCapsule hit={100,0,40};
 /* Synchronized oracle: 0f4ba39074ee, frame 4199, port-0 Nana. The
    damage modifier subtracts 5 after this function returns. */
 assert(bits(ftColl_80079C70(&victim,&attacker,&hit,3))==bits(68.797874450683594F));
 assert(bits(unadapted_capture(&victim,&attacker,&hit,3))==bits(68.79786682128906F));
 const float weights[]={60,80,88,90,100,110,120};
 const float percents[]={0,29.739999771118164F,32.5F,100,999};
 const unsigned fixed[]={0,1,20},growth[]={0,40,100,200},base[]={0,40,100};
 const unsigned counts[]={0,3,12};
 for(unsigned w=0;w<7;++w) for(unsigned p=0;p<5;++p)
 for(unsigned k=0;k<3;++k) for(unsigned g=0;g<4;++g)
 for(unsigned b=0;b<3;++b) for(unsigned n=0;n<3;++n)
 for(int mode=0;mode<3;++mode) {
  victim.co_attrs.weight=weights[w];victim.dmg.x1830_percent=percents[p];
  victim.dmg.x1838_percentTemp=p%2?0.75F:0;
  victim.x2225_b7=mode!=0;victim.x2224_b2=mode==2;
  hit.x28=fixed[k];hit.x24=growth[g];hit.x2C=base[b];
  defense=attack=stage=1;
  float a=ftColl_80079AB0(&victim,&hit,counts[n],stage,attack,defense,weights[w]);
  assert(bits(a)==bits(ftColl_80079C70(&victim,&attacker,&hit,counts[n])));
  assert(bits(a)==bits(ftColl_80079EA8(&victim,&hit,counts[n])));
  defense=0.5F;attack=2;stage=1.25F;
  assert(bits(ftColl_80079AB0(&victim,&hit,counts[n],stage,attack,defense,weights[w]))==
         bits(ftColl_80079C70(&victim,&attacker,&hit,counts[n])));
 }
 /* Exercise the final cap independently of the ordinary gameplay values. */
 common.x108=1;
 assert(ftColl_80079C70(&victim,&attacker,&hit,12)==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c, binary = Path(temp) / "knockback.c", Path(temp) / "knockback"
            c.write_text(harness)
            result = subprocess.run(["cc", "-std=c11", "-O2", "-fno-fast-math",
                                     "-ffp-contract=off", "-I", str(ROOT / "src/ssbm/native_compat"),
                                     "-I", str(Path(decomp) / "extern/dolphin/include"),
                                     str(c), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
