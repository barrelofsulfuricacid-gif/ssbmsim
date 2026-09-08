"""Exercise source-owned chain math and distinct inline/public rounding."""
import json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation

def function(text,name):
    start=re.search(r'^(?:static inline )?(?:float|f32|f64) '+name+r'\(',text,re.M).start()
    brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

class HookshotTests(unittest.TestCase):
    def test_no_unreviewed_local_address_spills(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:self.skipTest('requires PF_SSBM_DECOMP_SOURCE_DIR')
        source=Path(source)
        pattern=re.compile(r'\*\(\s*&\s*\w+\s*[+-]\s*\d+\s*\)')
        self.assertIsNotNone(pattern.search('*(&value + 6)'))
        specs={d['source_path']:d for p in (ROOT/'tools/host_adaptations').glob('*.json')
               if 'source_path' in (d:=json.loads(p.read_text()))}
        bad=[]
        for path in (source/'src/melee').rglob('*.c'):
            raw=path.read_bytes()
            if not pattern.search(raw.decode()):continue
            key=path.relative_to(source).as_posix()
            text=apply_adaptation(raw,specs[key]).decode() if key in specs else raw.decode()
            if pattern.search(text):bad.append(key)
        self.assertEqual(bad,[],'Review stack-layout pointer offsets before native execution')

    def test_source_norms_projections_and_spill(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source or not shutil.which('cc'):self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        source=Path(source);spec=json.loads((ROOT/'tools/host_adaptations/itlinkhookshot.json').read_text())
        raw=(source/spec['source_path']).read_bytes();text=apply_adaptation(raw,spec).decode()
        self.assertEqual(function(raw.decode(),'it_802A3C98'),function(text,'it_802A3C98'))
        self.assertNotIn('*(&y + 6)',text)
        self.assertEqual(text.count('pf_hookshot_distance_inline('),21)
        harness='''
#include "native_msl_math.h"
typedef struct {float x,y,z;} Vec3;
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
#define sqrtf PF_MSLSqrtf
#define __frsqrte PF_GekkoFrsqrte
'''
        names=['it_802A3C98','pf_hookshot_distance_inline','it_802A6A78_normalize_diff',
               'it_802A4BFC_sqrtf_offset','it_802A4BFC_normalize_diff','it_802A6A78_normalize_diff_rev']
        for name in names:harness+=function(text,name)+'\n'
        projections=[r for r in spec['replacements'] if r['reason'].startswith('Preserve target fused segment projection')]
        self.assertEqual(sum(r['count'] for r in projections),57)
        for i,r in enumerate(projections):
            operands=r['new'][len('PF_SlippiMulAddF32('):-1].split(', ')
            self.assertEqual(len(operands),3)
            for version in ('old','new'):
                expr=r[version]
                for operand,var in sorted(zip(operands,['a','b','c']),key=lambda p:-len(p[0])):expr=expr.replace(operand,var)
                harness+=f'static float {version}{i}(float a,float b,float c){{return {expr};}}\n'
        harness+='''
static unsigned state=9173;
static float sample(void){state=1664525U*state+1013904223U;return PF_MSLFloatFromBits(0x3e800000U|(state&0x7fffffU));}
static int equal(Vec3 a,Vec3 b){return memcmp(&a,&b,sizeof(a))==0;}
int main(void){
 int changed=0,projection_changed=0;
 for(profile=0;profile<2;profile++)for(int i=0;i<10000;i++){
  Vec3 a={sample(),sample(),sample()},b={0,0,0},v,expected;
  if(i==0)a=b;
  float sum=fmaf(a.z,a.z,fmaf(a.x,a.x,a.y*a.y));
  float len=PF_MSLSqrtf(sum),inv=len==0?0:(float)(1.0/(double)len);
  expected=(Vec3){a.x*inv,a.y*inv,a.z*inv};
  if(PF_MSLFloatBits(pf_hookshot_distance_inline(&a,&b,&v))!=PF_MSLFloatBits(len)||!equal(v,expected))return 1;
  if(it_802A6A78_normalize_diff(&a,&b,&v)!=(double)len||!equal(v,expected))return 2;
  if(it_802A4BFC_normalize_diff(&a,&b,&v)!=(double)len||!equal(v,expected))return 3;
  if(it_802A6A78_normalize_diff_rev(&b,&a,&v)!=(double)len||!equal(v,expected))return 4;
  float old=it_802A3C98(&a,&b,&v);changed+=PF_MSLFloatBits(old)!=PF_MSLFloatBits(len)||!equal(v,expected);
  float x=sample(),y=sample(),z=sample();
  if(i&1)x=-x;if(i&2)y=-y;if(i&4)z=-z;
'''
        for i in range(len(projections)):
            harness+=f'if(PF_MSLFloatBits(new{i}(x,y,z))!=PF_MSLFloatBits(fmaf(x,y,z)))return 5;\n'
            harness+=f'projection_changed+=PF_MSLFloatBits(old{i}(x,y,z))!=PF_MSLFloatBits(fmaf(x,y,z));\n'
        harness+='}return changed&&projection_changed?0:6;}\n'
        with tempfile.TemporaryDirectory() as tmp:
            c,binary=Path(tmp)/'hookshot.c',Path(tmp)/'hookshot';c.write_text(harness)
            subprocess.run(['cc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off','-fsanitize=undefined,address',
                '-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(source/'extern/dolphin/include'),str(c),'-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

if __name__=='__main__':unittest.main()
