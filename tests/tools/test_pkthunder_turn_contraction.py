"""Execute source-owned steering at cancellation and signed-zero boundaries."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation


class PKThunderTurnTests(unittest.TestCase):
    def test_both_directions_and_exact_cancellation(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        source=Path(source)
        spec=json.loads((ROOT/'tools/host_adaptations/itnesspkthunderball.json').read_text())
        adapted=apply_adaptation((source/spec['source_path']).read_bytes(),spec).decode()
        changes=[r for r in spec['replacements'] if 'angles[0]' in r['old']]
        self.assertEqual(len(changes),2)
        harness=r'''
#include "native_numeric.h"
#include <math.h>
#include <stdint.h>
#include <string.h>
#define MTXDegToRad(a) ((a)*0.01745329252f)
typedef struct {struct {struct {float angles[16];} pkthunder;} xDD4_itemVar;} Item;
typedef struct {float x10_PKTHUNDER_TURN_RADIUS;} Attr;
static uint32_t bits(float f) {uint32_t u;memcpy(&u,&f,4);return u;}
'''
        for i,change in enumerate(changes):
            self.assertIn(change['new'],adapted)
            for version in ('old','new'):
                harness+=f'static float {version}{i}(float angle,float radius) {{\n'
                harness+='Item item={0};Item* ip=&item;Attr attrs={radius};Attr* attr=&attrs;\n'
                harness+='ip->xDD4_itemVar.pkthunder.angles[0]=angle;\n'+change[version]
                harness+='\nreturn ip->xDD4_itemVar.pkthunder.angles[0];}\n'
        harness+=r'''
int main(void) {
    int changed[2]={0};
    for(int i=1;i<20000;i++) {
        float radius=(float)(i%360+1)/7.0f;
        float angle=(float)(i%2001-1000)/113.0f;
        float plus=fmaf(radius,0.01745329252f,angle);
        float minus=-fmaf(radius,0.01745329252f,-angle);
        if(bits(new0(angle,radius))!=bits(plus))return 1;
        if(bits(new1(angle,radius))!=bits(minus))return 2;
        changed[0]+=bits(old0(angle,radius))!=bits(plus);
        changed[1]+=bits(old1(angle,radius))!=bits(minus);
    }
    if(!changed[0]||!changed[1])return 3;
    /* A separately rounded degree product cancels to zero, losing the
       original fused residual. Check both signs and fnmsubs zero polarity. */
    float angle=MTXDegToRad(6.0f);
    if(bits(new1(angle,6.0f))!=0x31800000U)return 4;
    if(bits(old1(angle,6.0f))!=0U)return 5;
    if(bits(new0(-angle,6.0f))!=0xb1800000U)return 6;
    if(bits(new1(0.0f,0.0f))!=0x80000000U)return 7;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cfile,binary=Path(temp)/'turn.c',Path(temp)/'turn'
            cfile.write_text(harness)
            result=subprocess.run(['cc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off',
                '-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(source/'extern/dolphin/include'),
                str(cfile),'-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(binary)],check=True)


if __name__=='__main__':unittest.main()
