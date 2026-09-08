"""Exact inverse, inverse-transpose, and inverse-concat arithmetic boundaries."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


class InverseTests(unittest.TestCase):
    def test_inverse_family_aliases_and_singular_boundary(self):
        source = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:
            self.skipTest('requires pinned decomp source')
        spec = json.loads((ROOT / 'tools/host_adaptations/hsd_mtx.json').read_text())
        original = (Path(source) / spec['source_path']).read_bytes()
        adapted = apply_adaptation(original, spec).decode()
        def functions(text):
            return text[text.index('static inline f32 HSD_CalcDeterminantMatrix3x4'):text.index('static inline f32 calcVal')]
        old = re.sub(r'\bHSD_(\w+)', r'old_\1', functions(original.decode()))
        harness = r'''
#include "native_numeric.h"
#include <math.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef float Mtx[3][4];
#define EPSILON 0.0000000001f
#define fabsf_bitwise fabsf
#define MTXCopy(a,b) memcpy((b),(a),sizeof(Mtx))
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void) { return profile; }
static void MTXIdentity(Mtx m) { memset(m,0,sizeof(Mtx)); for(int i=0;i<3;i++)m[i][i]=1; }
static float ref(float a,float b,float c) {
    volatile double product=(double)a*b;
    volatile double sum=product+c;
    return (float)sum;
}
static float determinant(Mtx m) {
    float d=m[2][0]*(m[0][1]*m[1][2]);
    d=ref(m[2][2],m[0][0]*m[1][1],d);
    d=ref(m[2][1],m[0][2]*m[1][0],d);
    d=-ref(m[0][2],m[2][0]*m[1][1],-d);
    d=-ref(m[2][2],m[1][0]*m[0][1],-d);
    return -ref(m[1][2],m[0][0]*m[2][1],-d);
}
static void reference_inverse(Mtx src,Mtx out,int alias) {
    float d=determinant(src);
    if(fabsf(d)<EPSILON) { MTXIdentity(out); return; }
    Mtx original;MTXCopy(src,original);d=1.0f/d;
    /* Cofactors are selected algebraically, independently of source temporaries. */
    for(int r=0;r<3;r++)for(int c=0;c<3;c++) {
        int rr[2],cc[2],n=0;
        for(int k=0;k<3;k++)if(k!=c)rr[n++]=k;
        n=0;for(int k=0;k<3;k++)if(k!=r)cc[n++]=k;
        float co=ref(original[rr[0]][cc[0]],original[rr[1]][cc[1]],
                     -(original[rr[1]][cc[0]]*original[rr[0]][cc[1]]));
        if((r+c)&1)co=-co;
        out[r][c]=co*d;
    }
    for(int r=0;r<3;r++) {
        out[r][3]=-ref(out[r][2],original[2][3],
                        -ref(-out[r][0],original[0][3],-(out[r][1]*original[1][3])));
        /* Original inverse uses src translations even when output aliases src. */
        if(alias)original[r][3]=out[r][3];
    }
}
static void reference_concat(Mtx inv,Mtx src,Mtx out) {
    if(fabsf(determinant(inv))<EPSILON) { MTXCopy(src,out);return; }
    Mtx a;reference_inverse(inv,a,0);
    for(int r=0;r<3;r++)for(int c=0;c<4;c++) {
        out[r][c]=ref(a[r][2],src[2][c],ref(a[r][0],src[0][c],a[r][1]*src[1][c]));
        if(c==3)out[r][c]+=a[r][3];
    }
}
''' + functions(adapted) + old + r'''
int main(void) {
    unsigned rng=71;int changed=0;
    for(profile=0;profile<2;profile++)for(int i=0;i<10000;i++) {
        Mtx a,b,e,n,alias,negative;
        for(int r=0;r<3;r++)for(int c=0;c<4;c++) {
            rng=1664525u*rng+1013904223u;a[r][c]=((int)(rng%2001)-1000)/113.0f;
            rng=1664525u*rng+1013904223u;b[r][c]=((int)(rng%2001)-1000)/197.0f;
        }
        if(i%7<4) {
            MTXIdentity(a);
            float edge=EPSILON;
            a[0][0]=i%7==0?0.0f:i%7==1?nextafterf(edge,0.0f):
                     i%7==2?edge:nextafterf(edge,INFINITY);
            a[0][3]=3;a[1][3]=-5;a[2][3]=7;
        }
        reference_inverse(a,e,0);HSD_MtxInverse(a,n);
        if(memcmp(e,n,sizeof(Mtx)))return 1;
        old_MtxInverse(a,negative);changed+=memcmp(negative,n,sizeof(Mtx))!=0;
        reference_inverse(a,e,1);MTXCopy(a,alias);HSD_MtxInverse(alias,alias);
        if(memcmp(e,alias,sizeof(Mtx)))return 2;
        if(fabsf(determinant(a))<EPSILON)MTXCopy(a,e);
        else {
            reference_inverse(a,n,0);
            for(int r=0;r<3;r++){for(int c=0;c<3;c++)e[r][c]=n[c][r];e[r][3]=0;}
        }
        HSD_MtxInverseTranspose(a,n);
        if(memcmp(e,n,sizeof(Mtx)))return 3;
        MTXCopy(a,alias);HSD_MtxInverseTranspose(alias,alias);
        if(memcmp(e,alias,sizeof(Mtx)))return 4;
        reference_concat(a,b,e);HSD_MtxInverseConcat(a,b,n);
        if(memcmp(e,n,sizeof(Mtx)))return 5;
        MTXCopy(a,alias);HSD_MtxInverseConcat(alias,b,alias);
        if(memcmp(e,alias,sizeof(Mtx)))return 6;
        MTXCopy(b,alias);HSD_MtxInverseConcat(a,alias,alias);
        if(memcmp(e,alias,sizeof(Mtx)))return 7;
        reference_concat(a,a,e);MTXCopy(a,alias);HSD_MtxInverseConcat(alias,alias,alias);
        if(memcmp(e,alias,sizeof(Mtx)))return 8;
    }
    return changed?0:9;
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
