"""Compile the source-owned endpoint solvers against staged arithmetic references."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


class ProjectionTests(unittest.TestCase):
    def test_clamped_endpoint_projections(self):
        source = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:
            self.skipTest('requires pinned decomp source')
        spec = json.loads((ROOT / 'tools/host_adaptations/lbcollision.json').read_text())
        original = (Path(source) / spec['source_path']).read_bytes()
        text = apply_adaptation(original, spec).decode()
        def helpers(s):
            return s[s.index('float lbColl_80005EBC('):s.index('static inline bool end(')]
        old = helpers(original.decode()).replace('lbColl_80005EBC', 'old3').replace('lbColl_80005FC0', 'old2')
        harness = r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef struct { float x,y,z; } Vec3;
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void) { return profile; }
static uint32_t bits(float v) { uint32_t u; memcpy(&u,&v,4); return u; }
static float ref(float a,float b,float c) {
    volatile double product=(double)a*b;
    volatile double sum=product+c;
    return (float)sum;
}
static float expected(Vec3 a,Vec3 b,Vec3 c,int dimensions,float *param) {
    float dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z;
    float ox=a.x-c.x,oy=a.y-c.y,oz=a.z-c.z;
    float square=ref(dx,dx,dy*dy),dot=ref(dx,ox,dy*oy);
    if(dimensions==3) { square=ref(dz,dz,square); dot=ref(dz,oz,dot); }
    float t=-dot/square;
    if(t>1.0f)t=1.0f; else if(t<0.0f)t=0.0f;
    float x=ref(dx,t,a.x)-c.x,y=ref(dy,t,a.y)-c.y;
    float result=ref(x,x,y*y);
    if(dimensions==3) { float z=ref(dz,t,a.z)-c.z; result=ref(z,z,result); }
    *param=t; return result;
}
''' + helpers(text) + old + r'''
int main(void) {
    unsigned rng=37; int changed=0;
    for(profile=0;profile<2;profile++) for(int i=0;i<20000;i++) {
        float v[9];
        for(int j=0;j<9;j++) {
            rng=rng*1664525u+1013904223u;
            v[j]=((int)(rng%20001)-10000)/137.0f;
        }
        Vec3 a={v[0],v[1],v[2]},b={v[3],v[4],v[5]},c={v[6],v[7],v[8]};
        /* Exact endpoints and their immediate floating-point neighbours. */
        if(i%5==0)c=a;
        if(i%5==1)c=b;
        if(i%5==2) { c=a; c.x=nextafterf(a.x,-INFINITY); }
        if(i%5==3) { c=b; c.y=nextafterf(b.y,INFINITY); }
        float t,w,old_t;
        float e=expected(a,b,c,3,&t),n=lbColl_80005EBC(&a,&b,&c,&w);
        if(bits(e)!=bits(n)||bits(t)!=bits(w))return 1;
        changed+=bits(old3(&a,&b,&c,&old_t))!=bits(e);
        e=expected(a,b,c,2,&t);n=lbColl_80005FC0(&a,&b,&c,&w);
        if(bits(e)!=bits(n)||bits(t)!=bits(w))return 2;
    }
    return changed?0:3;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / 'test.c'
            exe = Path(tmp) / 'test'
            c.write_text(harness)
            subprocess.run(['cc', '-O2', '-ffp-contract=off', '-fno-fast-math',
                            '-fsanitize=address,undefined',
                            '-I', str(ROOT / 'src/ssbm/native_compat'),
                            '-I', str(Path(source) / 'extern/dolphin/include'),
                            str(c), '-lm', '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
