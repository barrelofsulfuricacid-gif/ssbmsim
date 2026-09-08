"""Exhaust raw-byte aliases of the production shared flag adaptation."""
import json,re,subprocess,tempfile
from pathlib import Path
def main():
 root=Path(__file__).resolve().parents[2]
 doc=json.loads((root/'tools/host_adaptations/gm_types.json').read_text())
 entry=next(x for x in doc['replacements'] if x['old'].startswith('typedef union UnkFlagStruct'))
 code='#include <stdint.h>\n#include <assert.h>\ntypedef uint8_t u8;\n'+entry['new']+'\nint main(void){_Static_assert(sizeof(UnkFlagStruct)==1,"size");UnkFlagStruct f;for(unsigned v=0;v<256;v++){'
 for bit in range(8):
  mask=1<<(7-bit)
  code+=f'f.u8=v;assert(f.b{bit}==((v>>{7-bit})&1));f.b{bit}=1;assert(f.u8==(v|{mask}));f.b{bit}=0;assert(f.u8==(v&~{mask}));'
 code+='}return 0;}'
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'test.c').write_text(code)
  subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True)
 print('PASS: 256 byte values, all eight read/set/clear aliases, one-byte ABI')
if __name__=='__main__':main()
