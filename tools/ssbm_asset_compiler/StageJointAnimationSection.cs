using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;

internal static class StageJointAnimationSection
{
    public const string Name = "stage.joint_animations.v1";
    public const uint Schema = 2;
    public const int SetRecordSize = 48;
    public const int NodeRecordSize = 48;
    public const int TrackRecordSize = 40;
    private const int HeaderSize = 80;

    public static StageJointAnimationSet[] Read(
        string path,
        string mapRootName,
        int groupIndex,
        HSD_JOBJ? modelRoot,
        IReadOnlyList<HSD_AnimJoint?> states)
    {
        Dictionary<HSDStruct, int> modelJoints = new(
            ReferenceEqualityComparer.Instance);
        if (modelRoot is not null)
        {
            int modelJointIndex = 0;
            foreach (HSD_JOBJ joint in modelRoot.TreeList)
                modelJoints.Add(joint._s, modelJointIndex++);
        }
        StageJointAnimationSet[] result = new StageJointAnimationSet[states.Count];
        for (int stateIndex = 0; stateIndex < states.Count; ++stateIndex)
        {
            List<StageJointAnimationNode> nodes = [];
            Dictionary<HSDStruct, int> seen = new(ReferenceEqualityComparer.Instance);
            HSD_AnimJoint? root = states[stateIndex];
            if (root is not null)
                Visit(path, mapRootName, groupIndex, stateIndex,
                    root, nodes, seen, modelJoints);
            result[stateIndex] = new StageJointAnimationSet(
                path, mapRootName, groupIndex, stateIndex,
                root is not null, nodes.ToArray());
        }
        return result;
    }

    public static string ObjectTreeName(
        string mapRootName,
        int groupIndex,
        int stateIndex,
        int nodeIndex) =>
        $"{mapRootName}.model_groups[{groupIndex}].joint_animations" +
        $"[{stateIndex}].nodes[{nodeIndex}].object";

    public static byte[] Build(IReadOnlyList<StageJointAnimationSet> sets)
    {
        int nodeCount = sets.Sum(set => set.Nodes.Length);
        int trackCount = sets.Sum(set => set.Nodes.Sum(node => node.Tracks.Length));
        int setsOffset = HeaderSize;
        int nodesOffset = Align8(checked(setsOffset + sets.Count * SetRecordSize));
        int tracksOffset = Align8(checked(nodesOffset + nodeCount * NodeRecordSize));
        int blobOffset = Align8(checked(tracksOffset + trackCount * TrackRecordSize));
        int blobBytes = sets.Sum(set => set.Nodes.Sum(node =>
            node.Tracks.Sum(track => track.Buffer.Length)));
        byte[] result = new byte[checked(blobOffset + blobBytes)];
        Span<byte> span = result;

        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)sets.Count));
        WriteU32(span, 8, checked((uint)nodeCount));
        WriteU32(span, 12, checked((uint)trackCount));
        WriteU32(span, 16, SetRecordSize);
        WriteU32(span, 20, NodeRecordSize);
        WriteU32(span, 24, TrackRecordSize);
        WriteU64(span, 32, checked((ulong)setsOffset));
        WriteU64(span, 40, checked((ulong)nodesOffset));
        WriteU64(span, 48, checked((ulong)tracksOffset));
        WriteU64(span, 56, checked((ulong)blobOffset));
        WriteU64(span, 64, checked((ulong)blobBytes));

        int nodeIndex = 0;
        int trackIndex = 0;
        int bufferOffset = blobOffset;
        for (int setIndex = 0; setIndex < sets.Count; ++setIndex)
        {
            StageJointAnimationSet set = sets[setIndex];
            int setRecord = setsOffset + setIndex * SetRecordSize;
            int nodeBase = nodeIndex;
            WriteU64(span, setRecord, StableNameHash(set.Path));
            WriteU64(span, setRecord + 8, StableNameHash(set.MapRootName));
            WriteU32(span, setRecord + 16, checked((uint)set.GroupIndex));
            WriteU32(span, setRecord + 20, checked((uint)set.StateIndex));
            WriteU32(span, setRecord + 24, checked((uint)nodeBase));
            WriteU32(span, setRecord + 28, checked((uint)set.Nodes.Length));
            WriteU32(span, setRecord + 32, set.RootPresent ? 1U : 0U);

            foreach (StageJointAnimationNode node in set.Nodes)
            {
                int nodeRecord = nodesOffset + nodeIndex++ * NodeRecordSize;
                WriteI32(span, nodeRecord, GlobalIndex(node.Child, nodeBase));
                WriteI32(span, nodeRecord + 4, GlobalIndex(node.Next, nodeBase));
                WriteU32(span, nodeRecord + 8, node.Flags);
                WriteU32(span, nodeRecord + 12, node.PresenceFlags);
                WriteU32(span, nodeRecord + 16, node.AobjFlags);
                WriteU32(span, nodeRecord + 20, node.EndFrameBits);
                WriteU32(span, nodeRecord + 24, checked((uint)trackIndex));
                WriteU32(span, nodeRecord + 28, checked((uint)node.Tracks.Length));
                WriteU64(span, nodeRecord + 32,
                    node.ObjectTreeName is null ? 0 : StableNameHash(node.ObjectTreeName));
                WriteI32(span, nodeRecord + 40, node.ObjectModelJoint);

                foreach (StageJointAnimationTrack track in node.Tracks)
                {
                    int trackRecord = tracksOffset + trackIndex++ * TrackRecordSize;
                    WriteU32(span, trackRecord, checked((uint)track.Buffer.Length));
                    WriteU32(span, trackRecord + 4, track.StartFrameBits);
                    span[trackRecord + 8] = track.TrackType;
                    span[trackRecord + 9] = track.ValueFlags;
                    span[trackRecord + 10] = track.TangentFlags;
                    WriteU64(span, trackRecord + 16, checked((ulong)bufferOffset));
                    WriteU32(span, trackRecord + 24, checked((uint)track.Buffer.Length));
                    track.Buffer.CopyTo(span[bufferOffset..]);
                    bufferOffset += track.Buffer.Length;
                }
            }
        }
        if (nodeIndex != nodeCount || trackIndex != trackCount ||
            bufferOffset != result.Length)
            throw new InvalidDataException("stage joint-animation layout mismatch");
        return result;
    }

    private static int Visit(
        string path,
        string mapRootName,
        int groupIndex,
        int stateIndex,
        HSD_AnimJoint source,
        List<StageJointAnimationNode> nodes,
        Dictionary<HSDStruct, int> seen,
        Dictionary<HSDStruct, int> modelJoints)
    {
        if (seen.ContainsKey(source._s))
            throw new InvalidDataException(
                $"shared/cyclic stage joint animation in " +
                $"'{path}:{mapRootName}[{groupIndex}][{stateIndex}]'");
        int index = nodes.Count;
        seen.Add(source._s, index);
        HSD_AOBJ? aobj = source.AOBJ;
        HSD_JOBJ? objectReference = aobj?.ObjectReference;
        int objectModelJoint = objectReference is not null &&
            modelJoints.TryGetValue(objectReference._s, out int modelJoint)
                ? modelJoint
                : -1;
        string? objectTreeName = objectReference is null ? null :
            ObjectTreeName(mapRootName, groupIndex, stateIndex, index);
        uint presence = 0;
        if (aobj is not null) presence |= 1U << 0;
        if (source._s.References.ContainsKey(0x0C)) presence |= 1U << 1;
        if (objectReference is not null) presence |= 1U << 2;
        nodes.Add(new StageJointAnimationNode(
            -1,
            -1,
            source.Flags,
            presence,
            aobj is null ? 0U : unchecked((uint)aobj.Flags),
            aobj is null ? 0U : BitConverter.SingleToUInt32Bits(aobj.EndFrame),
            objectReference,
            objectTreeName,
            objectModelJoint,
            ReadTracks(path, mapRootName, groupIndex, stateIndex, index,
                aobj?.FObjDesc)));
        int child = source.Child is null ? -1 : Visit(
            path, mapRootName, groupIndex, stateIndex,
            source.Child, nodes, seen, modelJoints);
        int next = source.Next is null ? -1 : Visit(
            path, mapRootName, groupIndex, stateIndex,
            source.Next, nodes, seen, modelJoints);
        nodes[index] = nodes[index] with { Child = child, Next = next };
        return index;
    }

    private static StageJointAnimationTrack[] ReadTracks(
        string path,
        string mapRootName,
        int groupIndex,
        int stateIndex,
        int nodeIndex,
        HSD_FOBJDesc? source)
    {
        List<StageJointAnimationTrack> result = [];
        HashSet<HSDStruct> seen = new(ReferenceEqualityComparer.Instance);
        for (HSD_FOBJDesc? track = source; track is not null; track = track.Next)
        {
            if (!seen.Add(track._s))
                throw new InvalidDataException(
                    $"cyclic stage FOBJ list in '{path}:{mapRootName}" +
                    $"[{groupIndex}][{stateIndex}][{nodeIndex}]'");
            byte[] buffer = track.Buffer ?? [];
            if (track.DataLength < 0 || track.DataLength > buffer.Length)
                throw new InvalidDataException(
                    $"invalid stage FOBJ length in '{path}:{mapRootName}" +
                    $"[{groupIndex}][{stateIndex}][{nodeIndex}]'");
            result.Add(new StageJointAnimationTrack(
                BitConverter.SingleToUInt32Bits(track.StartFrame),
                track.TrackType,
                track._s.GetByte(0x0D),
                track._s.GetByte(0x0E),
                buffer.AsSpan(0, track.DataLength).ToArray()));
        }
        return result.ToArray();
    }

    private static int GlobalIndex(int local, int nodeBase) =>
        local < 0 ? -1 : checked(local + nodeBase);
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
    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record StageJointAnimationSet(
    string Path,
    string MapRootName,
    int GroupIndex,
    int StateIndex,
    bool RootPresent,
    StageJointAnimationNode[] Nodes);

internal sealed record StageJointAnimationNode(
    int Child,
    int Next,
    uint Flags,
    uint PresenceFlags,
    uint AobjFlags,
    uint EndFrameBits,
    HSD_JOBJ? ObjectReference,
    string? ObjectTreeName,
    int ObjectModelJoint,
    StageJointAnimationTrack[] Tracks);

internal sealed record StageJointAnimationTrack(
    uint StartFrameBits,
    byte TrackType,
    byte ValueFlags,
    byte TangentFlags,
    byte[] Buffer);
