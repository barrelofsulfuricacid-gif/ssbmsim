using System.Buffers.Binary;
using System.Text;
using HSDRaw.Melee.Gr;

internal static class StageCollisionSection
{
    public const string Name = "stage.collision.v1";
    public const uint Schema = 1;
    public const int RecordSize = 96;
    private const int HeaderSize = 48;
    private const int VertexSize = 8;
    private const int LineSize = 16;
    private const int GroupSize = 40;

    public static StageCollisionAsset Read(
        string path,
        string rootName,
        SBM_Coll_Data collision)
    {
        SBM_CollVertex[] vertices = collision.Vertices ??
            throw new InvalidDataException($"missing collision vertices in '{path}:{rootName}'");
        SBM_CollLine[] lines = collision.Links ??
            throw new InvalidDataException($"missing collision links in '{path}:{rootName}'");
        SBM_CollLineGroup[] groups = collision.LineGroups ??
            throw new InvalidDataException($"missing collision groups in '{path}:{rootName}'");

        StageVertex[] outputVertices = vertices.Select(vertex => new StageVertex(
            BitConverter.SingleToUInt32Bits(vertex.X),
            BitConverter.SingleToUInt32Bits(vertex.Y))).ToArray();
        StageLine[] outputLines = lines.Select(line => new StageLine(
            line.VertexIndex1,
            line.VertexIndex2,
            line.NextLine,
            line.PreviousLine,
            line.NextLineAltGroup,
            line.PreviousLineAltGroup,
            (short)line.CollisionFlag,
            (byte)line.Flag,
            (byte)line.Material)).ToArray();
        StageGroup[] outputGroups = groups.Select(group => new StageGroup(
            group.TopLineIndex,
            group.TopLineCount,
            group.BottomLineIndex,
            group.BottomLineCount,
            group.RightLineIndex,
            group.RightLineCount,
            group.LeftLineIndex,
            group.LeftLineCount,
            group.DynamicLineIndex,
            group.DynamicLineCount,
            BitConverter.SingleToUInt32Bits(group.XMin),
            BitConverter.SingleToUInt32Bits(group.YMin),
            BitConverter.SingleToUInt32Bits(group.XMax),
            BitConverter.SingleToUInt32Bits(group.YMax),
            group.VertexStart,
            group.VertexCount)).ToArray();

        StageCollisionAsset asset = new(
            path,
            rootName,
            new LinkRange(collision.TopLinksOffset, collision.TopLinksCount),
            new LinkRange(collision.BottomLinksOffset, collision.BottomLinksCount),
            new LinkRange(collision.RightLinksOffset, collision.RightLinksCount),
            new LinkRange(collision.LeftLinksOffset, collision.LeftLinksCount),
            new LinkRange(collision.DynamicLinksOffset, collision.DynamicLinksCount),
            outputVertices,
            outputLines,
            outputGroups);
        Validate(asset);
        return asset;
    }

    public static byte[] Build(IReadOnlyList<StageCollisionAsset> stages)
    {
        int recordsOffset = HeaderSize;
        int payloadOffset = Align8(checked(recordsOffset + stages.Count * RecordSize));
        int size = payloadOffset;
        foreach (StageCollisionAsset stage in stages)
        {
            size = checked(size + stage.Vertices.Length * VertexSize);
            size = checked(size + stage.Lines.Length * LineSize);
            size = checked(size + stage.Groups.Length * GroupSize);
        }

        byte[] result = new byte[size];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, (uint)stages.Count);
        WriteU32(span, 8, RecordSize);
        WriteU32(span, 12, VertexSize);
        WriteU32(span, 16, LineSize);
        WriteU32(span, 20, GroupSize);
        WriteU64(span, 24, (ulong)recordsOffset);
        WriteU64(span, 32, (ulong)payloadOffset);

        int dataOffset = payloadOffset;
        for (int index = 0; index < stages.Count; ++index)
        {
            StageCollisionAsset stage = stages[index];
            int recordOffset = recordsOffset + index * RecordSize;
            int verticesOffset = dataOffset;
            dataOffset += stage.Vertices.Length * VertexSize;
            int linesOffset = dataOffset;
            dataOffset += stage.Lines.Length * LineSize;
            int groupsOffset = dataOffset;
            dataOffset += stage.Groups.Length * GroupSize;

            WriteU64(span, recordOffset, StableNameHash(stage.Path));
            WriteU64(span, recordOffset + 8, StableNameHash(stage.RootName));
            WriteU64(span, recordOffset + 16, (ulong)verticesOffset);
            WriteU32(span, recordOffset + 24, (uint)stage.Vertices.Length);
            WriteU64(span, recordOffset + 32, (ulong)linesOffset);
            WriteU32(span, recordOffset + 40, (uint)stage.Lines.Length);
            WriteU64(span, recordOffset + 48, (ulong)groupsOffset);
            WriteU32(span, recordOffset + 56, (uint)stage.Groups.Length);
            WriteRange(span, recordOffset + 64, stage.Top);
            WriteRange(span, recordOffset + 68, stage.Bottom);
            WriteRange(span, recordOffset + 72, stage.Right);
            WriteRange(span, recordOffset + 76, stage.Left);
            WriteRange(span, recordOffset + 80, stage.Dynamic);

            foreach (StageVertex vertex in stage.Vertices)
            {
                WriteU32(span, verticesOffset, vertex.XBits);
                WriteU32(span, verticesOffset + 4, vertex.YBits);
                verticesOffset += VertexSize;
            }
            foreach (StageLine line in stage.Lines)
            {
                WriteI16(span, linesOffset, line.Vertex1);
                WriteI16(span, linesOffset + 2, line.Vertex2);
                WriteI16(span, linesOffset + 4, line.Next);
                WriteI16(span, linesOffset + 6, line.Previous);
                WriteI16(span, linesOffset + 8, line.NextAlternate);
                WriteI16(span, linesOffset + 10, line.PreviousAlternate);
                WriteI16(span, linesOffset + 12, line.CollisionFlags);
                span[linesOffset + 14] = line.Properties;
                span[linesOffset + 15] = line.Material;
                linesOffset += LineSize;
            }
            foreach (StageGroup group in stage.Groups)
            {
                WriteRange(span, groupsOffset, group.Top);
                WriteRange(span, groupsOffset + 4, group.Bottom);
                WriteRange(span, groupsOffset + 8, group.Right);
                WriteRange(span, groupsOffset + 12, group.Left);
                WriteRange(span, groupsOffset + 16, group.Dynamic);
                WriteU32(span, groupsOffset + 20, group.XMinBits);
                WriteU32(span, groupsOffset + 24, group.YMinBits);
                WriteU32(span, groupsOffset + 28, group.XMaxBits);
                WriteU32(span, groupsOffset + 32, group.YMaxBits);
                WriteRange(span, groupsOffset + 36, group.Vertices);
                groupsOffset += GroupSize;
            }
        }
        if (dataOffset != result.Length)
        {
            throw new InvalidDataException("stage collision layout size mismatch");
        }
        return result;
    }

    private static void Validate(StageCollisionAsset stage)
    {
        ValidateRange(stage.Top, stage.Lines.Length, stage.Path, "top");
        ValidateRange(stage.Bottom, stage.Lines.Length, stage.Path, "bottom");
        ValidateRange(stage.Right, stage.Lines.Length, stage.Path, "right");
        ValidateRange(stage.Left, stage.Lines.Length, stage.Path, "left");
        ValidateRange(stage.Dynamic, stage.Lines.Length, stage.Path, "dynamic");
        for (int index = 0; index < stage.Lines.Length; ++index)
        {
            StageLine line = stage.Lines[index];
            if (line.Vertex1 < 0 || line.Vertex1 >= stage.Vertices.Length ||
                line.Vertex2 < 0 || line.Vertex2 >= stage.Vertices.Length)
            {
                throw new InvalidDataException(
                    $"collision line {index} has invalid vertex in '{stage.Path}'");
            }
        }
        for (int index = 0; index < stage.Groups.Length; ++index)
        {
            StageGroup group = stage.Groups[index];
            ValidateRange(group.Top, stage.Lines.Length, stage.Path, $"group {index} top");
            ValidateRange(group.Bottom, stage.Lines.Length, stage.Path, $"group {index} bottom");
            ValidateRange(group.Right, stage.Lines.Length, stage.Path, $"group {index} right");
            ValidateRange(group.Left, stage.Lines.Length, stage.Path, $"group {index} left");
            ValidateRange(group.Dynamic, stage.Lines.Length, stage.Path, $"group {index} dynamic");
            ValidateRange(group.Vertices, stage.Vertices.Length, stage.Path, $"group {index} vertices");
        }
    }

    private static void ValidateRange(LinkRange range, int total, string path, string label)
    {
        if (range.Offset < 0 || range.Count < 0 ||
            (long)range.Offset + range.Count > total)
        {
            throw new InvalidDataException(
                $"invalid {label} collision range in '{path}': " +
                $"{range.Offset}+{range.Count}>{total}");
        }
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

    private static void WriteRange(Span<byte> bytes, int offset, LinkRange range)
    {
        WriteI16(bytes, offset, range.Offset);
        WriteI16(bytes, offset + 2, range.Count);
    }

    private static void WriteI16(Span<byte> bytes, int offset, short value) =>
        BinaryPrimitives.WriteInt16LittleEndian(bytes[offset..], value);

    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);

    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record StageCollisionAsset(
    string Path,
    string RootName,
    LinkRange Top,
    LinkRange Bottom,
    LinkRange Right,
    LinkRange Left,
    LinkRange Dynamic,
    StageVertex[] Vertices,
    StageLine[] Lines,
    StageGroup[] Groups);

internal readonly record struct LinkRange(short Offset, short Count);
internal readonly record struct StageVertex(uint XBits, uint YBits);
internal readonly record struct StageLine(
    short Vertex1,
    short Vertex2,
    short Next,
    short Previous,
    short NextAlternate,
    short PreviousAlternate,
    short CollisionFlags,
    byte Properties,
    byte Material);
internal readonly record struct StageGroup(
    short TopOffset,
    short TopCount,
    short BottomOffset,
    short BottomCount,
    short RightOffset,
    short RightCount,
    short LeftOffset,
    short LeftCount,
    short DynamicOffset,
    short DynamicCount,
    uint XMinBits,
    uint YMinBits,
    uint XMaxBits,
    uint YMaxBits,
    short VertexOffset,
    short VertexCount)
{
    public LinkRange Top => new(TopOffset, TopCount);
    public LinkRange Bottom => new(BottomOffset, BottomCount);
    public LinkRange Right => new(RightOffset, RightCount);
    public LinkRange Left => new(LeftOffset, LeftCount);
    public LinkRange Dynamic => new(DynamicOffset, DynamicCount);
    public LinkRange Vertices => new(VertexOffset, VertexCount);
}
