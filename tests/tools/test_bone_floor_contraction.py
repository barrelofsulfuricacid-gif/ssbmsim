"""Compile the original shared bone-floor solver and exercise strict boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation

class BoneFloorTests(unittest.TestCase):
    def test_floor_intersection(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:self.skipTest('requires pinned decomp source')
        spec=json.loads((ROOT/'tools/host_adaptations/lb_00F9.json').read_text())
        original=(Path(source)/spec['source_path']).read_bytes()
        adapted=apply_adaptation(original,spec).decode()
        def extract(text):
            start=text.index('\nbool lb_800103D8(')+1
            return text[start:text.index('\n#ifdef MUST_MATCH',start)]
        harness=r'''
#include "native_numeric.h"
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef struct { float x,y,z; } Vec3;
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void) { return profile; }
static uint32_t bits(float v) { uint32_t u;memcpy(&u,&v,4);return u; }
''' + extract(adapted) + extract(original.decode()).replace('lb_800103D8','old_floor') + r'''
int main(void) {
    unsigned rng=733;int changed=0;
    for(profile=0;profile<2;profile++)for(int i=0;i<30000;i++) {
        float v[5];
        for(int j=0;j<5;j++){rng=rng*1664525u+1013904223u;v[j]=((int)(rng%200001)-100000)/137.0f;}
        if(i%6==0)v[1]=v[3];
        if(i%6==1)v[1]=v[4];
        if(i%6==2)v[3]=v[4];
        if(i%6==3)v[1]=nextafterf(v[4],INFINITY);
        if(i%6==4)v[3]=nextafterf(v[4],-INFINITY);
        float a=v[1]-v[4],b=v[3]-v[4];
        Vec3 actual={17,23,31},expected=actual,old=actual;
        bool hit=false;
        if(a==b)hit=a>1e-10f;
        else if((double)a>0 && (double)b<0) {
            float ratio=-b/(a-b),delta=v[0]-v[2];
            volatile double product=(double)ratio*delta;
            volatile double sum=product+v[2];
            expected.x=(float)sum;expected.y=v[4];expected.z=0;hit=true;
        }
        bool result=lb_800103D8(&actual,v[0],v[1],v[2],v[3],v[4]);
        if(result!=hit || bits(actual.x)!=bits(expected.x) || bits(actual.y)!=bits(expected.y) || bits(actual.z)!=bits(expected.z))return 1;
        old_floor(&old,v[0],v[1],v[2],v[3],v[4]);
        changed+=bits(old.x)!=bits(expected.x);
    }
    return changed?0:2;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.c';exe=Path(tmp)/'test';path.write_text(harness)
            subprocess.run(['cc','-O2','-ffp-contract=off','-fno-fast-math','-fsanitize=address,undefined',
                            '-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),
                            str(path),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__':unittest.main()
