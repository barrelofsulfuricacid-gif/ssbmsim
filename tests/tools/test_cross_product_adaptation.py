"""Native cross-product provider must retain retail paired-single arithmetic."""
import ctypes
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_quaternion_product_adaptation import f32, bits, value

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


def retail_cross(a, b):
    # PSVECCrossProduct, GALE01 80342E58-80342E90. The latter two
    # components negate a fused difference; do not swap its rounded term.
    ax, ay, az = a; bx, by, bz = b
    return [bits(f32(ay * bz - f32(az * by))),
            bits(-f32(ax * bz - f32(az * bx))),
            bits(-f32(ay * bx - f32(ax * by)))]


class CrossProductTests(unittest.TestCase):
    def test_source_rounding_zero_signs_and_aliases(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/dolphin_vec.json').read_text())
        original = (Path(decomp) / spec['source_path']).read_bytes()
        adapted = apply_adaptation(original, spec).decode()

        def body(text):
            start = text.index('void C_VECCrossProduct(')
            return text[start:text.index('\n}', start) + 2]

        code = '#include "native_numeric.h"\ntypedef struct {float x,y,z;} Vec;\n#define ASSERTMSGLINE(...)\n'
        code += body(adapted) + '\n' + body(original.decode()).replace('C_VECCrossProduct', 'original_cross')
        with tempfile.TemporaryDirectory(prefix='ssbm-cross-') as tmp:
            tmp = Path(tmp); source = tmp / 'cross.c'; library = tmp / 'cross.so'; source.write_text(code)
            compiled = subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-ffp-contract=off', '-fno-fast-math',
                                      '-I', str(ROOT / 'src/ssbm/native_compat'), '-I', str(Path(decomp) / 'extern/dolphin/include'),
                                      str(source), '-lm', '-o', str(library)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            lib = ctypes.CDLL(str(library)); array = ctypes.c_float * 3
            for fn in (lib.C_VECCrossProduct, lib.original_cross):
                fn.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3; fn.restype = None
            witness = (list(map(value, [1062261776, 3205732872, 1036800950])),
                       list(map(value, [1065336606, 3139321352, 3174429628])))
            cases = [witness]
            for order in itertools.permutations(range(3)):
                for signs in itertools.product((-1, 1), repeat=3):
                    cases.append(([witness[0][i] * signs[j] for j, i in enumerate(order)],
                                  [witness[1][i] for i in order]))
            rng = random.Random(0x342E58)
            cases.extend(([f32(rng.uniform(-1, 1)) for _ in range(3)],
                          [f32(rng.uniform(-1, 1)) for _ in range(3)]) for _ in range(2000))
            # Parallel, zero and orthogonal vectors preserve exact zero signs.
            cases.extend([(a, b) for a in ([0., 0., 0.], [-0., 0., -0.], [1., 0., 0.], [1., 1., 1.])
                          for b in ([0., 0., 0.], [0., -1., 0.], [1., 1., 1.])])
            old_misses = 0
            for a, b in cases:
                expected = retail_cross(a, b)
                previous = array(); lib.original_cross(array(*a), array(*b), previous)
                old_misses += [bits(x) for x in previous] != expected
                for alias in ('separate', 'a', 'b'):
                    aa, bb = array(*a), array(*b)
                    out = aa if alias == 'a' else bb if alias == 'b' else array()
                    lib.C_VECCrossProduct(aa, bb, out)
                    self.assertEqual([bits(x) for x in out], expected, (a, b, alias))
            self.assertGreater(old_misses, 0)


if __name__ == '__main__':
    unittest.main()
