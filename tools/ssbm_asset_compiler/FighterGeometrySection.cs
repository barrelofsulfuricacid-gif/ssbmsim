using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Melee.Pl;

internal static class FighterGeometrySection
{
    public const string Name = "fighter.geometry.v1";
    public const uint Schema = 1;
    public const int FighterRecordSize = 256;
    public const int HurtboxRecordSize = 40;
    public const int CoinRecordSize = 20;
    private const int HeaderSize = 48;

    private const uint HasHurtboxes = 1U << 0;
    private const uint HasCenterBubble = 1U << 1;
    private const uint HasCoinSpheres = 1U << 2;
    private const uint HasCameraBox = 1U << 3;
    private const uint HasItemPickup = 1U << 4;
    private const uint HasEnvironmentCollision = 1U << 5;
    private const uint HasJostleBox = 1U << 6;
    private const uint HasBoneIds = 1U << 7;
    private const uint HasIk = 1U << 8;
    private const uint HasModelBones = 1U << 9;

    public static FighterGeometryAsset Read(
        string path,
        string rootName,
        SBM_FighterData fighter)
    {
        SBM_Hurtbox[] hurtboxes = fighter.Hurtboxes?.Hurtboxes ?? [];
        SBM_Pl_CoinCollisionSphere[] coins =
            fighter.CoinCollisionSpheres?.Array ?? [];
        uint presence = 0;
        if (fighter.Hurtboxes is not null) presence |= HasHurtboxes;
        if (fighter.CenterBubble is not null) presence |= HasCenterBubble;
        if (fighter.CoinCollisionSpheres is not null) presence |= HasCoinSpheres;
        if (fighter.CameraBox is not null) presence |= HasCameraBox;
        if (fighter.ItemPickupParams is not null) presence |= HasItemPickup;
        if (fighter.EnvironmentCollision is not null) presence |= HasEnvironmentCollision;
        if (fighter.JostleBox is not null) presence |= HasJostleBox;
        if (fighter.FighterBoneTable is not null) presence |= HasBoneIds;
        if (fighter.FighterIK is not null) presence |= HasIk;
        if (fighter.ModelLookupTables is not null) presence |= HasModelBones;
        return new FighterGeometryAsset(
            path,
            rootName,
            presence,
            hurtboxes.Select(ReadHurtbox).ToArray(),
            coins.Select(ReadCoin).ToArray(),
            fighter.CenterBubble is null ? default : new CenterBubble(
                fighter.CenterBubble.BoneIndex,
                Bits(fighter.CenterBubble.Size)),
            fighter.JostleBox is null ? default : new JostleBox(
                Bits(fighter.JostleBox.Offset),
                Bits(fighter.JostleBox.Size)),
            ReadEnvironment(fighter.EnvironmentCollision),
            ReadCamera(fighter.CameraBox),
            ReadPickup(fighter.ItemPickupParams),
            ReadBoneIds(fighter.FighterBoneTable),
            ReadModelBones(fighter.ModelLookupTables),
            ReadIk(fighter.FighterIK));
    }

    public static byte[] Build(IReadOnlyList<FighterGeometryAsset> fighters)
    {
        int fighterOffset = HeaderSize;
        int hurtboxOffset = Align8(checked(
            fighterOffset + fighters.Count * FighterRecordSize));
        int hurtboxCount = fighters.Sum(fighter => fighter.Hurtboxes.Length);
        int coinOffset = Align8(checked(
            hurtboxOffset + hurtboxCount * HurtboxRecordSize));
        int coinCount = fighters.Sum(fighter => fighter.Coins.Length);
        byte[] result = new byte[checked(
            coinOffset + coinCount * CoinRecordSize)];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)fighters.Count));
        WriteU32(span, 8, FighterRecordSize);
        WriteU32(span, 12, HurtboxRecordSize);
        WriteU32(span, 16, CoinRecordSize);
        WriteU64(span, 24, checked((ulong)fighterOffset));
        WriteU64(span, 32, checked((ulong)hurtboxOffset));
        WriteU64(span, 40, checked((ulong)coinOffset));

        int hurtboxIndex = 0;
        int coinIndex = 0;
        for (int fighterIndex = 0; fighterIndex < fighters.Count; ++fighterIndex)
        {
            FighterGeometryAsset fighter = fighters[fighterIndex];
            int record = fighterOffset + fighterIndex * FighterRecordSize;
            WriteU64(span, record, StableNameHash(fighter.Path));
            WriteU64(span, record + 8, StableNameHash(fighter.RootName));
            WriteU32(span, record + 16, fighter.Presence);
            WriteU32(span, record + 20, checked((uint)fighter.Hurtboxes.Length));
            WriteU64(span, record + 24, checked((ulong)(
                hurtboxOffset + hurtboxIndex * HurtboxRecordSize)));
            WriteU32(span, record + 32, checked((uint)fighter.Coins.Length));
            WriteU64(span, record + 40, checked((ulong)(
                coinOffset + coinIndex * CoinRecordSize)));
            WriteI32(span, record + 48, fighter.Center.BoneIndex);
            WriteU32(span, record + 52, fighter.Center.SizeBits);
            WriteU32(span, record + 56, fighter.Jostle.OffsetBits);
            WriteU32(span, record + 60, fighter.Jostle.SizeBits);
            WriteEnvironment(span, record + 64, fighter.Environment);
            WriteWords(span, record + 92, fighter.Camera.Words);
            WriteWords(span, record + 116, fighter.Pickup.Words);
            WriteInts(span, record + 164, fighter.BoneIds.Values);
            fighter.ModelBones.Values.CopyTo(span[(record + 184)..]);
            WriteIk(span, record + 192, fighter.Ik);

            foreach (Hurtbox hurtbox in fighter.Hurtboxes)
            {
                int offset = hurtboxOffset + hurtboxIndex++ * HurtboxRecordSize;
                WriteI32(span, offset, hurtbox.BoneIndex);
                WriteI32(span, offset + 4, hurtbox.Type);
                WriteI32(span, offset + 8, hurtbox.Grabbable);
                WriteWords(span, offset + 12, hurtbox.Words);
            }
            foreach (CoinSphere coin in fighter.Coins)
            {
                int offset = coinOffset + coinIndex++ * CoinRecordSize;
                WriteI32(span, offset, coin.BoneIndex);
                WriteWords(span, offset + 4, coin.Words);
            }
        }
        if (hurtboxIndex != hurtboxCount || coinIndex != coinCount)
        {
            throw new InvalidDataException("fighter geometry layout mismatch");
        }
        return result;
    }

    private static Hurtbox ReadHurtbox(SBM_Hurtbox value) => new(
        value.BoneIndex,
        (int)value.Type,
        value.Grabbable,
        [Bits(value.X1), Bits(value.Y1), Bits(value.Z1),
         Bits(value.X2), Bits(value.Y2), Bits(value.Z2), Bits(value.Size)]);

    private static CoinSphere ReadCoin(SBM_Pl_CoinCollisionSphere value) => new(
        value.BoneIndex,
        [Bits(value.XOffset), Bits(value.YOffset), Bits(value.ZOffset), Bits(value.Size)]);

    private static EnvironmentCollision ReadEnvironment(SBM_EnvironmentCollision? value) =>
        value is null ? new() : new(
            [value.ECBBone1, value.ECBBone2, value.ECBBone3,
             value.ECBBone4, value.ECBBone5, value.ECBBone6],
            [Bits(value.Multiplier), Bits(value.LedgeGrabWidth),
             Bits(value.LedgeGrabYOffset), Bits(value.LedgeGrabHeight)]);

    private static FloatWords ReadCamera(SBM_PlCameraBox? value) =>
        value is null ? new([]) : new([
            Bits(value.YOffset), Bits(value.ProjRight), Bits(value.ProjLeft),
            Bits(value.ProjTop), Bits(value.ProjBottom), Bits(value.x50_of_camera_box)]);

    private static FloatWords ReadPickup(SBM_PlItemPickupParam? value) =>
        value is null ? new([]) : new([
            Bits(value.LightGroundedXOffset), Bits(value.LightGroundedYOffset),
            Bits(value.LightGroundedXRange), Bits(value.LightGroundedYRange),
            Bits(value.HeavyXOffset), Bits(value.HeavyYOffset),
            Bits(value.HeavyXRange), Bits(value.HeavyYRange),
            Bits(value.LightAerialXOffset), Bits(value.LightAerialYOffset),
            Bits(value.LightAerialXRange), Bits(value.LightAerialYRange)]);

    private static IntWords ReadBoneIds(SBM_FighterBoneIDs? value) =>
        value is null ? new([]) : new([
            value.HeadBone, value.RightArm, value.LeftLeg,
            value.RightLeg, value.LeftArm]);

    private static ByteWords ReadModelBones(SBM_PlayerModelLookupTables? value) =>
        value is null ? new([]) : new([
            value.ItemHoldBone, value.ShieldBone, value.TopOfHeadBone,
            value.LeftFootBone, value.RightFootBone]);

    private static FighterIk ReadIk(SBM_FighterIK? value) =>
        value is null ? new() : new(
            [value.RLegJ, value.LLegJ, value.RKneeJ, value.LKneeJ,
             value.RFootJ, value.LFootJ, value.RShoulderJ, value.LShoulderJ,
             value.RArmJ, value.LArmJ],
            [Bits(value.LegParam), Bits(value.KneeParam), Bits(value.FootParam1),
             Bits(value.FootParam2), Bits(value.ShoulderParam), Bits(value.ArmParam),
             Bits(value.UnkParam1), Bits(value.UnkParam2)]);

    private static void WriteEnvironment(
        Span<byte> bytes,
        int offset,
        EnvironmentCollision value)
    {
        for (int index = 0; index < value.Bones.Length; ++index)
            WriteI16(bytes, offset + index * 2, value.Bones[index]);
        WriteWords(bytes, offset + 12, value.Words);
    }

    private static void WriteIk(Span<byte> bytes, int offset, FighterIk value)
    {
        if (value.Joints.Length == 0 || value.Words.Length == 0) return;
        bytes[offset] = value.Joints[0];
        bytes[offset + 1] = value.Joints[1];
        WriteU32(bytes, offset + 4, value.Words[0]);
        bytes[offset + 8] = value.Joints[2];
        bytes[offset + 9] = value.Joints[3];
        WriteU32(bytes, offset + 12, value.Words[1]);
        bytes[offset + 16] = value.Joints[4];
        bytes[offset + 17] = value.Joints[5];
        WriteU32(bytes, offset + 20, value.Words[2]);
        WriteU32(bytes, offset + 24, value.Words[3]);
        bytes[offset + 28] = value.Joints[6];
        bytes[offset + 29] = value.Joints[7];
        WriteU32(bytes, offset + 32, value.Words[4]);
        bytes[offset + 36] = value.Joints[8];
        bytes[offset + 37] = value.Joints[9];
        WriteU32(bytes, offset + 40, value.Words[5]);
        WriteU32(bytes, offset + 44, value.Words[6]);
        WriteU32(bytes, offset + 48, value.Words[7]);
    }

    private static void WriteWords(Span<byte> bytes, int offset, uint[] words)
    {
        for (int index = 0; index < words.Length; ++index)
            WriteU32(bytes, offset + index * 4, words[index]);
    }

    private static void WriteInts(Span<byte> bytes, int offset, int[] words)
    {
        for (int index = 0; index < words.Length; ++index)
            WriteI32(bytes, offset + index * 4, words[index]);
    }

    private static uint Bits(float value) => BitConverter.SingleToUInt32Bits(value);
    private static int Align8(int value) => checked((value + 7) & ~7);
    private static ulong StableNameHash(string value)
    {
        ulong hash = 14695981039346656037UL;
        foreach (byte item in Encoding.UTF8.GetBytes(value))
        {
            hash ^= item;
            hash *= 1099511628211UL;
        }
        return hash;
    }
    private static void WriteI16(Span<byte> bytes, int offset, short value) =>
        BinaryPrimitives.WriteInt16LittleEndian(bytes[offset..], value);
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record FighterGeometryAsset(
    string Path,
    string RootName,
    uint Presence,
    Hurtbox[] Hurtboxes,
    CoinSphere[] Coins,
    CenterBubble Center,
    JostleBox Jostle,
    EnvironmentCollision Environment,
    FloatWords Camera,
    FloatWords Pickup,
    IntWords BoneIds,
    ByteWords ModelBones,
    FighterIk Ik);
internal sealed record Hurtbox(int BoneIndex, int Type, int Grabbable, uint[] Words);
internal sealed record CoinSphere(int BoneIndex, uint[] Words);
internal readonly record struct CenterBubble(int BoneIndex, uint SizeBits);
internal readonly record struct JostleBox(uint OffsetBits, uint SizeBits);
internal sealed record EnvironmentCollision(short[] Bones, uint[] Words)
{
    public EnvironmentCollision() : this([], []) { }
}
internal sealed record FloatWords(uint[] Words);
internal sealed record IntWords(int[] Values);
internal sealed record ByteWords(byte[] Values);
internal sealed record FighterIk(byte[] Joints, uint[] Words)
{
    public FighterIk() : this([], []) { }
}
