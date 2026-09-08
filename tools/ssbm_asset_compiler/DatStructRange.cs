using HSDRaw;
using System.Runtime.CompilerServices;

internal static class DatStructRange
{
    private sealed record Snapshot(List<(int Offset, HSDStruct Struct)> Nodes);
    private static readonly ConditionalWeakTable<HSDRawFile, Snapshot> snapshots = new();

    // Keep original fragments reachable even after external-link initialization
    // disconnects a chain or a typed view spans several original DAT nodes.
    public static void Capture(HSDRawFile archive) => _ = GetSnapshot(archive);

    private static Snapshot GetSnapshot(HSDRawFile archive) =>
        snapshots.GetValue(archive, value => new Snapshot(value.Roots
            .Concat(value.References)
            .SelectMany(root => root.Data._s.GetSubStructs())
            .Distinct()
            .Select(item => (value.GetOffsetFromStruct(item), item))
            .Where(item => item.Item1 >= 0)
            .OrderBy(item => item.Item1)
            .ToList()));

    public static HSDStruct? AtOffset(HSDRawFile archive, int offset) =>
        GetSnapshot(archive).Nodes
            .Where(item => item.Offset == offset)
            .Select(item => item.Struct).SingleOrDefault();

    public static T[] ReadCountedArray<T>(
        HSDRawFile archive,
        HSDAccessor? source,
        int count,
        string context)
        where T : HSDAccessor, new()
    {
        if (count < 0 || (count != 0 && source is null))
            throw new InvalidDataException(
                $"invalid counted DAT array in '{context}'");
        if (count == 0) return [];

        int stride = new T().TrimmedSize;
        if (stride <= 0)
            throw new InvalidDataException(
                $"unknown counted DAT stride in '{context}'");
        HSDStruct contiguous = Read(
            archive, source!._s, checked(count * stride), context);
        T[] result = new T[count];
        for (int index = 0; index < count; ++index)
        {
            result[index] = new T
            {
                _s = contiguous.GetEmbeddedStruct(index * stride, stride),
            };
        }
        return result;
    }

    public static HSDStruct Read(
        HSDRawFile archive,
        HSDStruct first,
        int length,
        string context)
    {
        int start = archive.GetOffsetFromStruct(first);
        if (start < 0 || length <= 0)
            throw new InvalidDataException(
                $"unmapped counted DAT array in '{context}'");

        List<(int Offset, HSDStruct Struct)> structs = GetSnapshot(archive).Nodes;
        byte[] bytes = new byte[length];
        bool[] covered = new bool[length];
        HSDStruct output = new(bytes);
        int end = checked(start + length);
        foreach ((int offset, HSDStruct item) in structs)
        {
            int itemEnd = checked(offset + item.Length);
            int copyStart = Math.Max(start, offset);
            int copyEnd = Math.Min(end, itemEnd);
            if (copyStart >= copyEnd) continue;

            int sourceOffset = copyStart - offset;
            int outputOffset = copyStart - start;
            int copyLength = copyEnd - copyStart;
            item.GetData().AsSpan(sourceOffset, copyLength)
                .CopyTo(bytes.AsSpan(outputOffset, copyLength));
            covered.AsSpan(outputOffset, copyLength).Fill(true);
            foreach ((int pointerOffset, HSDStruct target) in item.References)
            {
                int absolute = checked(offset + pointerOffset);
                if (absolute >= start && absolute < end)
                    output.SetReferenceStruct(absolute - start, target);
            }
        }
        int missing = Array.FindIndex(covered, value => !value);
        if (missing >= 0)
            throw new InvalidDataException(
                $"counted DAT array has a gap at 0x{missing:X} in '{context}'");
        return output;
    }
}
