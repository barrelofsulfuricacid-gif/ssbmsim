"""Verify repeated aerial-turn rounding and joint dirty propagation."""
import json,os,re,sys,tempfile,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
class TurnTests(unittest.TestCase):
 def test_turn_sequence(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires decomp source')
  spec=json.loads((ROOT/'tools/host_adaptations/ftCo_JumpAerial.json').read_text());text=apply_adaptation((Path(source)/spec['source_path']).read_bytes(),spec).decode()
  helper=text[text.index('static inline void pf_aerial_turn_rotation'):text.index('void ft_800CB6EC')]
  c='''#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
#include <assert.h>
typedef struct {struct {float x,y,z;} rotate;unsigned flags;} HSD_JObj;
#define HSD_ASSERT(line,x) assert(x)
#define JOBJ_MTX_INDEP_SRT 1
static int dirty;static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static void HSD_JObjSetMtxDirty(HSD_JObj* j){dirty++;}
static uint32_t bits(float x){uint32_t b;memcpy(&b,&x,4);return b;}
static float expected(float degrees,float angle){volatile double p=(double)degrees*(double)0.01745329252f;volatile double s=p-(double)angle;return -(float)s;}
'''+helper+'''
int main(void){int changed=0;
for(profile=0;profile<2;profile++)for(int n=1;n<=120;n++)for(int sign=-1;sign<=1;sign+=2)for(int flag=0;flag<2;flag++){
 HSD_JObj j={{0,sign*1.57079632679f,0},flag};float ref=j.rotate.y,old=ref;dirty=0;
 for(int frame=0;frame<n;frame++){
  float degrees=180.0f/n;ref=expected(degrees,ref);volatile float step=degrees*0.01745329252f;old-=step;
  pf_aerial_turn_rotation(&j,degrees);
  if(bits(ref)!=bits(j.rotate.y))return 1;
 }
 if(dirty!=(flag?0:n))return 2;
 changed+=bits(old)!=bits(ref);
}
return changed?0:3;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'test.c';exe=Path(tmp)/'test';path.write_text(c)
   subprocess.run(['cc','-O2','-ffp-contract=off','-fno-fast-math','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(path),'-lm','-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
