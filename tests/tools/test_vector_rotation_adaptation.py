"""Actual lbvector source: polynomial and both rotation paths at bit precision."""
import ctypes
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_quaternion_product_adaptation import f32, bits

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from apply_source_adaptation import apply_adaptation


def fused(a, b, c):
    return f32(a * b + c)


def polynomial(angle, cosine=False):
    angle = f32(angle + math.pi / 2) if cosine else angle
    if angle > math.pi: angle = f32(angle - math.tau)
    elif angle < -math.pi: angle = f32(angle + math.tau)
    cubic = f32(f32(f32(0.15527099370956421 * angle) * angle) * angle)
    quartic = f32(f32(f32(f32(0.0056429998949170113 * angle) * angle) * angle) * angle)
    return fused(angle, quartic, fused(0.9878619909286499, angle, -cubic))


def rotate(v, axis, angle, length):
    s, c = polynomial(angle), polynomial(angle, True)
    x, y, z = v
    if length > f32(1e-10):
        uy, uz = f32(axis[2] / length), f32(axis[1] / length)
        y, z = fused(y, uy, -f32(z * uz)), fused(y, uz, f32(z * uy))
    x2, z2 = fused(x, length, -f32(z * axis[0])), fused(x, axis[0], f32(z * length))
    x3, y3 = fused(x2, c, -f32(y * s)), fused(x2, s, f32(y * c))
    x, y, z = fused(x3, length, f32(z2 * axis[0])), y3, fused(-x3, axis[0], f32(z2 * length))
    if length > f32(1e-10):
        y, z = fused(y, uy, f32(z * uz)), fused(-y, uz, f32(z * uy))
    return [bits(a) for a in (x, y, z)]


class VectorRotationTests(unittest.TestCase):
    def test_polynomial_and_rotation_paths(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/lbvector.json').read_text())
        original = (Path(decomp) / spec['source_path']).read_bytes()
        adapted = apply_adaptation(original, spec).decode()
        start, end = adapted.index('static float lbvector_sin('), adapted.index('#ifdef MUST_MATCH')
        code = '#include "native_msl_math.h"\n#define M_PI 3.14159265358979323846\n#define M_TAU (2.0 * M_PI)\n'
        code += '#define sqrtf PF_MSLSqrtf\ntypedef struct {float x,y,z;} Vec3;\n' + adapted[start:end]
        start = adapted.index('void lbVector_CreateEulerMatrix(')
        end = adapted.index('\n}', start) + 2
        code += '\ntypedef float Mtx[3][4]; typedef struct {float x,y,z,w;} Quaternion;\n' + adapted[start:end]
        code += '\nfloat test_sin(float a){return lbvector_sin(a);}\nfloat test_cos(float a){return lbvector_cos(a);}\n'
        code += 'float test_length(float y,float z){return PF_MSLSqrtf(y*y+z*z);}\n'
        with tempfile.TemporaryDirectory(prefix='ssbm-rotation-') as tmp:
            tmp = Path(tmp); source = tmp / 'rotate.c'; library = tmp / 'rotate.so'; source.write_text(code)
            compiled = subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-ffp-contract=off', '-fno-fast-math',
                                      '-I', str(ROOT / 'src/ssbm/native_compat'), '-I', str(Path(decomp) / 'extern/dolphin/include'),
                                      str(source), str(ROOT / 'src/ssbm/native_compat/native_arithmetic.c'),
                                      '-lm', '-o', str(library)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            lib = ctypes.CDLL(str(library)); array = ctypes.c_float * 3
            for fn in (lib.test_sin, lib.test_cos): fn.argtypes = [ctypes.c_float]; fn.restype = ctypes.c_float
            lib.test_length.argtypes = [ctypes.c_float, ctypes.c_float]; lib.test_length.restype = ctypes.c_float
            lib.lbVector_RotateAboutUnitAxis.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.c_float]
            lib.lbVector_Rotate.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_float]
            lib.lbVector_CreateEulerMatrix.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
            angles = [0., -0., f32(math.pi), f32(-math.pi), f32(math.pi/2), f32(-math.pi/2)]
            rng = random.Random(0xD8F4); angles += [f32(rng.uniform(-math.pi, math.pi)) for _ in range(300)]
            axes = [[1.,0.,0.], [-1.,0.,0.], [0.,1.,0.], [0.,0.,1.], [1.,f32(1e-11),0.], [1.,f32(2e-10),0.],
                    [f32(1/math.sqrt(3))]*3]
            for angle in angles:
                self.assertEqual(bits(lib.test_sin(angle)), bits(polynomial(angle)))
                self.assertEqual(bits(lib.test_cos(angle)), bits(polynomial(angle, True)))
                v = [f32(rng.uniform(-20, 20)) for _ in range(3)]
                for axis in axes:
                    out = array(*v); lib.lbVector_RotateAboutUnitAxis(out, array(*axis), angle)
                    expected = rotate(v, axis, angle, lib.test_length(axis[1], axis[2]))
                    self.assertEqual([bits(a) for a in out], expected, (v, axis, angle))
                s, c = polynomial(angle), polynomial(angle, True); x,y,z = v
                expected = {
                    1:[x, fused(y,c,-f32(z*s)), fused(y,s,f32(z*c))],
                    2:[fused(x,c,f32(z*s)), y, fused(z,c,-f32(x*s))],
                    4:[fused(x,c,-f32(y*s)), fused(x,s,f32(y*c)), z],
                }
                for axis, wanted in expected.items():
                    out = array(*v); lib.lbVector_Rotate(out, axis, angle)
                    self.assertEqual([bits(a) for a in out], [bits(a) for a in wanted])
                angles3 = [angle, f32(angle / 3), f32(-angle / 2)]
                sx, sy, sz = [polynomial(a) for a in angles3]
                cx, cy, cz = [polynomial(a, True) for a in angles3]
                sxsy, cxsy = f32(sx * sy), f32(cx * sy)
                wanted = [f32(cy*cz), fused(cz,sxsy,-f32(cx*sz)), fused(cz,cxsy,f32(sx*sz)), 0.,
                          f32(cy*sz), fused(sz,sxsy,f32(cx*cz)), fused(sz,cxsy,-f32(sx*cz)), 0.,
                          -sy, f32(sx*cy), f32(cx*cy), 0.]
                matrix = (ctypes.c_float * 12)()
                lib.lbVector_CreateEulerMatrix(matrix, (ctypes.c_float * 4)(*angles3, 0))
                self.assertEqual([bits(a) for a in matrix], [bits(a) for a in wanted])


if __name__ == '__main__':
    unittest.main()
