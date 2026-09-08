"""Exercise both source line-traversal directions under bounds sanitizers."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


class MplibScratchTests(unittest.TestCase):
    def test_no_negative_sqrt_scratch_indices_remain_in_imported_source(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp:
            self.skipTest('requires PF_SSBM_DECOMP_SOURCE_DIR')
        specs = {}
        for path in (ROOT / 'tools/host_adaptations').glob('*.json'):
            spec = json.loads(path.read_text())
            specs[spec['source_path']] = spec
        pattern = re.compile(r'sqrtf_store\([^;\n]*sqrt_tmp\s*-\s*[1-9]')
        found = 0
        for path in (Path(decomp) / 'src').rglob('*.c'):
            raw = path.read_bytes()
            if not pattern.search(raw.decode()):
                continue
            found += len(pattern.findall(raw.decode()))
            name = path.relative_to(decomp).as_posix()
            self.assertIn(name, specs, f'unadapted negative scratch index in {name}')
            adapted = apply_adaptation(raw, specs[name]).decode()
            self.assertIsNone(pattern.search(adapted), name)
        self.assertEqual(found, 5, 'pinned source scratch-site inventory changed; audit new sites')

    def test_line_queries_use_in_bounds_volatile_scratch(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/mplib.json').read_text())
        adapted = apply_adaptation((Path(decomp) / spec['source_path']).read_bytes(), spec).decode()
        def function(prefix):
            start = adapted.index(prefix)
            return adapted[start:adapted.index('\n}', start)+2]
        source = function('static inline float sqrtf_store(') + '\n' + function('bool mpLib_80056C54(')
        preamble = r'''
#include <assert.h>
#include <math.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef float f32;
typedef struct { float x,y,z; } Vec3;
#define SQ(x) ((x)*(x))
#define CollLine_Floor 1
// This fixture isolates scratch lifetime/bounds, not Gekko sqrt numerics.
static double __frsqrte(double x) { return 1.0/sqrt(x); }
static bool mpLib_80054ED8(int id) { return id == 0; }
static int mpLib_8004DD90_Floor(int id, Vec3 *pos, float *dy, void *a, void *b) {
    (void)id; (void)pos; (void)a; (void)b; *dy = 0; return 0;
}
static void mpLineGetV1Pos(int id, Vec3 *v) { (void)id; *v = (Vec3){100,0,0}; }
static void mpLineGetV0Pos(int id, Vec3 *v) { (void)id; *v = (Vec3){-100,0,0}; }
static unsigned mpLineGetKind(int id) { (void)id; return CollLine_Floor; }
static int mpLineGetNext(int id) { (void)id; return -1; }
static int mpLineGetPrev(int id) { (void)id; return -1; }
static unsigned mpLineGetFlags(int id) { (void)id; return 17; }
static void mpLineGetNormal(int id, Vec3 *n) { (void)id; *n = (Vec3){0,1,0}; }
'''
        main = r'''
int main(void) {
    Vec3 pos = {0}, out, normal;
    unsigned flags;
    int line;
    for (int repeat=0; repeat<1000; ++repeat) {
        for (int side=-1; side<=1; side+=2) {
            assert(mpLib_80056C54(0,&pos,&line,&out,&flags,&normal,25.0f*side,10));
            assert(line==0 && out.x==25.0f*side && out.y==0 && out.z==0);
            assert(flags==17 && normal.x==0 && normal.y==1 && normal.z==0);
            assert(mpLib_80056C54(0,&pos,NULL,&out,NULL,NULL,25.0f*side,10));
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='mplib-scratch-') as tmp:
            tmp = Path(tmp)
            for label, body in [('adapted', source), ('negative-control', source.replace('&sqrt_tmp[0]', 'sqrt_tmp - 4').replace('&sqrt_tmp[1]', 'sqrt_tmp - 5'))]:
                c = tmp / (label + '.c')
                c.write_text(preamble + body + main)
                exe = tmp / label
                subprocess.run(['cc', '-O2', '-fsanitize=undefined,address',
                                '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                                str(c), '-lm', '-o', str(exe)], check=True, capture_output=True)
                result = subprocess.run([str(exe)], capture_output=True, text=True)
                if label == 'adapted':
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, 'negative control must detect invalid scratch stores')


if __name__ == '__main__':
    unittest.main()
