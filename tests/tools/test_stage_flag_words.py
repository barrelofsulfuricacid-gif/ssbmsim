import os
"""Conformance checks for normalized native stage flag words."""
from pathlib import Path
import json,subprocess,tempfile

def main():
    r=Path(__file__).resolve().parents[2];d=json.loads((r/'tools/host_adaptations/gr_types.json').read_text());stage=d['replacements'][0];shadow=d['replacements'][1];ground=json.loads((r/'tools/host_adaptations/ground.json').read_text());light=ground['replacements'][-1]
    code='''#include <stdint.h>
    #include <stddef.h>
    #include <string.h>
    #include <assert.h>
    #include <stdio.h>
    typedef uint8_t u8;typedef uint32_t u32;
    typedef void HSD_LightDesc;typedef void HSD_LightAnim;typedef void Ground_GObj;
    typedef void (*HSD_GObjEvent)(void);typedef int (*HSD_GObjPredicate)(void);
    '''+stage['old'].replace('StageCallbacks','OriginalCallbacks')+stage['new']+shadow['new']+light['new']+'''
    #if __SIZEOF_POINTER__ == 4
    _Static_assert(sizeof(StageCallbacks)==20,"callback ABI");
    _Static_assert(sizeof(struct GroundShadowEntry)==8,"shadow ABI");
    _Static_assert(sizeof(LightOverrideEntry)==8,"light ABI");
    #endif
    int main(void){
    OriginalCallbacks old={0};old.flags=0xC0000000;assert(old.flags_b0==0);
    StageCallbacks s={0};struct GroundShadowEntry shadow={0};LightOverrideEntry light={0};
    for(unsigned v=0;v<256;v++){unsigned word=(v<<24)|((v*65793u)&0xffffff),out;
    '''
    for i in range(8):
     mask=1<<(31-i);code+=f's.flags=word;assert(s.flags_b{i}==((word>>{31-i})&1));s.flags_b{i}=1;assert(s.flags==(word|{mask}u));s.flags_b{i}=0;assert(s.flags==(word&~{mask}u));\n'
    for obj,field,bit in [('shadow','flag',31),('light','a',31),('light','b',30),('light','c',29)]:
     mask=1<<bit;code+=f'memcpy((char*)&{obj}+sizeof(void*),&word,4);assert({obj}.{field}==((word>>{bit})&1));{obj}.{field}=1;memcpy(&out,(char*)&{obj}+sizeof(void*),4);assert(out==(word|{mask}u));{obj}.{field}=0;memcpy(&out,(char*)&{obj}+sizeof(void*),4);assert(out==(word&~{mask}u));\n'
    code+='}puts("stage-flag-word-tests=pass 256 words x 12 fields read/set/clear");return 0;}'
    with tempfile.TemporaryDirectory() as t:
     p=Path(t);(p/'test.c').write_text(code)
     subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True);subprocess.run([str(p/'test')],check=True)
     c=json.loads((r/'tools/ssbm_native_source_readiness.json').read_text())['compiler'];args=[a.replace('SSBM_I686_SYSROOT',os.environ['PF_SSBM_I686_SYSROOT']) for a in c['target_arguments']];subprocess.run([c['name'],*args,'-fsyntax-only',str(p/'test.c')],check=True)

if __name__ == "__main__":
    main()
