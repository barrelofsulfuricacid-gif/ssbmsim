"""Exercise source throw-joint smoothing, and dirty gating."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
class ThrowSmoothingTests(unittest.TestCase):
 def test_source_smoothing(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires pinned source')
  spec=json.loads((ROOT/'tools/host_adaptations/ftcommon.json').read_text());raw=(Path(source)/spec['source_path']).read_bytes();adapted=apply_adaptation(raw,spec).decode()
  def body(s):
   a=s.index('void ftCommon_8007E3EC(');return s[a:s.index('void ftCommon_8007E5AC(',a)]
  code=r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef struct {float x,y,z;} Vec3;
typedef struct {Vec3 translate;int dirty;} HSD_JObj;
typedef struct {struct {HSD_JObj *joint;} parts[5];Vec3 x1A7C;float x1A6C;} Fighter;
typedef struct {Fighter *user_data;} HSD_GObj;
static int ftParts_GetBoneIndex(Fighter *f,int i){(void)f;return i;}
static int HSD_JObjMtxIsDirty(HSD_JObj *j){return j->dirty;}
static void HSD_JObjGetTranslation(HSD_JObj *j,Vec3 *v){*v=j->translate;}
static void HSD_JObjSetTranslate(HSD_JObj *j,Vec3 *v){j->translate=*v;}
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t state=98765;
static float val(void){state=state*1664525u+1013904223u;return ((int32_t)(state>>8)-8388608)/65536.0f;}
static uint32_t bits(float f){uint32_t u;memcpy(&u,&f,4);return u;}
static float ref(float a,float b,float w){volatile float delta=b-a;volatile double prod=(double)delta*w;volatile double sum=prod+a;return (float)sum;}
'''+body(adapted)+body(raw.decode()).replace('ftCommon_8007E3EC','old_smoothing')+r'''
int main(void){int changed=0;
for(profile=0;profile<2;profile++)for(int k=0;k<20000;k++){
 HSD_JObj j={{val(),val(),val()},k%4!=0};Fighter fp={0};HSD_GObj obj={&fp};fp.parts[4].joint=&j;
 fp.x1A7C=(Vec3){val(),val(),val()};fp.x1A6C=k%5==0?0:k%5==1?1:k%5==2?nextafterf(1,0):val()/128;
 Fighter saved=fp;HSD_JObj original=j;
 Vec3 e=fp.x1A7C;if(j.dirty)e=(Vec3){ref(e.x,j.translate.x,fp.x1A6C),ref(e.y,j.translate.y,fp.x1A6C),ref(e.z,j.translate.z,fp.x1A6C)};
 ftCommon_8007E3EC(&obj);
 if(memcmp(&e,&fp.x1A7C,sizeof(e)))return 1;
 if(memcmp(&j.translate,j.dirty?&e:&original.translate,sizeof(e)))return 2;
 fp=saved;j=original;old_smoothing(&obj);changed+=memcmp(&fp.x1A7C,&e,sizeof(e))!=0;
}
return changed?0:3;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   c=Path(tmp)/'smooth.c';exe=Path(tmp)/'smooth';c.write_text(code)
   subprocess.run(['cc','-O2','-fno-fast-math','-ffp-contract=off','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(c),'-lm','-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
