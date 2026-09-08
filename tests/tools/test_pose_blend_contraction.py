"""Compile source-owned pose blend arithmetic for both variants and alias paths."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
class PoseBlendTests(unittest.TestCase):
 def test_both_blend_variants(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires pinned source')
  spec=json.loads((ROOT/'tools/host_adaptations/lb_00B0.json').read_text())
  raw=(Path(source)/spec['source_path']).read_bytes();adapted=apply_adaptation(raw,spec).decode()
  def extract(text,fn,name):
   start=text.index('    arg2->translate.x =',text.index('void '+fn+'('))
   end=text.index('    '+('is_quat_1 =' if fn=='lb_8000C490' else 'temp_r31 ='),start)
   first='HSD_JObj' if fn=='lb_8000C490' else 'HSD_Joint'
   return 'static void '+name+'('+first+' *'+('jobj1' if fn=='lb_8000C490' else 'arg0')+', HSD_JObj *'+('jobj2' if fn=='lb_8000C490' else 'arg1')+', HSD_JObj *arg2,float arg8,float arg9){\n'+text[start:end]+'}\n'
  code=r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef struct {float x,y,z;} Vec3;
typedef struct {Vec3 translate,scale;} HSD_JObj;
typedef struct {Vec3 position,scale;} HSD_Joint;
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t state=1234567;
static float value(void){state=state*1664525u+1013904223u;return (float)((int32_t)(state>>8)-8388608)/65536.0f;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
static float ref(float a,float b,float c,float d){volatile float second=c*d;volatile double product=(double)a*b;volatile double sum=product+(double)second;return (float)sum;}
'''
  for fn,name in [('lb_8000C490','objects'),('lb_8000C868','descriptor')]:
   code+=extract(adapted,fn,name)+extract(raw.decode(),fn,'old_'+name)
  code+=r'''
int main(void){int changed=0;
for(profile=0;profile<2;profile++)for(int k=0;k<20000;k++){
 HSD_JObj a,b;float av[6],bv[6],ev[6];
 for(int i=0;i<6;i++){av[i]=value();bv[i]=value();}
 memcpy(&a,av,sizeof(a));memcpy(&b,bv,sizeof(b));
 float t=k%5==0?0:k%5==1?1:k%5==2?nextafterf(1,0):value()/128;
 float w=1-t;
 for(int i=0;i<6;i++)ev[i]=ref(av[i],w,bv[i],t);
 for(int alias=0;alias<3;alias++){
  HSD_JObj x=a,y=b,out={0};HSD_JObj *dst=alias==1?&x:alias==2?&y:&out;
  objects(&x,&y,dst,w,t);float actual[6];memcpy(actual,dst,sizeof(actual));
  for(int i=0;i<6;i++)if(bits(actual[i])!=bits(ev[i]))return 1;
 }
 HSD_Joint desc;memcpy(&desc,&a,sizeof(desc));
 for(int alias=0;alias<2;alias++){
  HSD_JObj y=b,out={0};HSD_JObj *dst=alias?&y:&out;
  descriptor(&desc,&y,dst,w,t);float actual[6];memcpy(actual,dst,sizeof(actual));
  for(int i=0;i<6;i++)if(bits(actual[i])!=bits(ev[i]))return 2;
 }
 HSD_JObj old;old_descriptor(&desc,&b,&old,w,t);float actual[6];memcpy(actual,&old,sizeof(actual));
 for(int i=0;i<6;i++)changed+=bits(actual[i])!=bits(ev[i]);
}
return changed?0:3;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   c=Path(tmp)/'blend.c';exe=Path(tmp)/'blend';c.write_text(code)
   subprocess.run(['cc','-O2','-fno-fast-math','-ffp-contract=off','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(c),'-lm','-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
