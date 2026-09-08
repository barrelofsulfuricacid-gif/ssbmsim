"""Compiled collision interpolation and wall-projection boundary regressions."""
import json,os,re,subprocess,tempfile,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
class CollisionTests(unittest.TestCase):
 def test_projection_and_interpolation(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires pinned source')
  spec=json.loads((ROOT/'tools/host_adaptations/mpcoll.json').read_text());text=apply_adaptation((Path(source)/spec['source_path']).read_bytes(),spec).decode()
  fn=re.search(r'static inline void Vec2_Interpolate\([^}]+}',text).group(0)
  rows=[r for r in spec['replacements'] if re.fullmatch(r'(f27|f26|bot_y_to_x|top_y_to_x) \* \(pos.y - (bot|top|f28|f30)\) \+ coll->ecb\.(bottom|top).x',r['old'])]
  self.assertEqual(sum(r['count'] for r in rows),16)
  c='''#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef struct{float x,y;}Vec2;
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
static float ref(float a,float b,float c){volatile double p=(double)a*b;volatile double s=p+c;return (float)s;}
'''+fn+'\n'
  for i,r in enumerate(rows):
   m=re.fullmatch(r'PF_SlippiMulAddF32\(([^,]+), pos.y - ([^,]+), ([^)]+)\)',r['new']);self.assertIsNotNone(m)
   expr=r['new'].replace(m[1],'slope').replace('pos.y - '+m[2],'y - edge').replace(m[3],'offset')
   c+=f'float wall{i}(float slope,float y,float edge,float offset){{return {expr};}}\n'
  c+='''int main(void){int changed=0;unsigned state=6199;
for(profile=0;profile<2;profile++)for(int i=0;i<20000;i++){
state=1664525*state+1013904223;float x=((int)(state%20001)-10000)/131.0f;
state=1664525*state+1013904223;float y=((int)(state%20001)-10000)/173.0f;
float t=(i%101)/100.0f;Vec2 d={x,y},s={y,x};Vec2 expected={ref(t,s.x-d.x,d.x),ref(t,s.y-d.y,d.y)};
Vec2_Interpolate(t,&d,&s);if(memcmp(&d,&expected,sizeof(d)))return 1;
float slope=x,edge=y,offset=-x;float point=i%3==0?edge:nextafterf(edge,i%3==1?INFINITY:-INFINITY);
volatile float delta=point-edge;float result=ref(slope,delta,offset);
'''
  for i in range(len(rows)):c+=f'if(bits(wall{i}(slope,point,edge,offset))!=bits(result))return 2;\n'
  c+='''volatile float product=t*(s.x-x);changed+=bits(product+x)!=bits(expected.x);
}return changed?0:3;}'''
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'test.c';exe=Path(tmp)/'test';path.write_text(c)
   subprocess.run(['cc','-O2','-ffp-contract=off','-fno-fast-math','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(path),'-lm','-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
