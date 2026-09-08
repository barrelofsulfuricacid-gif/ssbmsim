"""Exercise every imported Samus grapple projection against staged target rounding."""
import json,os,re,subprocess,tempfile,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation
from test_hookshot_contraction import function
class GrappleTests(unittest.TestCase):
 def test_all_projections(self):
  source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
  if not source:self.skipTest('requires pinned decomp checkout')
  spec=json.loads((ROOT/'tools/host_adaptations/itsamusgrapple.json').read_text())
  raw=(Path(source)/spec['source_path']).read_bytes();text=apply_adaptation(raw,spec).decode()
  self.assertEqual(raw.decode().count('HSD_Randf()'),text.count('HSD_Randf()'))
  self.assertEqual(raw.decode().count('it_802A3C98('),text.count('it_802A3C98('))
  rows=[r for r in spec['replacements'] if r['reason'].startswith('Retail fused chain projection')]
  self.assertEqual(sum(r['count'] for r in rows),69)
  c='''#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
static float reference(float a,float b,float c){volatile double p=(double)a*b;volatile double s=p+(double)c;return (float)s;}
static float random_values[2];static int random_calls;
static float HSD_Randf(void){return random_values[random_calls++];}
'''
  for name in ('samus_grapple_calc_grav','it_802B9328_grav'):
   c+=function(text,name)+'\n'
  for i,r in enumerate(rows):
   expr=r['new'].split(' = ',1)[1].rstrip(';');args=expr[len('PF_SlippiMulAddF32('):-1].split(', ')
   for old,new in sorted(zip(args,['a','b','c']),key=lambda x:-len(x[0])):expr=expr.replace(old,new)
   c+=f'static float projection{i}(float a,float b,float c){{return {expr};}}\n'
  c+='''int main(void){unsigned state=4857;int changed=0;
for(profile=0;profile<2;profile++)for(int i=0;i<20000;i++){
state=1664525U*state+1013904223U;float a=(int)(state%200001)-100000;
state=1664525U*state+1013904223U;float b=((int)(state%200001)-100000)/317.0f;
state=1664525U*state+1013904223U;float c=((int)(state%200001)-100000)/173.0f;
if(i%7==0)c=-(a*b);if(i==0)a=b=c=0.0f;
volatile float product=a*b;changed+=bits(product+c)!=bits(reference(a,b,c));
random_values[0]=0.95f;random_values[1]=(i%997)/997.0f;random_calls=0;
float grav=samus_grapple_calc_grav(a);
float expected=a<0.0?-reference(0.6f,random_values[1],-a):reference(0.6f,random_values[1],a);
if(random_calls!=2||bits(grav)!=bits(expected))return 3;
random_calls=0;grav=it_802B9328_grav(a);
expected=a<0.0?-reference(1.0f,random_values[1],-a):reference(1.0f,random_values[1],a);
if(random_calls!=2||bits(grav)!=bits(expected))return 4;
random_values[0]=0.5f;random_calls=0;
if(samus_grapple_calc_grav(a)!=0.0f||random_calls!=1)return 5;
random_calls=0;if(it_802B9328_grav(a)!=0.0f||random_calls!=1)return 6;
'''
  for i in range(len(rows)):c+=f'if(bits(projection{i}(a,b,c))!=bits(reference(a,b,c)))return 1;\n'
  c+='}return changed?0:2;}\n'
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'test.c';binary=Path(tmp)/'test';path.write_text(c)
   subprocess.run(['cc','-O2','-ffp-contract=off','-fno-fast-math','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(path),'-lm','-o',str(binary)],check=True)
   subprocess.run([str(binary)],check=True)
if __name__=='__main__':unittest.main()
