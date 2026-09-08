"""Retail PK Flash physics preserves X, including its exact stored bits."""
import ctypes
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


class NessProjectileTests(unittest.TestCase):
    def test_flash_velocity_components_follow_retail_stores(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/itnesspkflashexplode.json').read_text())
        adapted = apply_adaptation((Path(decomp) / spec['source_path']).read_bytes(), spec).decode()
        start = adapted.index('void itNessPKFlashExplode_UnkMotion0_Phys(')
        function = adapted[start:adapted.index('\n}', start) + 2]
        code = '''
typedef struct { float x,y,z; } Vec;
typedef struct { Vec x40_vel; } Item;
typedef struct { Item *item; } Item_GObj;
#define GET_ITEM(gobj) ((gobj)->item)
''' + function
        class Item(ctypes.Structure):
            _fields_ = [('words', ctypes.c_uint32 * 3)]
        class GObj(ctypes.Structure):
            _fields_ = [('item', ctypes.POINTER(Item))]
        with tempfile.TemporaryDirectory(prefix='ness-velocity-') as tmp:
            tmp = Path(tmp)
            (tmp / 'test.c').write_text(code)
            subprocess.run(['cc', '-shared', '-fPIC', '-O3', '-Wall', '-Wextra', '-Werror',
                            '-ffp-contract=off', '-fno-fast-math', str(tmp / 'test.c'),
                            '-o', str(tmp / 'test.so')], check=True, capture_output=True)
            lib = ctypes.CDLL(str(tmp / 'test.so'))
            fn = lib.itNessPKFlashExplode_UnkMotion0_Phys
            fn.argtypes = [ctypes.POINTER(GObj)]
            fn.restype = None
            # X is not reset by retail; cover signed zero, finite velocities,
            # subnormals and untouched NaN payloads. Y and Z become positive zero.
            for x in (0, 0x80000000, 0x3f800000, 0xc1200000, 1, 0x7fc01234):
                item = Item((ctypes.c_uint32 * 3)(x, 0xbf800000, 0x80000000))
                fn(ctypes.byref(GObj(ctypes.pointer(item))))
                self.assertEqual(list(item.words), [x, 0, 0])


if __name__ == '__main__':
    unittest.main()
