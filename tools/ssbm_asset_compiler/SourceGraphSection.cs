using System.Buffers.Binary;
using System.Text;
using HSDRaw;

internal sealed class SourceGraphBuilder
{
    public const string Name = "source.graphs.v2";
    public const uint Schema = 2;
    public const int RootRecordSize = 40;
    public const int NodeRecordSize = 32;
    public const int EdgeRecordSize = 8;
    private const int HeaderSize = 64;

    private readonly Dictionary<HSDStruct, int> nodeMap =
        new(ReferenceEqualityComparer.Instance);
    private readonly Dictionary<HSDStruct, string> opaqueByteNodes =
        new(ReferenceEqualityComparer.Instance);
    private readonly List<SourceGraphRootAsset> roots = [];
    private readonly List<SourceGraphNodeAsset?> nodes = [];

    private readonly Dictionary<HSDStruct, (uint Group, uint Offset, uint Extent)> storage =
        new(ReferenceEqualityComparer.Instance);
    private readonly Dictionary<int, (uint Group, uint Offset, uint Extent)> nodeStorage = [];
    private uint groupCount;

    public void PreserveContiguousRecords(IReadOnlyList<HSDStruct> records,
        int stride, string provenance)
    {
        if (records.Count == 0) return;
        if (stride <= 0 || records.Any(record => record.Length != stride))
            throw new InvalidDataException($"{provenance}: inconsistent contiguous record extent");
        uint extent = checked((uint)(records.Count * stride));
        uint group = storage.TryGetValue(records[0], out var first) ? first.Group : groupCount++;
        for (int i = 0; i < records.Count; ++i)
        {
            var placement = (group, checked((uint)(i * stride)), extent);
            if (storage.TryGetValue(records[i], out var previous) && previous != placement)
                throw new InvalidDataException($"{provenance}: conflicting source storage aliases");
            storage[records[i]] = placement;
            if (nodeMap.TryGetValue(records[i], out int index)) nodeStorage[index] = placement;
        }
    }

    public void PreserveOpaqueBytes(HSDStruct source, string provenance)
    {
        if (source.References.Count != 0)
            throw new InvalidDataException(
                $"opaque byte node '{provenance}' contains relocations");
        opaqueByteNodes.TryAdd(source, provenance);
    }

    public void AddRoot(
        string path,
        string name,
        string typeName,
        uint ownerKind,
        int ownerIndex,
        HSDStruct source)
    {
        if (ownerKind > 1U || ownerIndex < 0)
            throw new InvalidDataException("invalid source graph owner identity");
        try
        {
            roots.Add(new(
                StableNameHash(path),
                StableNameHash(name),
                StableNameHash(typeName),
                ownerKind,
                checked((uint)ownerIndex),
                checked((uint)AddNode(source))));
        }
        catch (Exception exception)
        {
            throw new InvalidDataException(
                $"source graph conversion failed for '{path}:{name}' ({typeName})",
                exception);
        }
    }

    public void EndArchive() { nodeMap.Clear(); storage.Clear(); }

    public SourceGraphAsset Build()
    {
        SourceGraphNodeAsset[] completeNodes = nodes
            .Select(node => node ?? throw new InvalidDataException(
                "incomplete source graph node"))
            .ToArray();
        int edgeCount = completeNodes.Sum(node => node.Edges.Length);
        int wordCount = completeNodes.Sum(node => node.Words.Length);
        int rootsOffset = HeaderSize;
        int nodesOffset = Align8(checked(rootsOffset + roots.Count * RootRecordSize));
        int edgesOffset = Align8(checked(nodesOffset + completeNodes.Length * NodeRecordSize));
        int wordsOffset = Align8(checked(edgesOffset + edgeCount * EdgeRecordSize));
        byte[] result = new byte[checked(wordsOffset + wordCount * sizeof(uint))];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)roots.Count));
        WriteU32(span, 8, checked((uint)completeNodes.Length));
        WriteU32(span, 12, checked((uint)edgeCount));
        WriteU32(span, 16, checked((uint)wordCount));
        WriteU32(span, 20, RootRecordSize);
        WriteU32(span, 24, NodeRecordSize);
        WriteU32(span, 28, EdgeRecordSize);
        WriteU64(span, 32, checked((ulong)rootsOffset));
        WriteU64(span, 40, checked((ulong)nodesOffset));
        WriteU64(span, 48, checked((ulong)edgesOffset));
        WriteU64(span, 56, checked((ulong)wordsOffset));
        for (int index = 0; index < roots.Count; ++index)
        {
            SourceGraphRootAsset root = roots[index];
            int record = rootsOffset + index * RootRecordSize;
            WriteU64(span, record, root.FileNameHash);
            WriteU64(span, record + 8, root.RootNameHash);
            WriteU64(span, record + 16, root.TypeNameHash);
            WriteU32(span, record + 24, root.OwnerKind);
            WriteU32(span, record + 28, root.OwnerIndex);
            WriteU32(span, record + 32, root.NodeIndex);
        }
        int nextWord = 0;
        int nextEdge = 0;
        for (int index = 0; index < completeNodes.Length; ++index)
        {
            SourceGraphNodeAsset node = completeNodes[index];
            int record = nodesOffset + index * NodeRecordSize;
            WriteU32(span, record, checked((uint)node.LogicalBytes));
            WriteU32(span, record + 4, checked((uint)nextWord));
            WriteU32(span, record + 8, checked((uint)node.Words.Length));
            WriteU32(span, record + 12, checked((uint)nextEdge));
            WriteU32(span, record + 16, checked((uint)node.Edges.Length));
            WriteU32(span, record + 20, node.Flags);
            for (int word = 0; word < node.Words.Length; ++word)
                WriteU32(span, wordsOffset + (nextWord + word) * sizeof(uint),
                    node.Words[word]);
            foreach (SourceGraphEdgeAsset edge in node.Edges)
            {
                int edgeRecord = edgesOffset + nextEdge++ * EdgeRecordSize;
                WriteU32(span, edgeRecord, edge.SourceByteOffset);
                WriteU32(span, edgeRecord + 4, edge.TargetNode);
            }
            nextWord += node.Words.Length;
        }
        if (nextWord != wordCount || nextEdge != edgeCount)
            throw new InvalidDataException("source graph layout mismatch");
        byte[] storageData = new byte[checked(16 + completeNodes.Length * 12)];
        uint nextGroup = groupCount;
        WriteU32(storageData, 0, 1);
        WriteU32(storageData, 4, checked((uint)completeNodes.Length));
        WriteU32(storageData, 12, 12);
        for (int i = 0; i < completeNodes.Length; ++i)
        {
            var placement = nodeStorage.TryGetValue(i, out var shared) ? shared :
                (Group: nextGroup++, Offset: 0U, Extent: checked((uint)completeNodes[i].LogicalBytes));
            WriteU32(storageData, 16 + i * 12, placement.Group);
            WriteU32(storageData, 20 + i * 12, placement.Offset);
            WriteU32(storageData, 24 + i * 12, placement.Extent);
        }
        WriteU32(storageData, 8, nextGroup);
        return new(result, roots.Count, completeNodes.Length, edgeCount, wordCount, storageData);
    }

    private int AddNode(HSDStruct source)
    {
        if (nodeMap.TryGetValue(source, out int existing)) return existing;
        int index = nodes.Count;
        nodeMap.Add(source, index);
        nodes.Add(null);
        if (storage.TryGetValue(source, out var placement)) nodeStorage[index] = placement;
        byte[] sourceBytes = source.GetData().ToArray();
        if (opaqueByteNodes.TryGetValue(source, out string? provenance) &&
            source.ScalarFields.Count != 0)
        {
            throw new InvalidDataException(
                $"opaque byte node '{provenance}' acquired scalar fields: " +
                string.Join(",", source.ScalarFields
                    .OrderBy(field => field.Key)
                    .Select(field => $"{field.Key}+{field.Value}")));
        }
        foreach ((int offset, int width) in source.ScalarFields.OrderBy(item => item.Key))
        {
            if (offset < 0 || width < 2 || offset > sourceBytes.Length - width)
                throw new InvalidDataException(
                    $"invalid scalar field at {offset}+{width}/{sourceBytes.Length}");
            Array.Reverse(sourceBytes, offset, width);
        }
        List<SourceGraphEdgeAsset> edges = [];
        foreach ((int offset, HSDStruct target) in
                 source.References.OrderBy(item => item.Key))
        {
            if (offset < 0 || offset % sizeof(uint) != 0 ||
                offset > sourceBytes.Length - sizeof(uint) || target is null)
                throw new InvalidDataException(
                    $"invalid source graph reference at {offset}/{sourceBytes.Length}");
            if (source.ScalarFields.Any(field =>
                    offset < field.Key + field.Value &&
                    field.Key < offset + sizeof(uint)))
                throw new InvalidDataException(
                    $"source graph reference overlaps scalar field at {offset} " +
                    $"in {sourceBytes.Length}-byte node; fields=" +
                    string.Join(",", source.ScalarFields
                        .OrderBy(field => field.Key)
                        .Select(field => $"{field.Key}+{field.Value}")));
            Array.Clear(sourceBytes, offset, sizeof(uint));
            edges.Add(new(checked((uint)offset), checked((uint)AddNode(target))));
        }
        uint[] words = new uint[(sourceBytes.Length + 3) / sizeof(uint)];
        for (int wordIndex = 0; wordIndex < words.Length; ++wordIndex)
        {
            uint word = 0;
            for (int byteIndex = 0; byteIndex < sizeof(uint); ++byteIndex)
            {
                int sourceIndex = wordIndex * sizeof(uint) + byteIndex;
                if (sourceIndex < sourceBytes.Length)
                    word |= (uint)sourceBytes[sourceIndex] << (24 - byteIndex * 8);
            }
            words[wordIndex] = word;
        }
        uint flags = 0;
        if (source.IsBufferAligned) flags |= 1U << 0;
        if (source.CanBeDuplicate) flags |= 1U << 1;
        if (source.CanBeBuffer) flags |= 1U << 2;
        if (source.Align) flags |= 1U << 3;
        nodes[index] = new(sourceBytes.Length, words, edges.ToArray(), flags);
        return index;
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
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record SourceGraphAsset(
    byte[] Data,
    int RootCount,
    int NodeCount,
    int EdgeCount,
    int WordCount,
    byte[] StorageData);
internal sealed record SourceGraphRootAsset(
    ulong FileNameHash,
    ulong RootNameHash,
    ulong TypeNameHash,
    uint OwnerKind,
    uint OwnerIndex,
    uint NodeIndex);
internal sealed record SourceGraphNodeAsset(
    int LogicalBytes,
    uint[] Words,
    SourceGraphEdgeAsset[] Edges,
    uint Flags);
internal sealed record SourceGraphEdgeAsset(uint SourceByteOffset, uint TargetNode);
