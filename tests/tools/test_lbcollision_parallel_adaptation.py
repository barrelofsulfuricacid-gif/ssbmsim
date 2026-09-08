"""Regression for degenerate capsule classification using actual adapted source."""
import json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation

class CapsuleParallelTests(unittest.TestCase):
    def test_parallel_overlap_and_separated_capsules(self):
        decomp=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec=json.loads((ROOT/'tools/host_adaptations/lbcollision.json').read_text())
        original=(Path(decomp)/spec['source_path']).read_bytes()
        adapted=apply_adaptation(original,spec).decode()
        start=adapted.index('float lbColl_80005EBC(')
        end=adapted.index('/// @brief Tests a hit capsule segment')
        body=adapted[start:end]
        old=original.decode();old=old[old.index('float lbColl_80005EBC('):old.index('/// @brief Tests a hit capsule segment')]
        for name in ['lbColl_80005EBC','lbColl_80005FC0','lbColl_80006094','lbColl_800067F8','lbColl_GetY','lbColl_DifferenceY','end']:
            old=re.sub(r'\b'+name+r'\b','original_'+name,old)
        harness='''#include "native_numeric.h"
#include <assert.h>
#include <stdbool.h>
typedef struct {float x,y,z;} Vec3;
typedef struct {float x,y;} Vec2;
#define PAD_STACK(n)
static bool approximatelyZero(float x){return x<0.00001f && x>-0.00001f;}
'''+body+old+r'''
int main(void) {
 Vec3 a={11.748685836791992F,14.382461547851562F,-3.3738726301635324e-7F};
 Vec3 b={7.090226650238037F,a.y,a.z};
 Vec3 c={6.25738525390625F,13.752842903137207F,1.5651986586817657e-6F};
 Vec3 d={11.25738525390625F,c.y,c.z},e,f;
 /* Captured overlapping detector/laser paths. The previous coefficients
    choose the wrong branch and return a miss despite clear overlap. */
 assert(!original_lbColl_80006094(&a,&b,&c,&d,&e,&f,3.999743938446045F,1.1718000173568726F));
 for(int sx=-1;sx<=1;sx+=2) for(int sy=-1;sy<=1;sy+=2)
 for(int sz=-1;sz<=1;sz+=2) {
  Vec3 aa={sx*a.x,sy*a.y,sz*a.z},bb={sx*b.x,sy*b.y,sz*b.z};
  Vec3 cc={sx*c.x,sy*c.y,sz*c.z},dd={sx*d.x,sy*d.y,sz*d.z};
  assert(lbColl_80006094(&aa,&bb,&cc,&dd,&e,&f,3.999743938446045F,1.1718000173568726F));
  assert(lbColl_800067F8(&aa,&bb,&cc,&dd,&e,&f,3.999743938446045F,1.1718000173568726F));
  cc.y+=sy*20;dd.y+=sy*20;
  assert(!lbColl_80006094(&aa,&bb,&cc,&dd,&e,&f,3.999743938446045F,1.1718000173568726F));
  assert(!lbColl_800067F8(&aa,&bb,&cc,&dd,&e,&f,3.999743938446045F,1.1718000173568726F));
 }
 /* Zero-length and crossing segments exercise the other solver branches. */
 a=(Vec3){0,0,0};b=a;c=(Vec3){1,0,0};d=c;
 assert(lbColl_80006094(&a,&b,&c,&d,&e,&f,1,1));
 c.x=d.x=4;assert(!lbColl_80006094(&a,&b,&c,&d,&e,&f,1,1));
 a=(Vec3){-4,0,0};b=(Vec3){4,0,0};c=(Vec3){0,-4,0};d=(Vec3){0,4,0};
 assert(lbColl_80006094(&a,&b,&c,&d,&e,&f,1,1));
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='ssbm-capsule-') as folder:
            folder=Path(folder);source=folder/'test.c';exe=folder/'test'
            source.write_text(harness)
            result=subprocess.run(['cc','-std=c11','-O2','-ffp-contract=off','-fno-fast-math','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(decomp)/'extern/dolphin/include'),str(source),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__':unittest.main()
