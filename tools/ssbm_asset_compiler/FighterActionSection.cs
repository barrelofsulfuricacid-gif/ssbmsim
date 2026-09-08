using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Common.Animation;
using HSDRaw.Melee.Pl;
using HSDRaw.Tools.Melee;

internal static class FighterActionSection
{
    public const string Name = "fighter.actions.v1";
    public const uint Schema = 1;
    public const int FighterRecordSize = 32;
    public const int ActionRecordSize = 80;
    public const int NodeRecordSize = 8;
    public const int TrackRecordSize = 32;
    private const int HeaderSize = 64;

    public static FighterActionAsset Read(
        string path,
        string rootName,
        SBM_FighterData fighter,
        FighterAJManager? animationArchive)
    {
        SBM_FighterAction[] commands = fighter.FighterActionTable?.Commands ?? [];
        FighterAction[] actions = new FighterAction[commands.Length];
        for (int actionIndex = 0; actionIndex < commands.Length; ++actionIndex)
        {
            SBM_FighterAction command = commands[actionIndex];
            byte[] script = command.SubAction?._s.GetData() ?? [];
            HSD_FigaTree? animation = command.Animation;
            string actionName = command.Name ?? string.Empty;
            if (animation is null && command.AnimationSize != 0)
            {
                byte[]? animationData = animationArchive?.GetAnimationData(actionName);
                if (animationData is null)
                {
                    throw new InvalidDataException(
                        $"missing AJ animation '{actionName}' for " +
                        $"'{path}:{rootName}' action {actionIndex}");
                }
                if (animationData.Length != command.AnimationSize)
                {
                    throw new InvalidDataException(
                        $"AJ animation size mismatch for '{actionName}' in " +
                        $"'{path}:{rootName}': {animationData.Length} != " +
                        $"{command.AnimationSize}");
                }
                HSDRawFile animationFile = new(animationData);
                if (animationFile.Roots.Count != 1 ||
                    animationFile.Roots[0].Name != actionName ||
                    animationFile.Roots[0].Data is not HSD_FigaTree animationTree)
                {
                    throw new InvalidDataException(
                        $"invalid AJ animation mini-DAT '{actionName}' for " +
                        $"'{path}:{rootName}' action {actionIndex}");
                }
                animation = animationTree;
            }
            FighterAnimation? outputAnimation = null;
            if (animation is not null)
            {
                List<FigaTreeNode> sourceNodes = animation.Nodes;
                List<FighterAnimationNode> nodes = new(sourceNodes.Count);
                List<FighterAnimationTrack> tracks = [];
                foreach (FigaTreeNode sourceNode in sourceNodes)
                {
                    int firstTrack = tracks.Count;
                    foreach (HSD_Track sourceTrack in sourceNode.Tracks)
                    {
                        byte[] buffer = sourceTrack.Buffer ?? [];
                        if (sourceTrack.DataLength > buffer.Length)
                        {
                            throw new InvalidDataException(
                                $"animation track length mismatch in " +
                                $"'{path}:{rootName}' action {actionIndex}: " +
                                $"declared {sourceTrack.DataLength}, decoded " +
                                $"{buffer.Length}");
                        }
                        byte[] normalizedBuffer = buffer
                            .AsSpan(0, sourceTrack.DataLength)
                            .ToArray();
                        tracks.Add(new FighterAnimationTrack(
                            sourceTrack.DataLength,
                            sourceTrack.StartFrame,
                            sourceTrack.TrackType,
                            (byte)sourceTrack.ValueFormat,
                            (byte)sourceTrack.TanFormat,
                            sourceTrack.ValueScale,
                            sourceTrack.TanScale,
                            normalizedBuffer));
                    }
                    nodes.Add(new FighterAnimationNode(firstTrack, tracks.Count - firstTrack));
                }
                if (animation.NodeCount != nodes.Count ||
                    animation.TrackCount != tracks.Count)
                {
                    throw new InvalidDataException(
                        $"animation topology mismatch in '{path}:{rootName}' " +
                        $"action {actionIndex}");
                }
                outputAnimation = new FighterAnimation(
                    animation.Type,
                    BitConverter.SingleToUInt32Bits(animation.FrameCount),
                    nodes.ToArray(),
                    tracks.ToArray());
            }
            actions[actionIndex] = new FighterAction(
                actionName,
                command.AnimationOffset,
                command.AnimationSize,
                command.Flags,
                script,
                outputAnimation);
        }
        return new FighterActionAsset(path, rootName, actions);
    }

    public static byte[] Build(IReadOnlyList<FighterActionAsset> fighters)
    {
        int actionCount = fighters.Sum(fighter => fighter.Actions.Length);
        int fighterRecordsOffset = HeaderSize;
        int actionRecordsOffset = checked(
            fighterRecordsOffset + fighters.Count * FighterRecordSize);
        int blobOffset = Align8(checked(
            actionRecordsOffset + actionCount * ActionRecordSize));

        using MemoryStream blob = new();
        List<ActionLayout> layouts = new(actionCount);
        foreach (FighterActionAsset fighter in fighters)
        {
            foreach (FighterAction action in fighter.Actions)
            {
                byte[] name = Encoding.UTF8.GetBytes(action.Name);
                int nameOffset = checked((int)blob.Position);
                blob.Write(name);
                int scriptOffset = checked((int)blob.Position);
                blob.Write(action.Script);

                int nodesOffset = 0;
                int tracksOffset = 0;
                List<int> bufferOffsets = [];
                if (action.Animation is not null)
                {
                    Align8(blob);
                    nodesOffset = checked((int)blob.Position);
                    blob.Position = checked(
                        blob.Position +
                        action.Animation.Nodes.Length * NodeRecordSize);
                    Align8(blob);
                    tracksOffset = checked((int)blob.Position);
                    blob.Position = checked(
                        blob.Position +
                        action.Animation.Tracks.Length * TrackRecordSize);
                    blob.SetLength(blob.Position);
                    foreach (FighterAnimationTrack track in action.Animation.Tracks)
                    {
                        bufferOffsets.Add(checked((int)blob.Position));
                        blob.Write(track.Buffer);
                    }
                }
                layouts.Add(new ActionLayout(
                    nameOffset,
                    name.Length,
                    scriptOffset,
                    action.Script.Length,
                    nodesOffset,
                    tracksOffset,
                    bufferOffsets.ToArray()));
            }
        }

        byte[] result = new byte[checked(blobOffset + (int)blob.Length)];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)fighters.Count));
        WriteU32(span, 8, checked((uint)actionCount));
        WriteU32(span, 12, FighterRecordSize);
        WriteU32(span, 16, ActionRecordSize);
        WriteU32(span, 20, NodeRecordSize);
        WriteU32(span, 24, TrackRecordSize);
        WriteU64(span, 32, checked((ulong)fighterRecordsOffset));
        WriteU64(span, 40, checked((ulong)actionRecordsOffset));
        WriteU64(span, 48, checked((ulong)blobOffset));
        WriteU64(span, 56, checked((ulong)blob.Length));
        blob.ToArray().CopyTo(span[blobOffset..]);

        int actionBase = 0;
        int layoutIndex = 0;
        for (int fighterIndex = 0; fighterIndex < fighters.Count; ++fighterIndex)
        {
            FighterActionAsset fighter = fighters[fighterIndex];
            int fighterOffset = fighterRecordsOffset + fighterIndex * FighterRecordSize;
            WriteU64(span, fighterOffset, StableNameHash(fighter.Path));
            WriteU64(span, fighterOffset + 8, StableNameHash(fighter.RootName));
            WriteU64(span, fighterOffset + 16, checked((ulong)(
                actionRecordsOffset + actionBase)));
            WriteU32(span, fighterOffset + 24, checked((uint)fighter.Actions.Length));

            foreach (FighterAction action in fighter.Actions)
            {
                ActionLayout layout = layouts[layoutIndex++];
                int recordOffset = actionRecordsOffset + actionBase;
                WriteU64(span, recordOffset, checked((ulong)(blobOffset + layout.NameOffset)));
                WriteU32(span, recordOffset + 8, checked((uint)layout.NameLength));
                WriteU32(span, recordOffset + 12, action.Flags);
                WriteI32(span, recordOffset + 16, action.AnimationOffset);
                WriteI32(span, recordOffset + 20, action.AnimationSize);
                WriteU64(span, recordOffset + 24, checked((ulong)(
                    blobOffset + layout.ScriptOffset)));
                WriteU32(span, recordOffset + 32, checked((uint)layout.ScriptLength));
                WriteU32(span, recordOffset + 36, action.Animation is null ? 0U : 1U);
                if (action.Animation is not null)
                {
                    WriteI32(span, recordOffset + 40, action.Animation.Type);
                    WriteU32(span, recordOffset + 44, action.Animation.FrameCountBits);
                    WriteU64(span, recordOffset + 48, checked((ulong)(
                        blobOffset + layout.NodesOffset)));
                    WriteU32(span, recordOffset + 56,
                        checked((uint)action.Animation.Nodes.Length));
                    WriteU64(span, recordOffset + 64, checked((ulong)(
                        blobOffset + layout.TracksOffset)));
                    WriteU32(span, recordOffset + 72,
                        checked((uint)action.Animation.Tracks.Length));

                    for (int nodeIndex = 0;
                         nodeIndex < action.Animation.Nodes.Length;
                         ++nodeIndex)
                    {
                        FighterAnimationNode node = action.Animation.Nodes[nodeIndex];
                        int nodeOffset = blobOffset + layout.NodesOffset +
                            nodeIndex * NodeRecordSize;
                        WriteU32(span, nodeOffset, checked((uint)node.FirstTrack));
                        WriteU32(span, nodeOffset + 4, checked((uint)node.TrackCount));
                    }
                    for (int trackIndex = 0;
                         trackIndex < action.Animation.Tracks.Length;
                         ++trackIndex)
                    {
                        FighterAnimationTrack track = action.Animation.Tracks[trackIndex];
                        int trackOffset = blobOffset + layout.TracksOffset +
                            trackIndex * TrackRecordSize;
                        WriteU16(span, trackOffset, track.DataLength);
                        WriteI16(span, trackOffset + 2, track.StartFrame);
                        span[trackOffset + 4] = track.TrackType;
                        span[trackOffset + 5] = track.ValueFormat;
                        span[trackOffset + 6] = track.TangentFormat;
                        WriteU32(span, trackOffset + 8, track.ValueScale);
                        WriteU32(span, trackOffset + 12, track.TangentScale);
                        WriteU64(span, trackOffset + 16, checked((ulong)(
                            blobOffset + layout.BufferOffsets[trackIndex])));
                        WriteU32(span, trackOffset + 24,
                            checked((uint)track.Buffer.Length));
                    }
                }
                actionBase += ActionRecordSize;
            }
        }
        if (layoutIndex != layouts.Count || actionBase != actionCount * ActionRecordSize)
        {
            throw new InvalidDataException("fighter action layout mismatch");
        }
        return result;
    }

    private static int Align8(int value) => checked((value + 7) & ~7);

    private static void Align8(MemoryStream stream)
    {
        stream.Position = Align8(checked((int)stream.Position));
        if (stream.Length < stream.Position)
        {
            stream.SetLength(stream.Position);
        }
    }

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

    private static void WriteU16(Span<byte> bytes, int offset, ushort value) =>
        BinaryPrimitives.WriteUInt16LittleEndian(bytes[offset..], value);

    private static void WriteI16(Span<byte> bytes, int offset, short value) =>
        BinaryPrimitives.WriteInt16LittleEndian(bytes[offset..], value);

    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);

    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);

    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record FighterActionAsset(
    string Path,
    string RootName,
    FighterAction[] Actions);

internal sealed record FighterAction(
    string Name,
    int AnimationOffset,
    int AnimationSize,
    uint Flags,
    byte[] Script,
    FighterAnimation? Animation);

internal sealed record FighterAnimation(
    int Type,
    uint FrameCountBits,
    FighterAnimationNode[] Nodes,
    FighterAnimationTrack[] Tracks);

internal readonly record struct FighterAnimationNode(int FirstTrack, int TrackCount);

internal sealed record FighterAnimationTrack(
    ushort DataLength,
    short StartFrame,
    byte TrackType,
    byte ValueFormat,
    byte TangentFormat,
    uint ValueScale,
    uint TangentScale,
    byte[] Buffer);

internal sealed record ActionLayout(
    int NameOffset,
    int NameLength,
    int ScriptOffset,
    int ScriptLength,
    int NodesOffset,
    int TracksOffset,
    int[] BufferOffsets);
