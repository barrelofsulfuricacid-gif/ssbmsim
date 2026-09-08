import os
"""Guard host VECMag dispatch against the SDK C magnitude fallback."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
class MagnitudeTests(unittest.TestCase):
 def test_host_dispatch(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires pinned source')
  spec=json.loads((ROOT/'tools/host_adaptations/dolphin_vec.json').read_text());s=apply_adaptation((Path(source)/spec['source_path']).read_bytes(),spec).decode()
  def function(name):
   a=s.index('f32 '+name+'(');b=s.index('{',a);level=1;i=b+1
   while level:
    level+=(s[i]=='{')-(s[i]=='}');i+=1
   return s[a:i]
  code=r'''
#include "target_bool.h"
#include "native_numeric.h"
#include "native_ps_math.h"
#include <dolphin/mtx.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t state=123;
static float value(void){state=state*1664525+1013904223;return ((int32_t)(state>>8)-8388608)/65536.0f;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
'''+function('PSVECMag')+'\n'+function('C_VECMag')+r'''
int main(void){int old_diff=0;for(profile=0;profile<2;profile++)for(int i=0;i<20000;i++){
 Vec v={value(),value(),value()};float a=VECMag(&v),b=PSVECMag(&v);
 if(bits(a)!=bits(b))return 1;
 volatile float xx=v.x*v.x,yy=v.y*v.y,zz=v.z*v.z;
 volatile float xy=xx+yy;float old=sqrtf(xy+zz);old_diff+=bits(a)!=bits(old);
}return old_diff?0:2;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   c=Path(tmp)/'mag.c';exe=Path(tmp)/'mag';c.write_text(code)
   subprocess.run(['cc','-O2','-fno-fast-math','-ffp-contract=off','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(os.environ['PF_AURORA_SOURCE_DIR'])/'include'),str(c),'-lm','-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
