using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.Melee.Gr;

internal static class StageMapHeadSection
{
    public const string Name = "stage.map_head.v2";
    public const uint Schema = 2;
    public const int MapRecordSize = 64;
    public const int GeneralGroupRecordSize = 32;
    public const int GeneralPointRecordSize = 8;
    public const int ModelGroupRecordSize = 64;
    public const int CollisionLinkRecordSize = 8;
    public const int JobjLinkRecordSize = 2;
    private const int HeaderSize = 96;

    public static StageMapHeadAsset Read(
        string path,
        string rootName,
        HSDRawFile archive,
        SBM_Map_Head source)
    {
        int declaredModelGroups = source._s.GetInt32(0x0C);
        SBM_Map_GOBJ[] modelSources =
            DatStructRange.ReadCountedArray<SBM_Map_GOBJ>(
                archive, source.ModelGroups, declaredModelGroups,
                $"{path}:{rootName}.model_groups");
        StageModelGroup[] modelGroups = modelSources
            .Select((group, index) => ReadModelGroup(path, rootName, index, group))
            .ToArray();
        HSD_JOBJ?[] modelRoots = modelSources
            .Select(group => group.RootNode)
            .ToArray();

        int declaredGeneralGroups = source._s.GetInt32(0x04);
        SBM_GeneralPoints[] generalSources =
            DatStructRange.ReadCountedArray<SBM_GeneralPoints>(
                archive, source.GeneralPoints, declaredGeneralGroups,
                $"{path}:{rootName}.general_points");
        StageGeneralPointGroup[] generalGroups = generalSources
            .Select((group, index) =>
            {
                HSD_JOBJ? root = group.JOBJReference;
                int linkedModelGroup = Array.FindIndex(modelRoots,
                    candidate => candidate is not null && root is not null &&
                        ReferenceEquals(candidate._s, root._s));
                return new StageGeneralPointGroup(
                    GeneralTreeName(rootName, index),
                    root,
                    linkedModelGroup,
                    (group.Points ?? []).Select(point => new StageGeneralPoint(
                        point.JOBJIndex,
                        checked((short)point.Type))).ToArray());
            })
            .ToArray();

        return new StageMapHeadAsset(
            path,
            rootName,
            source.Splines?.Length ?? 0,
            source.Lights?.Length ?? 0,
            source.SplineDesc?.Length ?? 0,
            source.MOBJs?.Length ?? 0,
            generalGroups,
            modelGroups);
    }

    public static string GeneralTreeName(string rootName, int index) =>
        $"{rootName}.general_points[{index}].jobj";

    public static string ModelTreeName(string rootName, int index) =>
        $"{rootName}.model_groups[{index}].jobj";

    public static byte[] Build(IReadOnlyList<StageMapHeadAsset> maps)
    {
        int generalGroupCount = maps.Sum(map => map.GeneralGroups.Length);
        int generalPointCount = maps.Sum(map =>
            map.GeneralGroups.Sum(group => group.Points.Length));
        int modelGroupCount = maps.Sum(map => map.ModelGroups.Length);
        int collisionLinkCount = maps.Sum(map => map.ModelGroups.Sum(group =>
            group.CollisionLinks.Length));
        int jobjLinkCount = maps.Sum(map => map.ModelGroups.Sum(group =>
            group.JobjLinks.Length));
        int animationFlagCount = maps.Sum(map => map.ModelGroups.Sum(group =>
            group.AnimationFlags.Length));

        int mapsOffset = HeaderSize;
        int generalGroupsOffset = Align8(checked(
            mapsOffset + maps.Count * MapRecordSize));
        int generalPointsOffset = Align8(checked(
            generalGroupsOffset + generalGroupCount * GeneralGroupRecordSize));
        int modelGroupsOffset = Align8(checked(
            generalPointsOffset + generalPointCount * GeneralPointRecordSize));
        int collisionLinksOffset = Align8(checked(
            modelGroupsOffset + modelGroupCount * ModelGroupRecordSize));
        int jobjLinksOffset = Align8(checked(
            collisionLinksOffset + collisionLinkCount * CollisionLinkRecordSize));
        int animationFlagsOffset = Align8(checked(
            jobjLinksOffset + jobjLinkCount * JobjLinkRecordSize));
        byte[] result = new byte[checked(
            animationFlagsOffset + animationFlagCount)];
        Span<byte> span = result;

        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)maps.Count));
        WriteU32(span, 8, checked((uint)generalGroupCount));
        WriteU32(span, 12, checked((uint)generalPointCount));
        WriteU32(span, 16, checked((uint)modelGroupCount));
        WriteU32(span, 20, checked((uint)collisionLinkCount));
        WriteU32(span, 24, MapRecordSize);
        WriteU32(span, 28, GeneralGroupRecordSize);
        WriteU32(span, 32, GeneralPointRecordSize);
        WriteU32(span, 36, ModelGroupRecordSize);
        WriteU32(span, 40, CollisionLinkRecordSize);
        WriteU32(span, 44, checked((uint)jobjLinkCount));
        WriteU64(span, 48, checked((ulong)mapsOffset));
        WriteU64(span, 56, checked((ulong)generalGroupsOffset));
        WriteU64(span, 64, checked((ulong)generalPointsOffset));
        WriteU64(span, 72, checked((ulong)modelGroupsOffset));
        WriteU64(span, 80, checked((ulong)collisionLinksOffset));
        WriteU64(span, 88, checked((ulong)jobjLinksOffset));

        int generalGroupIndex = 0;
        int generalPointIndex = 0;
        int modelGroupIndex = 0;
        int collisionLinkIndex = 0;
        int jobjLinkIndex = 0;
        int animationFlagIndex = 0;
        for (int mapIndex = 0; mapIndex < maps.Count; ++mapIndex)
        {
            StageMapHeadAsset map = maps[mapIndex];
            int mapRecord = mapsOffset + mapIndex * MapRecordSize;
            WriteU64(span, mapRecord, StableNameHash(map.Path));
            WriteU64(span, mapRecord + 8, StableNameHash(map.RootName));
            WriteU32(span, mapRecord + 16, checked((uint)generalGroupIndex));
            WriteU32(span, mapRecord + 20, checked((uint)map.GeneralGroups.Length));
            WriteU32(span, mapRecord + 24, checked((uint)modelGroupIndex));
            WriteU32(span, mapRecord + 28, checked((uint)map.ModelGroups.Length));
            WriteU32(span, mapRecord + 32, checked((uint)map.SplineCount));
            WriteU32(span, mapRecord + 36, checked((uint)map.LightCount));
            WriteU32(span, mapRecord + 40, checked((uint)map.SplineDescCount));
            WriteU32(span, mapRecord + 44, checked((uint)map.MobjCount));

            foreach (StageGeneralPointGroup group in map.GeneralGroups)
            {
                int groupRecord = generalGroupsOffset +
                    generalGroupIndex++ * GeneralGroupRecordSize;
                WriteU64(span, groupRecord, StableNameHash(group.TreeName));
                WriteU32(span, groupRecord + 8, checked((uint)generalPointIndex));
                WriteU32(span, groupRecord + 12, checked((uint)group.Points.Length));
                WriteU32(span, groupRecord + 16, group.RootNode is null ? 0U : 1U);
                WriteI32(span, groupRecord + 20, group.LinkedModelGroup);
                foreach (StageGeneralPoint point in group.Points)
                {
                    int pointRecord = generalPointsOffset +
                        generalPointIndex++ * GeneralPointRecordSize;
                    WriteI16(span, pointRecord, point.JobjIndex);
                    WriteI16(span, pointRecord + 2, point.Type);
                }
            }

            foreach (StageModelGroup group in map.ModelGroups)
            {
                int groupRecord = modelGroupsOffset +
                    modelGroupIndex++ * ModelGroupRecordSize;
                int firstCollisionLink = collisionLinkIndex;
                foreach (StageMapCollisionLink link in group.CollisionLinks)
                    WriteCollisionLink(span, collisionLinksOffset,
                        ref collisionLinkIndex, link);
                int firstJobjLink = jobjLinkIndex;
                foreach (short link in group.JobjLinks)
                {
                    WriteI16(span, jobjLinksOffset +
                        jobjLinkIndex++ * JobjLinkRecordSize, link);
                }

                WriteU64(span, groupRecord, StableNameHash(group.TreeName));
                WriteU32(span, groupRecord + 8, checked((uint)group.JointAnimations.Length));
                WriteU32(span, groupRecord + 12, checked((uint)group.MaterialAnimationCount));
                WriteU32(span, groupRecord + 16, checked((uint)group.ShapeAnimationCount));
                WriteU32(span, groupRecord + 20, checked((uint)group.LightCount));
                WriteU32(span, groupRecord + 24, checked((uint)firstCollisionLink));
                WriteU32(span, groupRecord + 28, checked((uint)group.CollisionLinks.Length));
                WriteU32(span, groupRecord + 32, checked((uint)firstJobjLink));
                WriteU32(span, groupRecord + 36, checked((uint)group.JobjLinks.Length));
                WriteU32(span, groupRecord + 40, group.PresenceFlags);
                WriteU64(span, groupRecord + 48, checked((ulong)(
                    animationFlagsOffset + animationFlagIndex)));
                WriteU32(span, groupRecord + 56,
                    checked((uint)group.AnimationFlags.Length));
                group.AnimationFlags.CopyTo(span[
                    (animationFlagsOffset + animationFlagIndex)..]);
                animationFlagIndex += group.AnimationFlags.Length;
            }
        }
        if (generalGroupIndex != generalGroupCount ||
            generalPointIndex != generalPointCount ||
            modelGroupIndex != modelGroupCount ||
            collisionLinkIndex != collisionLinkCount ||
            jobjLinkIndex != jobjLinkCount ||
            animationFlagIndex != animationFlagCount)
            throw new InvalidDataException("stage map-head layout mismatch");
        return result;
    }

    private static StageModelGroup ReadModelGroup(
        string path,
        string rootName,
        int index,
        SBM_Map_GOBJ source)
    {
        SBM_Map_GOBJ_CollisionLink[] links = ReadCollisionLinks(
            source.CollisionLinks, source.CollisionLinkCount,
            path, rootName, index, "primary");
        short[] jobjLinks = ReadJobjLinks(
            source.JOBJLinks, source.JOBJLinkCount,
            path, rootName, index);
        uint presence = 0;
        if (source.RootNode is not null) presence |= 1U << 0;
        if (source.Camera is not null) presence |= 1U << 1;
        if (source.Fog is not null) presence |= 1U << 2;
        if (source._s.References.ContainsKey(0x14)) presence |= 1U << 3;
        if (source._s.References.ContainsKey(0x28)) presence |= 1U << 4;
        int animationFlagCount = Math.Max(
            source.JointAnimations?.Length ?? 0,
            Math.Max(source.MaterialAnimations?.Length ?? 0,
                source.ShapeAnimations?.Length ?? 0));
        byte[] animationFlags = [];
        if (animationFlagCount != 0)
        {
            byte[] rawFlags = source._s
                .GetReference<HSDAccessor>(0x28)?._s.GetData() ?? [];
            if (rawFlags.Length < animationFlagCount)
                throw new InvalidDataException(
                    $"invalid map animation-flag range in " +
                    $"'{path}:{rootName}[{index}]'");
            animationFlags = rawFlags.AsSpan(0, animationFlagCount).ToArray();
        }
        return new StageModelGroup(
            ModelTreeName(rootName, index),
            source.RootNode,
            ReadPointerArray(source.JointAnimations),
            source.MaterialAnimations?.Length ?? 0,
            source.ShapeAnimations?.Length ?? 0,
            source.Lights?.Length ?? 0,
            presence,
            links.Select(ReadCollisionLink).ToArray(),
            jobjLinks,
            animationFlags);
    }

    private static short[] ReadJobjLinks(
        HSDShortArray? source,
        int count,
        string path,
        string rootName,
        int groupIndex)
    {
        if (count < 0 || (count != 0 && source is null) ||
            (source is not null && count > source.Length))
            throw new InvalidDataException(
                $"invalid map JOBJ-link range in " +
                $"'{path}:{rootName}[{groupIndex}]'");
        if (count == 0) return [];
        return source!.Array.AsSpan(0, count).ToArray();
    }

    private static HSD_AnimJoint?[] ReadPointerArray(
        HSDNullPointerArrayAccessor<HSD_AnimJoint>? source)
    {
        if (source is null) return [];
        HSD_AnimJoint?[] result = new HSD_AnimJoint?[source.Length];
        for (int index = 0; index < result.Length; ++index)
            result[index] = source[index];
        return result;
    }

    private static SBM_Map_GOBJ_CollisionLink[] ReadCollisionLinks(
        HSDArrayAccessor<SBM_Map_GOBJ_CollisionLink>? source,
        int count,
        string path,
        string rootName,
        int groupIndex,
        string kind)
    {
        if (count < 0 || (count != 0 && source is null) ||
            (source is not null && count > source.Length))
            throw new InvalidDataException(
                $"invalid {kind} map collision-link range in " +
                $"'{path}:{rootName}[{groupIndex}]'");
        if (count == 0) return [];
        SBM_Map_GOBJ_CollisionLink[] result = new SBM_Map_GOBJ_CollisionLink[count];
        for (int link = 0; link < count; ++link)
            result[link] = source![link];
        return result;
    }

    private static StageMapCollisionLink ReadCollisionLink(
        SBM_Map_GOBJ_CollisionLink source) =>
        new(source.CollisionIndex, source.UnknownIndex, source.JOBJIndex);

    private static void WriteCollisionLink(
        Span<byte> bytes,
        int baseOffset,
        ref int index,
        StageMapCollisionLink link)
    {
        int offset = baseOffset + index++ * CollisionLinkRecordSize;
        WriteI16(bytes, offset, link.CollisionIndex);
        WriteI16(bytes, offset + 2, link.UnknownIndex);
        WriteI16(bytes, offset + 4, link.JobjIndex);
    }

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
    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record StageMapHeadAsset(
    string Path,
    string RootName,
    int SplineCount,
    int LightCount,
    int SplineDescCount,
    int MobjCount,
    StageGeneralPointGroup[] GeneralGroups,
    StageModelGroup[] ModelGroups);

internal sealed record StageGeneralPointGroup(
    string TreeName,
    HSD_JOBJ? RootNode,
    int LinkedModelGroup,
    StageGeneralPoint[] Points);

internal readonly record struct StageGeneralPoint(short JobjIndex, short Type);

internal sealed record StageModelGroup(
    string TreeName,
    HSD_JOBJ? RootNode,
    HSD_AnimJoint?[] JointAnimations,
    int MaterialAnimationCount,
    int ShapeAnimationCount,
    int LightCount,
    uint PresenceFlags,
    StageMapCollisionLink[] CollisionLinks,
    short[] JobjLinks,
    byte[] AnimationFlags);

internal readonly record struct StageMapCollisionLink(
    short CollisionIndex,
    short UnknownIndex,
    short JobjIndex);
