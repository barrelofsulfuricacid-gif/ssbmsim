"""Compile actual source expressions and exercise contraction boundaries."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


class SpecialMoveContractionTests(unittest.TestCase):
    def test_source_expressions_round_once_and_old_forms_fail(self):
        source = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        source = Path(source)
        cases = [
            ('ftsamusspeciallw0', '(-da->x4 * value)',
             {'da->x4': 'a', 'value': 'b'}, '-a', 'b', '1.5707963705062866f'),
            ('ftluigispecials', 'sa->x28_LUIGI_GREENMISSILE_MUL_X *',
             {'sa->x28_LUIGI_GREENMISSILE_MUL_X': 'a',
              'fp->mv.lg.SpecialS.chargeFrames': 'charge',
              'sa->x24_LUIGI_GREENMISSILE_VEL_X': 'c'}, 'a', '(float)charge', 'c'),
            ('ftpikachuspecialhi', '(pika_attr->x90 * stick_mag)',
             {'pika_attr->x90': 'a', 'stick_mag': 'b', 'pika_attr->x94': 'c'}, 'a', 'b', 'c'),
            ('ftzeldaspecialhi', '((attributes->x54 * var_f31)',
             {'attributes->x54': 'a', 'var_f31': 'b', 'attributes->x58': 'c'}, 'a', 'b', 'c'),
            ('ftnessspecialhi', '((5.0f * fp->x34_scale.y)',
             {'fp->x34_scale.y': 'b', 'fp->cur_pos.y': 'c'}, '5.0f', 'b', 'c'),
        ]
        harness = '#include "native_numeric.h"\n#include <math.h>\n#include <stdint.h>\n#include <string.h>\n'
        for index, (name, prefix, names, a, b, c) in enumerate(cases):
            spec = json.loads((ROOT / 'tools/host_adaptations' / (name + '.json')).read_text())
            raw = (source / spec['source_path']).read_bytes()
            adapted = apply_adaptation(raw, spec).decode()
            entries = [r for r in spec['replacements'] if r['old'].startswith(prefix)]
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertIn(entry['new'], adapted)
            self.assertIn(entry['old'], raw.decode())
            for version in ('old', 'new'):
                expression = entry[version]
                for old, new in names.items():
                    expression = expression.replace(old, new)
                harness += f'static float {version}{index}(float a,float b,float c,int charge) {{return {expression};}}\n'
            harness += f'static float ref{index}(float a,float b,float c,int charge) {{return fmaf({a},{b},{c});}}\n'
        harness += r'''
static uint32_t bits(float f) {uint32_t u; memcpy(&u,&f,4); return u;}
static uint32_t seed=71231;
static float sample(void) {
    seed=1664525U*seed+1013904223U;
    /* Finite moderate inputs: the double intermediate cannot introduce
       double-rounding here, so independent libm fmaf is an exact reference. */
    uint32_t u=0x3e800000U|(seed&0x007fffffU);
    float f; memcpy(&f,&u,4); return f;
}
int main(void) {
    int changed[5]={0};
    for(int i=0;i<10000;i++) {
        float a=sample(),b=sample(),c=sample(); int charge=i%90;
        if(i&1) a=-a;
        if(i&2) b=-b;
        if(i&4) c=-c;
'''
        for index in range(len(cases)):
            harness += f'''
        if(bits(new{index}(a,b,c,charge))!=bits(ref{index}(a,b,c,charge))) return {index+1};
        changed[{index}] += bits(old{index}(a,b,c,charge))!=bits(ref{index}(a,b,c,charge));
'''
        harness += '    }\n for(int i=0;i<5;i++) if(!changed[i]) return 10+i; return 0;\n}\n'
        with tempfile.TemporaryDirectory() as temp:
            cfile, binary = Path(temp)/'test.c', Path(temp)/'test'
            cfile.write_text(harness)
            compiled = subprocess.run(['cc', '-std=c11', '-O2', '-fno-fast-math', '-ffp-contract=off',
                '-I', str(ROOT/'src/ssbm/native_compat'), '-I', str(source/'extern/dolphin/include'),
                str(cfile), '-lm', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            subprocess.run([str(binary)], check=True)

    def test_both_zelda_entries_preserve_binary64_refinement(self):
        source = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        source = Path(source)
        spec = json.loads((ROOT/'tools/host_adaptations/ftzeldaspecialhi.json').read_text())
        adapted = apply_adaptation((source/spec['source_path']).read_bytes(), spec).decode()
        entry = next(r for r in spec['replacements'] if r['old'].startswith('_half * guess'))
        self.assertEqual(adapted.count(entry['new']), 6)
        harness = r'''
#include "native_msl_math.h"
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void) {return profile;}
static double refinement(float var_f4, double guess) {
    const double _half=0.5, _three=3.0;
'''
        harness += 'return ' + entry['new'] + ';\n}\n'
        harness += r'''
int main(void) {
    for(profile=0;profile<2;profile++) {
        for(int k=1;k<2000;k++) {
            float x=(float)k/997.0f;
            double actual=PF_GekkoFrsqrte(x), expected=actual;
            for(int iteration=0;iteration<3;iteration++) {
                const double square=expected*expected, half=0.5*expected;
                double correction;
                if(profile==0) correction=-fma((double)x,square,-3.0);
                else {volatile double product=(double)x*square;
                      volatile double difference=product-3.0;
                      correction=-difference;}
                expected=half*correction;
                actual=refinement(x,actual);
                if(memcmp(&actual,&expected,8)) return 1;
            }
        }
    }
    profile=0;
    double x=PF_GekkoFrsqrte(2.0);
    for(int i=0;i<3;i++) x=refinement(2.0f,x);
    uint64_t bits; memcpy(&bits,&x,8);
    return bits!=UINT64_C(0x3fe6a09e667f3bcd);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cfile, binary = Path(temp)/'refine.c', Path(temp)/'refine'
            cfile.write_text(harness)
            compiled = subprocess.run(['cc', '-std=c11', '-O2', '-fno-fast-math', '-ffp-contract=off',
                '-I', str(ROOT/'src/ssbm/native_compat'), '-I', str(source/'extern/dolphin/include'),
                str(cfile), '-lm', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
