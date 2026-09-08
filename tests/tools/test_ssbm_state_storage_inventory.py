"""Compile synthetic types and prove the audit cannot hide pointer/union/gap storage."""
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
from ssbm_state_storage_inventory import build_report
from ssbm_build_type_inventory import production_command


class StorageTests(unittest.TestCase):
    def test_production_flags_not_test_target_flags(self):
        target = 'CMakeFiles/ssbm_native_host_providers.dir/src/ssbm/native_compat/native_fighter_state.c.o'
        production = f'gcc -DPRODUCTION=1 -o {target} -c /repo/native_fighter_state.c'
        test = 'gcc -include target_bool.h -o CMakeFiles/test.dir/native_fighter_state.c.o -c /repo/native_fighter_state.c'
        self.assertEqual(production_command(test + '\n' + production), production)
        with self.assertRaises(ValueError):
            production_command(test)
        with self.assertRaises(ValueError):
            production_command(production + '\n' + production)

    def test_compiler_inventory_and_unresolved_storage(self):
        if not shutil.which('gcc') or not shutil.which('gdb'):
            self.skipTest('requires gcc and GDB Python')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / 'types.c'
            obj = tmp / 'types.o'
            output = tmp / 'types.json'
            source.write_text('''
typedef struct Node {
    unsigned char tag;
    unsigned bits:3;
    unsigned rest:5;
    unsigned short count;
    struct Node *next;
    union { float charge; unsigned word; } state;
    float positions[3];
} Node;
Node *root;
''')
            subprocess.run(['gcc', '-g', '-gdwarf-4', '-fno-eliminate-unused-debug-types',
                            '-c', str(source), '-o', str(obj)], check=True)
            env = dict(os.environ, PF_SSBM_TYPE_OUTPUT=str(output), PF_SSBM_TYPE_ROOTS='Node')
            subprocess.run(['gdb', '-q', '-batch', str(obj), '-ex',
                            'source ' + str(ROOT / 'tools/ssbm_gdb_type_inventory.py')],
                           env=env, check=True, capture_output=True, text=True)
            inventory = json.loads(output.read_text())
            report = build_report(inventory)
            root = report['roots'][0]
            fields = {f['path']: f for f in root['fields']}
            self.assertEqual(fields['Node.next']['role'], 'pointer_requires_identity')
            self.assertEqual(fields['Node.state']['role'], 'union_requires_selector')
            self.assertEqual(fields['Node.bits']['size_bits'], 3)
            self.assertEqual(fields['Node.rest']['size_bits'], 5)
            self.assertEqual(sum(k.startswith('Node.positions[') for k in fields), 3)
            self.assertTrue(all(not f['oracle_layout_verified'] for f in fields.values()))
            self.assertFalse(report['canonical_ready'])
            self.assertEqual(sum(root['storage_bits'].values()), root['size_bytes'] * 8)
            self.assertFalse(root['issues'])
            # No field, even an ordinary scalar, supplies original-ABI proof.
            self.assertTrue(report['blocking_requirements'])
            # Inject a malformed offset: an overlap must remain an explicit issue.
            type_root = inventory['types'][inventory['roots']['Node']]
            next(f for f in type_root['fields'] if f['name'] == 'next')['native_bit_offset'] = 0
            damaged = build_report(inventory)['roots'][0]
            self.assertTrue(any(i['issue'] == 'overlapping non-union storage'
                                for i in damaged['issues']))

    def test_rejects_incomplete_extraction(self):
        with self.assertRaises(ValueError):
            build_report({'schema': 1, 'errors': [{'root': 'Missing'}]})


if __name__ == '__main__':
    unittest.main()
