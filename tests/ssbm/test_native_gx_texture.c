#include <assert.h>
#include <stdio.h>

#include <dolphin/gx/GXTexture.h>

int main(void)
{
    assert(GXGetTexBufferSize(80, 60, GX_TF_RGB565, GX_FALSE, 0) == 9600);
    assert(GXGetTexBufferSize(32, 32, GX_TF_IA8, GX_FALSE, 0) == 2048);
    assert(GXGetTexBufferSize(8, 8, GX_TF_RGBA8, GX_FALSE, 0) == 256);
    assert(GXGetTexBufferSize(8, 8, GX_TF_I4, GX_FALSE, 0) == 32);
    assert(GXGetTexBufferSize(8, 8, GX_TF_I4, GX_TRUE, 4) == 128);
    puts("native-gx-texture=pass vectors=5 fountain_bytes=9600");
    return 0;
}
