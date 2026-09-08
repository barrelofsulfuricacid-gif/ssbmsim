"""Compile the source entry callback; guard every countdown and both ownership paths."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from apply_source_adaptation import apply_adaptation

class EntryTests(unittest.TestCase):
    def test_countdown_scale(self):
        source=os.environ.get('PF_SSBM_DECOMP_SOURCE_DIR')
        if not source:self.skipTest('requires pinned source')
        spec=json.loads((ROOT/'tools/host_adaptations/ft_0C31.json').read_text())
        raw=(Path(source)/spec['source_path']).read_bytes()
        adapted=apply_adaptation(raw,spec).decode()
        def body(text):
            start=text.index('void ftCo_EntryStart_Phys(')
            return text[start:text.index('void ftCo_EntryStart_Coll(',start)]
        harness=r'''
#include "native_numeric.h"
#include <stdint.h>
#include <string.h>
typedef struct {float x,y,z;} Vec3;
typedef struct {Vec3 scale;} Joint;
typedef struct Fighter {
 struct {struct {struct {int timer;Vec3 x8,x14;float x24,x28,x20,x4;} entry;} co;} mv;
 int x221F_b4,player_id;Joint *x20A0_accessory;Vec3 cur_pos;} Fighter;
typedef struct {Fighter *user_data;Joint *hsd_obj;} Fighter_GObj;
#define GET_FIGHTER(g) ((g)->user_data)
static Fighter_GObj other;
static Fighter_GObj *Player_GetEntityAtIndex(int port,int sub){(void)port;(void)sub;return &other;}
static void HSD_JObjSetScale(Joint *j,Vec3 *v){j->scale=*v;}
static struct {int x6BC;float x6C4;} common;
#define p_ftCommonData (&common)
static uint8_t profile;
uint8_t pf_ssbm_native_arithmetic_current(void){return profile;}
static uint32_t bits(float x){uint32_t u;memcpy(&u,&x,4);return u;}
''' + body(adapted) + body(raw.decode()).replace('ftCo_EntryStart_Phys','old_entry') + r'''
int main(void){
 int changed=0;Fighter leader={0};leader.cur_pos.y=123;other.user_data=&leader;
 for(profile=0;profile<2;profile++)for(int duration=1;duration<=120;duration++)for(int timer=0;timer<=duration;timer++)for(int variant=0;variant<4;variant++){
  Fighter fp={0};Joint root={0},accessory={0};Fighter_GObj obj={&fp,&root};
  common.x6BC=duration;common.x6C4=variant==0?0.0f:0.01f;
  fp.mv.co.entry.timer=timer;fp.mv.co.entry.x8=(Vec3){2,variant==3?1.13f:1.0f,3};
  fp.mv.co.entry.x14=(Vec3){4,5,6};fp.mv.co.entry.x24=1.2f;fp.mv.co.entry.x20=2.5f;fp.mv.co.entry.x4=17;
  fp.x221F_b4=variant&1;fp.x20A0_accessory=&accessory;
  float fraction=(float)(duration-timer)/duration,delta=fp.mv.co.entry.x8.y-common.x6C4;
  volatile double product=(double)fraction*delta;
  volatile double sum=product+common.x6C4;
  float expected=(float)sum;
  Fighter saved=fp;
  ftCo_EntryStart_Phys(&obj);
  if(bits(root.scale.y)!=bits(expected)||bits(fp.mv.co.entry.x14.y)!=bits(expected)||root.scale.x!=4||root.scale.z!=6)return 1;
  if(fp.x221F_b4){if(fp.cur_pos.y!=123)return 2;}
  else if(bits(accessory.scale.y)!=bits(saved.mv.co.entry.x24*fraction)||bits(fp.cur_pos.y)!=bits(17.0f+2.5f*fraction))return 3;
  fp=saved;old_entry(&obj);changed+=bits(root.scale.y)!=bits(expected);
 }
 return changed?0:4;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'entry.c';exe=Path(tmp)/'entry';c.write_text(harness)
            subprocess.run(['cc','-O2','-fno-fast-math','-ffp-contract=off','-fsanitize=address,undefined',
                            '-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(source)/'extern/dolphin/include'),str(c),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__=='__main__':unittest.main()
