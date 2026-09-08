"""Offline GDB Python script; load a compiler-produced object, never run a game.

Set PF_SSBM_TYPE_OUTPUT and optionally PF_SSBM_TYPE_ROOTS before invoking
gdb -batch <debug-object> -ex 'source tools/ssbm_gdb_type_inventory.py'.
This inventories the native ABI only. It grants no oracle layout equivalence.
"""
import hashlib
import json
import os
from pathlib import Path

import gdb


def inventory(root_names):
    known = []
    nodes = []
    roots = {}
    errors = []
    codes = {getattr(gdb, name): name.removeprefix('TYPE_CODE_').lower()
             for name in dir(gdb) if name.startswith('TYPE_CODE_')}

    def intern(original):
        value = original.strip_typedefs().unqualified()
        # Type equality retains anonymous struct identity; spelling alone does not.
        for index, previous in enumerate(known):
            if previous == value:
                return index
        known.append(value)
        return len(known) - 1

    for name in root_names:
        try:
            roots[name] = intern(gdb.lookup_type(name))
        except gdb.error as error:
            errors.append({'root': name, 'error': str(error)})
    cursor = 0
    while cursor < len(known):
        value = known[cursor]
        kind = codes[value.code]
        node = {'id': cursor, 'name': str(value), 'kind': kind}
        nodes.append(node)
        try:
            node['size_bytes'] = int(value.sizeof) if kind not in ('void', 'func') else 0
            if kind in ('struct', 'union'):
                node['fields'] = []
                for index, field in enumerate(value.fields()):
                    node['fields'].append({
                        'ordinal': index, 'name': field.name,
                        'native_bit_offset': int(field.bitpos),
                        'bit_size': int(field.bitsize),
                        'declared_type': str(field.type),
                        'type_id': intern(field.type),
                        'artificial': bool(field.artificial),
                    })
                node['complete'] = node['size_bytes'] > 0
            elif kind == 'array':
                low, high = value.range()
                node.update(lower_bound=int(low), upper_bound=int(high),
                            element_type=intern(value.target()))
            elif kind == 'ptr':
                node['target_type'] = intern(value.target())
            elif kind == 'func':
                node['return_type'] = intern(value.target())
                node['parameters'] = [intern(field.type) for field in value.fields()]
            elif kind == 'enum':
                node['values'] = [{'name': f.name, 'value': int(f.enumval)}
                                  for f in value.fields()]
            elif kind not in ('int', 'flt', 'bool', 'void'):
                errors.append({'type_id': cursor, 'error': 'unsupported type kind ' + kind})
            if kind == 'bool':
                node['signed'] = False
            elif kind in ('int', 'enum'):
                node['signed'] = bool(gdb.Value(-1).cast(value) < 0)
        except (gdb.error, TypeError, ValueError) as error:
            errors.append({'type_id': cursor, 'error': str(error)})
        cursor += 1
    files = [Path(obj.filename) for obj in gdb.objfiles()]
    return {
        'schema': 1,
        'claim_boundary': 'native compiler layout inventory; not canonical state qualification',
        'gdb_version': gdb.VERSION,
        'pointer_bytes': int(gdb.lookup_type('void').pointer().sizeof),
        'objects': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in files],
        'roots': roots, 'types': nodes, 'errors': errors,
        'unresolved_requirements': [
            'independent original ABI and bitfield mapping',
            'active union alternatives',
            'dynamic object ownership, lengths and stable identities',
            'callback and immutable asset identities',
            'padding versus gameplay storage classification',
            'complete global, stage, RNG and lifecycle state roots',
        ],
    }


output = Path(os.environ['PF_SSBM_TYPE_OUTPUT'])
names = os.environ.get('PF_SSBM_TYPE_ROOTS',
                       'Fighter,Item,HSD_JObj,HSD_GObj,HSD_GObjProc,CollData,HitCapsule,HurtCapsule,Article,HSD_AObj,Ground,StageInfo,CmSubject,Camera,HSD_FObj').split(',')
result = inventory(names)
output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'roots': len(result['roots']), 'types': len(result['types']),
                  'errors': result['errors'], 'output': str(output)}))
