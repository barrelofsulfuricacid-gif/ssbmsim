"""New source-declared character article graph fields require extractor review."""
import os
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ArticleAuxiliaryInventoryTests(unittest.TestCase):
    def test_source_joint_fields_have_explicit_file_slot_schemas(self):
        source = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:
            self.skipTest('PF_SSBM_DECOMP_SOURCE_DIR required for original-source inventory')
        item = Path(source)/'src/melee/it'
        found = {}
        for path in (item/'itCharItems.h', item/'itYoyo.h'):
            for body, name in re.findall(r'typedef\s+struct(?:\s+\w+)?\s*\{(.*?)\}\s*(\w+)\s*;', path.read_text(), re.S):
                if 'Attr' not in name: continue
                fields = re.findall(r'(HSD_(?:Joint|AnimJoint|MatAnimJoint|ShapeAnimJoint))\s*(\*+)\s*(x[0-9A-Fa-f]+)\w*', body)
                if fields: found[name] = fields
        registration = {
            'itClimbersStringAttributes': [('PlPp.dat', 2)],
            'itLinkHookshotAttributes': [('PlLk.dat', 2), ('PlCl.dat', 2)],
            'itLinkBoomerangAttributes': [('PlLk.dat', 1), ('PlCl.dat', 1)],
            'itLinkArrowAttributes': [('PlLk.dat', 3), ('PlCl.dat', 3)],
            'itSamusGrappleAttributes': [('PlSs.dat', 3)],
            'itSeakChain_Attrs': [('PlSk.dat', 3)],
            'itYoyoAttributes': [('PlNs.dat', 10)],
        }
        self.assertEqual(set(found), set(registration), 'new source graph-bearing attribute type needs a schema')
        compiler = (ROOT/'tools/ssbm_asset_compiler/ArticleAuxiliaryGraphs.cs').read_text()
        schemas = {(file, int(slot)): [int(x.strip(),16) for x in offsets.split(',')]
                   for file,slot,offsets in re.findall(r'new\("([^"]+)",\s*(\d+),\s*0x[\dA-Fa-f]+,\s*\[([^]]+)\]',compiler)}
        for name, fields in found.items():
            joints = [int(field[1:],16) for kind,pointers,field in fields if kind=='HSD_Joint']
            for key in registration[name]:
                self.assertEqual(schemas[key], joints, f'{name} source joint offsets must all be discovered')
        # Animation pointer tables and direct material pointers require distinct
        # accessors; a new pointer of either form must not silently become raw.
        animations = {name:[(kind,pointers,int(field[1:],16)) for kind,pointers,field in fields if kind!='HSD_Joint']
                      for name,fields in found.items() if any(kind!='HSD_Joint' for kind,_,_ in fields)}
        self.assertEqual(animations, {
            'itYoyoAttributes': [('HSD_MatAnimJoint','*',0x58)],
            'itSamusGrappleAttributes': [(kind,'**',offset+delta) for offset in range(0x74,0xA5,12)
                for kind,delta in [('HSD_AnimJoint',0),('HSD_MatAnimJoint',4),('HSD_ShapeAnimJoint',8)]]})


if __name__ == '__main__': unittest.main()
