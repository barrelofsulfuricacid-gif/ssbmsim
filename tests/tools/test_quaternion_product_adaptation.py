"""Actual source quaternion product versus the GALE01 operation ordering."""
import ctypes
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def value(x):
    return struct.unpack('<f', struct.pack('<I', x))[0]


def retail_product(p, q):
    # 8037EC64-EC90 round seven products. 8037EC94-ECC0 contain
    # nine fused single operations and three separately rounded vector sums.
    # Slippi's single operations round the binary64 intermediate to binary32.
    px, py, pz, pw = p
    qx, qy, qz, qw = q
    x = f32(f32(qw * px + f32(pw * qx)) + f32(py * qz - f32(qy * pz)))
    y = f32(f32(qw * py + f32(pw * qy)) + f32(qx * pz - f32(px * qz)))
    z = f32(f32(qw * pz + f32(pw * qz)) + f32(px * qy - f32(qx * py)))
    dot_xy = f32(px * qx + f32(py * qy))
    dot_xyz = f32(pz * qz + dot_xy)
    return [bits(v) for v in (x, y, z, f32(pw * qw - dot_xyz))]


class QuaternionProductTests(unittest.TestCase):
    def test_source_rounding_and_aliasing(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/quatlib.json').read_text())
        original = (Path(decomp) / spec['source_path']).read_bytes()
        adapted = apply_adaptation(original, spec).decode()

        def body(text):
            return text[text.index('s32 HSD_QuatLib_8037EC4C('):text.index('s32 HSD_QuatLib_8037ECE0(')]

        code = '#include "native_numeric.h"\n'
        code += 'typedef struct {float x,y,z,w;} Quaternion;\n#define PAD_STACK(n)\n'
        code += body(adapted) + body(original.decode()).replace('HSD_QuatLib_8037EC4C', 'original_product')
        with tempfile.TemporaryDirectory(prefix='ssbm-quaternion-') as tmp:
            tmp = Path(tmp); source = tmp / 'product.c'; library = tmp / 'product.so'
            source.write_text(code)
            compiled = subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-ffp-contract=off', '-fno-fast-math',
                            '-I', str(ROOT / 'src/ssbm/native_compat'), '-I', str(Path(decomp) / 'extern/dolphin/include'),
                            str(source), '-lm', '-o', str(library)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            lib = ctypes.CDLL(str(library)); array = ctypes.c_float * 4
            for fn in (lib.HSD_QuatLib_8037EC4C, lib.original_product):
                fn.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
                fn.restype = ctypes.c_long
            # Two actual first-frame Yoshi dynamics calls anchor the domain.
            # These inputs alone do not distinguish old and adapted products.
            witnesses = [
                ([1038939009, 994143407, 1019143193, 1065235886], [1014172591, 3186478868, 3172042723, 1065227200]),
                ([1039133323, 3164072947, 3183096396, 1065164815], [1043018403, 1038195043, 1018858722, 1065009078]),
            ]
            cases = [(list(map(value, p)), list(map(value, q))) for p, q in witnesses]
            old_misses = 0
            for p, q in cases:
                output = array(); lib.original_product(array(*p), array(*q), output)
                old_misses += [bits(x) for x in output] != retail_product(p, q)
            # Component permutations/signs cover cancellation in every output.
            for p, q in list(cases):
                for order in itertools.permutations(range(4)):
                    for signs in itertools.product((-1, 1), repeat=4):
                        cases.append(([p[i] * signs[j] for j, i in enumerate(order)],
                                      [q[i] for i in order]))
            rng = random.Random(0x37EC4C)
            cases.extend(([f32(rng.uniform(-1, 1)) for _ in range(4)],
                          [f32(rng.uniform(-1, 1)) for _ in range(4)]) for _ in range(2000))
            cases.extend([([0, 0, 0, 1], [0, 0, 0, 1]), ([1, 0, 0, 0], [0, 1, 0, 0])])
            for p, q in cases:
                expected = retail_product(p, q)
                previous = array(); lib.original_product(array(*p), array(*q), previous)
                old_misses += [bits(x) for x in previous] != expected
                for alias in ('separate', 'p', 'q'):
                    a, b = array(*p), array(*q)
                    out = a if alias == 'p' else b if alias == 'q' else array()
                    self.assertEqual(lib.HSD_QuatLib_8037EC4C(a, b, out), 0)
                    self.assertEqual([bits(x) for x in out], expected, (p, q, alias))
            self.assertGreater(old_misses, 0)


if __name__ == '__main__':
    unittest.main()
