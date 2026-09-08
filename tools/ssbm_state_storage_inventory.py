"""Account for native object storage before admitting a canonical trace schema.

No category emitted here is an exemption from comparison. In particular, holes
are unclassified storage, pointers need identities, and unions need selectors.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def describe_root(inventory: dict, name: str) -> dict:
    types = inventory['types']
    root = types[inventory['roots'][name]]
    leaves = []
    issues = []
    size_bits = root['size_bytes'] * 8
    coverage = [None] * size_bits

    def emit(path, offset, size, role, type_id):
        leaf = dict(path=path, native_bit_offset=offset, size_bits=size,
                    role=role, type_id=type_id, oracle_layout_verified=False)
        leaves.append(leaf)
        if offset < 0 or size < 0 or offset + size > size_bits:
            issues.append(dict(path=path, issue='field outside root storage'))
            return
        for bit in range(offset, offset + size):
            if coverage[bit] is not None:
                issues.append(dict(path=path, issue='overlapping non-union storage', bit=bit))
                break
            coverage[bit] = role

    def walk(type_id, path, offset, ancestors):
        if type_id in ancestors:
            raise ValueError('recursive by-value type: ' + path)
        node = types[type_id]
        kind = node['kind']
        size = node['size_bytes'] * 8
        if kind == 'struct':
            if not node['complete']:
                issues.append(dict(path=path, issue='incomplete by-value type'))
                emit(path, offset, size, 'incomplete_type', type_id)
                return
            for field in node['fields']:
                label = field['name'] or f"<anonymous:{field['ordinal']}>"
                child = path + '.' + label
                start = offset + field['native_bit_offset']
                if field['bit_size']:
                    emit(child, start, field['bit_size'], 'bitfield', field['type_id'])
                else:
                    walk(field['type_id'], child, start, ancestors | {type_id})
        elif kind == 'array':
            count = node['upper_bound'] - node['lower_bound'] + 1
            stride = types[node['element_type']]['size_bytes'] * 8
            if count < 0 or count * stride != size:
                raise ValueError('invalid fixed array extent: ' + path)
            for index in range(count):
                walk(node['element_type'], f"{path}[{index + node['lower_bound']}]",
                     offset + index * stride, ancestors | {type_id})
        elif kind == 'union':
            emit(path, offset, size, 'union_requires_selector', type_id)
        elif kind == 'ptr':
            emit(path, offset, size, 'pointer_requires_identity', type_id)
        elif kind in ('int', 'flt', 'bool', 'enum'):
            emit(path, offset, size, 'scalar', type_id)
        else:
            emit(path, offset, size, 'unsupported_storage', type_id)

    walk(root['id'], name, 0, set())
    gaps = []
    index = 0
    while index < size_bits:
        if coverage[index] is not None:
            index += 1
            continue
        start = index
        while index < size_bits and coverage[index] is None:
            index += 1
        gaps.append(dict(native_bit_offset=start, size_bits=index - start,
                         role='unclassified_storage'))
    counts = Counter(value or 'unclassified_storage' for value in coverage)
    assert sum(counts.values()) == size_bits
    return dict(name=name, size_bytes=root['size_bytes'], fields=leaves,
                unclassified_ranges=gaps, storage_bits=dict(sorted(counts.items())),
                issues=issues, canonical_ready=False)


def build_report(inventory: dict) -> dict:
    if inventory.get('schema') != 1 or inventory.get('errors'):
        raise ValueError('invalid or incomplete type inventory')
    for index, node in enumerate(inventory['types']):
        if node['id'] != index:
            raise ValueError('noncanonical type indices')
    roots = [describe_root(inventory, name) for name in inventory['roots']]
    return dict(schema=1, claim_boundary='storage inventory only; never acceptance evidence',
                roots=roots, canonical_ready=False,
                blocking_requirements=inventory['unresolved_requirements'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--types', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    data = args.types.read_bytes()
    report = build_report(json.loads(data))
    report['type_inventory_sha256'] = hashlib.sha256(data).hexdigest()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps([{k: r[k] for k in ('name', 'size_bytes', 'storage_bits', 'issues')}
                      for r in report['roots']], indent=2))


if __name__ == '__main__':
    main()
