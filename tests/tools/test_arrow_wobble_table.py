"""Arrow wobble must use its own array, independent of linker placement."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation


class ArrowWobbleTests(unittest.TestCase):
    def test_no_unreviewed_float_arithmetic_from_global_addresses(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:
            self.skipTest('requires PF_SSBM_DECOMP_SOURCE_DIR')
        source=Path(source)
        pattern=re.compile(r'\((?:f32|float)\s*\*\)\s*&\s*\w+\s*\+')
        self.assertIsNotNone(pattern.search('(f32*) &unrelated_global + index'))
        specs={d['source_path']:d for path in (ROOT/'tools/host_adaptations').glob('*.json')
               if 'source_path' in (d:=json.loads(path.read_text()))}
        unreviewed=[]
        for path in (source/'src/melee').rglob('*.c'):
            raw=path.read_bytes()
            if not pattern.search(raw.decode()):continue
            relative=path.relative_to(source).as_posix()
            text=apply_adaptation(raw,specs[relative]).decode() if relative in specs else raw.decode()
            if pattern.search(text):unreviewed.append(relative)
        self.assertEqual(unreviewed,[], 'Review address-relative global float accesses before importing them')

    def test_all_counters_with_unrelated_neighbor_data(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        source=Path(source)
        spec=json.loads((ROOT/'tools/host_adaptations/itlinkarrow.json').read_text())
        raw=(source/spec['source_path']).read_bytes()
        adapted=apply_adaptation(raw,spec).decode()
        self.assertNotIn('(f32*) &it_803F6A28',adapted)
        table=re.search(r'f32 it_803F6A84\[\] = \{.*?\};',adapted,re.S).group()
        def body(text):
            start=text.index('    switch (ip->xDD4_itemVar.linkarrow.x9C)',text.index('bool itLinkarrow_UnkMotion4_Anim'))
            end=text.index('    HSD_JObjSetRotationZ',start)
            return text[start:end]
        harness=r'''
#include "native_numeric.h"
#include <math.h>
#include <stdint.h>
#include <string.h>
typedef float f32;
#define MTXDegToRad(a) ((a)*0.01745329252f)
typedef struct {struct {struct {int x9C;float x94;} linkarrow;} xDD4_itemVar;} Item;
static float random_value;
static float HSD_Randf(void){return random_value;}
/* Deliberately unrelated adjacent data: the old expression must not work
   merely because one particular link happened to place globals together. */
static float it_803F6A28[64];
static unsigned bits(float f){unsigned u;memcpy(&u,&f,4);return u;}
'''+table+'\n'
        for label,text in [('old',raw.decode()),('fixed',adapted)]:
            harness+=f'static float {label}(int counter,float angle) {{\n'
            harness+='Item item={0};Item* ip=&item;float rand,var_f31,var_f32;float* temp_r3;\n'
            harness+='ip->xDD4_itemVar.linkarrow.x9C=counter;ip->xDD4_itemVar.linkarrow.x94=angle;\n'
            harness+=body(text)+'return var_f31;}\n'
        harness+=r'''
int main(void){
 int negative_controls=0;
 for(int placement=0;placement<3;placement++){
  for(int j=0;j<64;j++)it_803F6A28[j]=placement==0?NAN:(float)(j+1)*(placement==1?17.0f:-9.0f);
  for(int counter=-2;counter<=9;counter++)for(int r=0;r<=1024;r++){
   random_value=(float)r/1024.0f;
   float angle=(float)(r-512)/97.0f,expected=angle;
   if(counter>=0&&counter<=6){
    float degrees=fmaf((float)(counter+2),random_value,(float)(2*counter+2));
    float delta=degrees*0.01745329252f;
    expected=(counter&1)?angle-delta:angle+delta;
   }
   if(bits(fixed(counter,angle))!=bits(expected))return 1;
   if(counter>=0&&counter<=6)negative_controls+=bits(old(counter,angle))!=bits(expected);
  }
 }
 return negative_controls?0:2;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c,binary=Path(temp)/'wobble.c',Path(temp)/'wobble'
            c.write_text(harness)
            subprocess.run(['cc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off',
                '-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(source/'extern/dolphin/include'),
                str(c),'-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)


if __name__=='__main__':unittest.main()
