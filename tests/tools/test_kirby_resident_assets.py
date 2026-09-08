"""Compile the adapted source loaders and check preload/cache ordering contracts."""
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


class KirbyResidentAssetsTests(unittest.TestCase):
    def test_source_loaders_preserve_color_ranges_caches_and_effect_order(self):
        decomp = os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not decomp or not shutil.which('cc'):
            self.skipTest('requires cc and PF_SSBM_DECOMP_SOURCE_DIR')
        spec = json.loads((ROOT / 'tools/host_adaptations/ftkirby.json').read_text())
        adapted = apply_adaptation((Path(decomp) / spec['source_path']).read_bytes(), spec).decode()
        functions = []
        for name in ('ftKb_SpecialN_800EEC34', 'ftKb_SpecialN_800EED50'):
            start = adapted.index('void ' + name + '(')
            functions.append(adapted[start:adapted.index('\n}', start) + 2])
        code = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
typedef int s32;
typedef void HSD_Archive;
typedef struct { void *joint, *matanim; } ftKirby_CostumeArchive;
typedef struct { const char *dat_filename, *joint_name, *matanim_joint_name; } Fighter_CostumeStrings;
struct { const char *filename, *name; } ftKb_Init_803CA9D0[33];
Fighter_CostumeStrings *ftKb_Init_803CB3E8[33];
ftKirby_CostumeArchive *ftKb_Init_803C9FC8[33];
char ftKb_Init_803CB46C[33];
void *ft_80459B88[34];
static int trace[128], trace_count, loads, locale_calls;
static char nodes[8];
static const char *lbFileGetFullName(const char *name) {
    ++locale_calls; return name;
}
static void *pf_ssbm_native_archive_root_require(const char *file, const char *root) {
    assert(file && root);
    int id = root[0] - '0';
    assert(id >= 0 && id < 8);
    trace[trace_count++] = id;
    ++loads;
    return &nodes[id];
}
static void efAsync_LoadAsync(int id) { trace[trace_count++] = 100 + id; }
static void efAsync_LoadSync(int id) { trace[trace_count++] = 200 + id; }
''' + '\n'.join(functions) + r'''
int main(void) {
    Fighter_CostumeStrings colors[3] = {
        {"color0", "1", "2"}, {"color1", "3", NULL}, {"color2", "4", "5"}
    };
    ftKirby_CostumeArchive cache[3] = {{0}};
    ftKb_Init_803CA9D0[7].filename = "copy";
    ftKb_Init_803CA9D0[7].name = "0";
    ftKb_Init_803CB3E8[7] = colors;
    ftKb_Init_803C9FC8[7] = cache;
    ftKb_Init_803CB46C[7] = 9;
    ftKb_SpecialN_800EEC34(7, 0xFF, 3);
    int expected[] = {0,1,2,3,4,5,109};
    assert(trace_count == 7 && !memcmp(trace, expected, sizeof(expected)));
    assert(locale_calls == 4 && ft_80459B88[7] == NULL);
    for (int i = 0; i < 3; ++i) assert(!cache[i].joint && !cache[i].matanim);
    trace_count = 0;
    ftKb_SpecialN_800EEC34(7, 1, 3);
    assert(trace_count == 3 && trace[0] == 0 && trace[1] == 3 && trace[2] == 109);
    trace_count = 0;
    ftKb_SpecialN_800EED50(7, 0);
    assert(trace_count == 4 && trace[0] == 0 && trace[1] == 1 && trace[2] == 2 && trace[3] == 209);
    assert(ft_80459B88[7] == &nodes[0] && !ft_80459B88[6] && !ft_80459B88[8]);
    assert(cache[0].joint == &nodes[1] && cache[0].matanim == &nodes[2]);
    int before = loads;
    trace_count = 0;
    ftKb_SpecialN_800EED50(7, 0);
    assert(loads == before && trace_count == 1 && trace[0] == 209);
    ftKb_SpecialN_800EED50(7, 1);
    assert(cache[1].joint == &nodes[3] && cache[1].matanim == NULL);
    before = trace_count;
    ftKb_SpecialN_800EED50(-1, 0);
    ftKb_SpecialN_800EED50(4, 0);
    assert(trace_count == before);
    ftKb_Init_803CB46C[6] = -1;
    ftKb_SpecialN_800EEC34(6, 0xFF, 3);
    assert(trace_count == before);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kirby-resident-') as tmp:
            tmp = Path(tmp)
            (tmp / 'test.c').write_text(code)
            subprocess.run(['cc', '-O3', '-Wall', '-Wextra', '-Werror',
                            str(tmp / 'test.c'), '-o', str(tmp / 'test')],
                           check=True, capture_output=True)
            subprocess.run([str(tmp / 'test')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
