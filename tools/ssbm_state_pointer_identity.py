"""Address-independent identities for explicitly captured state objects.

Identities are supplied by the capture's ordered roots, not inferred from pointer
values or object contents. Unknown non-null pointers remain unresolved. These
are snapshot identities, not creation/destruction history or qualification.
"""
from __future__ import annotations


class ObjectIdentities:
    def __init__(self):
        self.by_address = {}
        self.by_identity = {}

    def add(self, identity: str, address: int):
        if not identity or not isinstance(address, int) or address <= 0:
            raise ValueError('object identity requires a non-null address')
        if identity in self.by_identity and self.by_identity[identity] != address:
            raise ValueError('one identity assigned to different objects: ' + identity)
        if address in self.by_address and self.by_address[address] != identity:
            raise ValueError('object alias requires an explicit shared identity')
        self.by_identity[identity] = address
        self.by_address[address] = identity

    def resolve(self, address: int):
        if not isinstance(address, int) or address < 0:
            raise ValueError('invalid pointer value')
        if address == 0:
            return {'kind': 'null'}
        if address in self.by_address:
            return {'kind': 'object', 'identity': self.by_address[address]}
        return {'kind': 'unresolved', 'address': hex(address)}


def compare_pointer(native: int, oracle: int, native_objects: ObjectIdentities,
                    oracle_objects: ObjectIdentities):
    left = native_objects.resolve(native)
    right = oracle_objects.resolve(oracle)
    # Equal numeric addresses (including dangling pointers) prove nothing.
    status = ('unresolved' if 'unresolved' in (left['kind'], right['kind'])
              else 'equal' if left == right else 'different')
    return {'status': status, 'native': left, 'oracle': right}


def audit_snapshot_pointers(records, storage, types, byteorder):
    """Report every pointer leaf in captured native roots, including unknowns.

    The storage inventory describes the native ABI only. This function must not
    be used to infer oracle offsets. Unions retain their separate unresolved
    status in the storage report and are not flattened into pointer guesses.
    """
    if byteorder not in ('little', 'big'):
        raise ValueError('invalid byte order')
    registry = ObjectIdentities()
    roots = {root['name']: root for root in storage['roots']}
    for record in records:
        registry.add(record['identity'], record['address'])
    result = []
    for record in records:
        root = roots[record['type']]
        if root['issues']:
            raise ValueError('invalid root storage layout')
        blob = bytes.fromhex(record['data'])
        if len(blob) != root['size_bytes']:
            raise ValueError('captured object size differs from native layout')
        for field in root['fields']:
            if field['role'] != 'pointer_requires_identity':
                continue
            offset, width = field['native_bit_offset'], field['size_bits']
            if offset % 8 or width != types['pointer_bytes'] * 8:
                raise ValueError('invalid pointer field layout')
            node = types['types'][field['type_id']]
            if node['kind'] != 'ptr':
                raise ValueError('pointer role assigned to another type')
            address = int.from_bytes(blob[offset//8:(offset+width)//8], byteorder)
            result.append({'object': record['identity'], 'field': field['path'],
                           'target_type': types['types'][node['target_type']]['name'],
                           'value': registry.resolve(address)})
    return result


def capture_joint_graph(read, seeds: dict[str, int], byteorder: str, limit=16384):
    """Capture explicitly typed JObj roots, preserving shared child references.

    Root paths and ordered next/child edges determine the first owning path.
    Shared instances reuse that identity. Parent pointers are captured but not
    traversed, so an out-of-scope parent stays unresolved during comparison.
    """
    if byteorder not in ('little', 'big') or limit <= 0:
        raise ValueError('invalid joint capture configuration')
    queue = list(sorted(seeds.items()))
    registry = ObjectIdentities()
    records = []
    cursor = 0
    while cursor < len(queue):
        identity, address = queue[cursor]
        cursor += 1
        if address == 0 or address in registry.by_address:
            continue
        if len(records) >= limit:
            raise ValueError('excessive joint graph')
        registry.add(identity, address)
        blob = bytes(read(address, 0x88))
        if len(blob) != 0x88:
            raise ValueError('short joint read')
        records.append({'identity':identity, 'address':address,
                        'type':'HSD_JObj', 'data':blob.hex()})
        for name, offset in [('next',8), ('child',16)]:
            target = int.from_bytes(blob[offset:offset+4], byteorder)
            queue.append((identity + '.' + name, target))
    return records, registry


def capture_fighter_dynamics(read, fighters, byteorder: str):
    """Capture the source-owned bone-dynamics alternative of DynamicsData.

    Other users of the PolymorphicDesc union are not assumed to be bone data.
    Counts and list lengths must agree before this selector can be used.
    """
    if byteorder not in ('little','big'):
        raise ValueError('invalid byte order')
    def exact(address,size):
        value=bytes(read(address,size))
        if len(value)!=size:raise ValueError('short dynamics read')
        return value
    def u(address):return int.from_bytes(exact(address,4),byteorder)
    result=[]
    registry=ObjectIdentities()
    for fighter in fighters:
        if fighter['type']!='Fighter':continue
        fp=fighter['address']
        count=u(fp+0x3e0)
        if count>10:raise ValueError('invalid fighter dynamics set count')
        for index in range(count):
            desc=fp+0x2f0+index*24
            node=u(desc+4);length=u(desc+8)
            if length>320:raise ValueError('invalid dynamics chain count')
            part=0;seen=set()
            while node:
                if node in seen or part>=length:raise ValueError('invalid dynamics chain')
                seen.add(node)
                identity=f"{fighter['identity']}.dynamic_bone_sets[{index}].data[{part}]"
                registry.add(identity,node)
                blob=exact(node,0x98)
                result.append({'identity':identity,'address':node,'type':'DynamicsData',
                               'active_union':'desc.lb_unk0','data':blob.hex()})
                node=int.from_bytes(blob[0x90:0x94],byteorder);part+=1
            if part!=length:raise ValueError('short dynamics chain')
    return result,registry


def capture_entity_lists(read, heads: dict[int, int], byteorder: str,
                         data_sizes: dict[int, tuple[str, int]], limit=4096):
    """Capture ordered fighter/item roots through a read-only memory reader.

    GObj offsets are the explicit source layout in sysdolphin/baselib/gobj.h:
    next=8, user_data=0x2c, size=0x38. Caller owns evidence for that layout on
    each side. Unsupported lists must not be passed or silently skipped.
    """
    if byteorder not in ('little', 'big') or limit <= 0:
        raise ValueError('invalid capture configuration')
    registry = ObjectIdentities()
    records = []

    def exact(address, size):
        data = bytes(read(address, size))
        if len(data) != size:
            raise ValueError('short object read')
        return data

    for link, head in sorted(heads.items()):
        if link not in data_sizes:
            raise ValueError('missing list data type')
        data_type, data_size = data_sizes[link]
        if data_size <= 0:
            raise ValueError('invalid object size')
        address = head
        seen = set()
        index = 0
        while address:
            if address in seen or index >= limit:
                raise ValueError('cyclic or excessive entity list')
            seen.add(address)
            identity = f'entities[{link}][{index}]'
            registry.add(identity, address)
            obj = exact(address, 0x38)
            if obj[2] != link:
                raise ValueError('object belongs to another entity list')
            user = int.from_bytes(obj[0x2c:0x30], byteorder)
            registry.add(identity + '.user_data', user)
            records.extend([
                {'identity': identity, 'address': address, 'type': 'HSD_GObj', 'data': obj.hex()},
                {'identity': identity + '.user_data', 'address': user,
                 'type': data_type, 'data': exact(user, data_size).hex()},
            ])
            address = int.from_bytes(obj[8:12], byteorder)
            index += 1
    return records, registry
