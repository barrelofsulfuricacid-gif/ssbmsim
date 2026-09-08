import os
"""Native viewport state: jitter ordering, exact storage, and reset isolation."""
import subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class ViewportTests(unittest.TestCase):
 def test_state_and_reset(self):
  code=r'''
#include <dolphin/gx/GXTransform.h>
#include <stdint.h>
#include <string.h>
void pf_gx_viewport_reset(void);
void GXGetViewportv(f32*);
void GXGetProjectionv(f32*);
int main(void){float out[6],expected[6];
 /* Reconstruct the matrix as fog.c does, then compare its action on vectors.
  * Distinct off-axis entries detect perspective/orthographic column swaps. */
 for(int type=0;type<2;type++)for(int k=-1000;k<=1000;k++){
  float m[4][4]={{1.25f,0,0.125f,-0.25f},{0,2.5f,-0.375f,0.5f},
                 {0,0,-1.5f,-2.0f},{0,0,0,0}};
  float p[7],rebuilt[4][4]={{0}},v[4]={k*0.125f,0.75f,-3.0f,1.0f};
  int col=type?3:2;m[0][type?2:3]=0;m[1][type?2:3]=0;
  m[3][col]=type?1.0f:-1.0f;
  GXSetProjection(m,(GXProjectionType)type);GXGetProjectionv(p);
  if(p[0]!=(float)type)return 4;
  rebuilt[0][0]=p[1];rebuilt[0][col]=p[2];
  rebuilt[1][1]=p[3];rebuilt[1][col]=p[4];
  rebuilt[2][2]=p[5];rebuilt[2][3]=p[6];rebuilt[3][col]=type?1.0f:-1.0f;
  for(int row=0;row<4;row++){
   float a=0,b=0;for(int c=0;c<4;c++){a+=m[row][c]*v[c];b+=rebuilt[row][c]*v[c];}
   if(memcmp(&a,&b,sizeof(a)))return 5;
  }
  pf_gx_viewport_reset();GXGetProjectionv(p);
  for(int i=0;i<7;i++)if(p[i]!=0.0f)return 6;
 }
 for(unsigned f=0;f<4;f++)for(int k=-1000;k<=1000;k++){
  float top=k*0.125f;
  float e[6]={-0.0f,f==0?top-0.5f:top,640.0f,480.0f,-0.0f,1.0f};
  GXSetViewportJitter(-0.0f,top,640.0f,480.0f,-0.0f,1.0f,f);
  GXGetViewportv(out);if(memcmp(out,e,sizeof(out)))return 1;
  GXSetViewport(-0.0f,top,640.0f,480.0f,-0.0f,1.0f);
  e[1]=top;GXGetViewportv(out);if(memcmp(out,e,sizeof(out)))return 2;
  pf_gx_viewport_reset();memset(expected,0,sizeof(expected));GXGetViewportv(out);
  if(memcmp(out,expected,sizeof(out)))return 3;
 }
 return 0;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   c=Path(tmp)/'viewport.c';exe=Path(tmp)/'viewport';c.write_text(code)
   subprocess.run(['cc','-O2','-DTARGET_PC','-Werror=implicit-function-declaration','-fno-fast-math','-ffp-contract=off','-fsanitize=address,undefined','-I',str(ROOT/'src/ssbm/native_compat'),'-I',str(Path(os.environ['PF_AURORA_SOURCE_DIR'])/'include'),str(c),str(ROOT/'src/ssbm/native_compat/native_gx_viewport.c'),'-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
