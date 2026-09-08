import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from ssbm_state_pointer_identity import ObjectIdentities, compare_pointer, capture_entity_lists, capture_joint_graph, capture_fighter_dynamics


class IdentityTests(unittest.TestCase):
    def test_dynamic_union_selector_requires_valid_chain(self):
        for order in ('little','big'):
            memory=bytearray(0x4000)
            def put(address,value):memory[address:address+4]=value.to_bytes(4,order)
            def read(address,size):return memory[address:address+size]
            put(0x1000+0x3e0,1)
            put(0x1000+0x2f4,0x2000)
            put(0x1000+0x2f8,2)
            put(0x2090,0x2100)
            fighters=[{'identity':'fighter','address':0x1000,'type':'Fighter'}]
            rows,_=capture_fighter_dynamics(read,fighters,order)
            self.assertEqual(len(rows),2)
            self.assertTrue(all(r['active_union']=='desc.lb_unk0' for r in rows))
            put(0x2190,0x2000)
            with self.assertRaisesRegex(ValueError,'invalid dynamics chain'):
                capture_fighter_dynamics(read,fighters,order)
            put(0x2190,0);put(0x1000+0x2f8,3)
            with self.assertRaisesRegex(ValueError,'short dynamics chain'):
                capture_fighter_dynamics(read,fighters,order)

    def test_shared_joint_graph_and_bound(self):
        memory = {n:bytearray(0x88) for n in (100,200,300)}
        memory[100][16:20] = (300).to_bytes(4,'little')
        memory[200][16:20] = (300).to_bytes(4,'little')
        read = lambda address,size:memory[address][:size]
        rows, ids = capture_joint_graph(read, {'first':100,'second':200}, 'little')
        self.assertEqual(len(rows),3)
        self.assertEqual(ids.resolve(300),{'kind':'object','identity':'first.child'})
        with self.assertRaisesRegex(ValueError,'excessive'):
            capture_joint_graph(read, {'first':100,'second':200}, 'little',limit=2)
        memory[300] = bytearray(4)
        with self.assertRaisesRegex(ValueError,'short'):
            capture_joint_graph(read, {'first':100}, 'little')

    def test_relocation_null_and_unknown(self):
        native, oracle = ObjectIdentities(), ObjectIdentities()
        native.add('fighter', 0x1000)
        oracle.add('fighter', 0x80004000)
        self.assertEqual(compare_pointer(0x1000, 0x80004000, native, oracle)['status'], 'equal')
        self.assertEqual(compare_pointer(0, 0, native, oracle)['status'], 'equal')
        self.assertEqual(compare_pointer(0x1000, 0, native, oracle)['status'], 'different')
        self.assertEqual(compare_pointer(123, 123, native, oracle)['status'], 'unresolved')
        self.assertEqual(compare_pointer(0x1004, 0x80004004, native, oracle)['status'], 'unresolved')
        with self.assertRaises(ValueError):
            native.add('other', 0x1000)
        with self.assertRaises(ValueError):
            native.add('fighter', 0x2000)

    def test_ordered_capture_both_endians_and_corruption(self):
        snapshots = []
        for order, base in [('little', 0x1000), ('big', 0x80001000)]:
            memory = {}
            for index in range(2):
                address = base + index * 0x100
                obj = bytearray(0x38)
                obj[2] = 8
                obj[8:12] = (base + 0x100 if index == 0 else 0).to_bytes(4, order)
                obj[0x2c:0x30] = (address + 0x80).to_bytes(4, order)
                memory[address] = obj
                memory[address + 0x80] = bytes(4)
            read = lambda address, size: memory[address][:size]
            records, identities = capture_entity_lists(read, {8: base}, order, {8: ('Fighter', 4)})
            snapshots.append((records, identities))
            self.assertEqual(len(records), 4)
            memory[base + 0x100][8:12] = base.to_bytes(4, order)
            with self.assertRaisesRegex(ValueError, 'cyclic'):
                capture_entity_lists(read, {8: base}, order, {8: ('Fighter', 4)})
        self.assertEqual(compare_pointer(0x1180, 0x80001180, snapshots[0][1], snapshots[1][1])['status'], 'equal')
        self.assertEqual(compare_pointer(0x1180, 0x80001080, snapshots[0][1], snapshots[1][1])['status'], 'different')


if __name__ == '__main__':
    unittest.main()
