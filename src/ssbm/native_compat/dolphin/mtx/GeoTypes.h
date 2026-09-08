#ifndef PF_SSBM_NATIVE_DOLPHIN_GEOTYPES_H
#define PF_SSBM_NATIVE_DOLPHIN_GEOTYPES_H

#include <platform.h>

typedef struct {
    f32 x;
    f32 y;
} Vec2, *Vec2Ptr, Point2d, *Point2dPtr;

typedef struct Vec {
    f32 x;
    f32 y;
    f32 z;
} Vec, Vec3, *VecPtr, *Vec3Ptr, Point3d, *Point3dPtr;

typedef struct {
    s8 x;
    s8 y;
    s8 z;
} S8Vec, S8Vec3, *S8VecPtr, *S8Vec3Ptr;

typedef struct {
    u8 x;
    u8 y;
    u8 z;
    u8 w;
} U8Vec4, *U8Vec4Ptr;

typedef struct {
    s16 x;
    s16 y;
    s16 z;
} S16Vec, S16Vec3, *S16VecPtr, *S16Vec3Ptr;

typedef struct {
    int x;
    int y;
} IntVec2, *IntVec2Ptr;

typedef struct {
    s32 x;
    s32 y;
} S32Vec2, *S32Vec2Ptr;

typedef struct {
    int x;
    int y;
    int z;
} IntVec3, *IntVec3Ptr;

typedef struct {
    s32 x;
    s32 y;
    s32 z;
} S32Vec, S32Vec3, *S32VecPtr, *S32Vec3Ptr;

typedef struct {
    f32 x;
    f32 y;
    f32 z;
    f32 w;
} Quaternion, Vec4, *QuaternionPtr, *Vec4Ptr, Qtrn, *QtrnPtr;

typedef f32 Mtx[3][4];
typedef f32 (*MtxPtr)[4];
typedef f32 ROMtx[4][3];
typedef f32 (*ROMtxPtr)[3];
typedef f32 Mtx44[4][4];
typedef f32 (*Mtx44Ptr)[4];

#endif
