using System.Buffers.Binary;
using System.Text;
using HSDRaw;

internal static class ArticleGraphSection
{
    public const string Name = "article.graphs.v1";
    public const uint Schema = 1;
    public const int RootRecordSize = 40;
    public const int NodeRecordSize = 32;
    public const int EdgeRecordSize = 8;
    private const int HeaderSize = 64;
    private const uint ExtensionRoot = 1;
    private const uint AnimationRoot = 2;
    private const uint MaterialAnimationRoot = 3;
    private const uint StateParameterRoot = 4;

    public static ArticleGraphAsset Build(IReadOnlyList<ArticleSourceAsset> sources)
    {
        List<ArticleGraphRootSource> rootSources = [];
        foreach (ArticleSourceAsset source in sources)
        {
            for (int slotIndex = 0; slotIndex < source.Slots.Length; ++slotIndex)
            {
                ArticleSlotAsset? slot = source.Slots[slotIndex];
                if (slot is null) continue;
                if (slot.ExtensionStruct is not null)
                    rootSources.Add(new(source, slotIndex, uint.MaxValue,
                        ExtensionRoot, slot.ExtensionStruct));
                for (int stateIndex = 0; stateIndex < slot.States.Length; ++stateIndex)
                {
                    ArticleState state = slot.States[stateIndex];
                    if (state.AnimationStruct is not null)
                        rootSources.Add(new(source, slotIndex, checked((uint)stateIndex),
                            AnimationRoot, state.AnimationStruct));
                    if (state.MaterialAnimationStruct is not null)
                        rootSources.Add(new(source, slotIndex, checked((uint)stateIndex),
                            MaterialAnimationRoot, state.MaterialAnimationStruct));
                    if (state.ParameterStruct is not null)
                        rootSources.Add(new(source, slotIndex, checked((uint)stateIndex),
                            StateParameterRoot, state.ParameterStruct));
                }
            }
        }

        Dictionary<HSDStruct, int> nodeMap = new(ReferenceEqualityComparer.Instance);
        List<ArticleGraphNodeAsset?> nodes = [];
        int AddNode(HSDStruct source)
        {
            if (nodeMap.TryGetValue(source, out int existing)) return existing;
            int index = nodes.Count;
            nodeMap.Add(source, index);
            nodes.Add(null);
            byte[] sourceBytes = source.GetData().ToArray();
            List<ArticleGraphEdgeAsset> localEdges = [];
            foreach ((int offset, HSDStruct target) in
                     source.References.OrderBy(item => item.Key))
            {
                if (offset < 0 || offset % sizeof(uint) != 0 ||
                    offset > sourceBytes.Length - sizeof(uint) || target is null)
                    throw new InvalidDataException(
                        $"invalid HSD graph reference at {offset}/{sourceBytes.Length}");
                Array.Clear(sourceBytes, offset, sizeof(uint));
                localEdges.Add(new(checked((uint)offset), checked((uint)AddNode(target))));
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
            nodes[index] = new(
                sourceBytes.Length,
                words,
                localEdges.ToArray(),
                flags);
            return index;
        }

        ArticleGraphRootAsset[] roots = rootSources.Select(root => new ArticleGraphRootAsset(
            StableNameHash(root.Source.Path),
            StableNameHash(root.Source.RootName),
            root.Source.GroupKind,
            checked((uint)root.SlotIndex),
            root.StateIndex,
            root.RootKind,
            checked((uint)AddNode(root.Struct)))).ToArray();
        ArticleGraphNodeAsset[] completeNodes = nodes
            .Select(node => node ?? throw new InvalidDataException("incomplete HSD graph node"))
            .ToArray();
        int edgeCount = completeNodes.Sum(node => node.Edges.Length);
        int wordCount = completeNodes.Sum(node => node.Words.Length);
        int rootsOffset = HeaderSize;
        int nodesOffset = Align8(checked(rootsOffset + roots.Length * RootRecordSize));
        int edgesOffset = Align8(checked(nodesOffset + completeNodes.Length * NodeRecordSize));
        int wordsOffset = Align8(checked(edgesOffset + edgeCount * EdgeRecordSize));
        byte[] result = new byte[checked(wordsOffset + wordCount * sizeof(uint))];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)roots.Length));
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
        for (int index = 0; index < roots.Length; ++index)
        {
            ArticleGraphRootAsset root = roots[index];
            int record = rootsOffset + index * RootRecordSize;
            WriteU64(span, record, root.FileNameHash);
            WriteU64(span, record + 8, root.RootNameHash);
            WriteU32(span, record + 16, root.GroupKind);
            WriteU32(span, record + 20, root.SlotIndex);
            WriteU32(span, record + 24, root.StateIndex);
            WriteU32(span, record + 28, root.RootKind);
            WriteU32(span, record + 32, root.NodeIndex);
        }
        int nextWord = 0;
        int nextEdge = 0;
        for (int index = 0; index < completeNodes.Length; ++index)
        {
            ArticleGraphNodeAsset node = completeNodes[index];
            int record = nodesOffset + index * NodeRecordSize;
            WriteU32(span, record, checked((uint)node.LogicalBytes));
            WriteU32(span, record + 4, checked((uint)nextWord));
            WriteU32(span, record + 8, checked((uint)node.Words.Length));
            WriteU32(span, record + 12, checked((uint)nextEdge));
            WriteU32(span, record + 16, checked((uint)node.Edges.Length));
            WriteU32(span, record + 20, node.Flags);
            for (int word = 0; word < node.Words.Length; ++word)
                WriteU32(span, wordsOffset + (nextWord + word) * sizeof(uint), node.Words[word]);
            foreach (ArticleGraphEdgeAsset edge in node.Edges)
            {
                int edgeRecord = edgesOffset + nextEdge++ * EdgeRecordSize;
                WriteU32(span, edgeRecord, edge.SourceByteOffset);
                WriteU32(span, edgeRecord + 4, edge.TargetNode);
            }
            nextWord += node.Words.Length;
        }
        if (nextWord != wordCount || nextEdge != edgeCount)
            throw new InvalidDataException("HSD graph word layout mismatch");
        return new(result, roots.Length, completeNodes.Length, edgeCount, wordCount);
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

internal sealed record ArticleGraphAsset(
    byte[] Data,
    int RootCount,
    int NodeCount,
    int EdgeCount,
    int WordCount);
internal sealed record ArticleGraphRootSource(
    ArticleSourceAsset Source,
    int SlotIndex,
    uint StateIndex,
    uint RootKind,
    HSDStruct Struct);
internal sealed record ArticleGraphRootAsset(
    ulong FileNameHash,
    ulong RootNameHash,
    uint GroupKind,
    uint SlotIndex,
    uint StateIndex,
    uint RootKind,
    uint NodeIndex);
internal sealed record ArticleGraphNodeAsset(
    int LogicalBytes,
    uint[] Words,
    ArticleGraphEdgeAsset[] Edges,
    uint Flags);
internal sealed record ArticleGraphEdgeAsset(uint SourceByteOffset, uint TargetNode);
