using System.Buffers.Binary;
using HSDRaw;

internal static class ArchiveExternalReferences
{
    // GALE01 lbArchive_InitializeDAT calls HSD_ArchiveLocateExtern(symbol, NULL)
    // for every external symbol. Link words are archive-relative offsets to the
    // next patch location, not asset pointers. No Melee caller rebinds them later.
    public static void ResolveToNull(HSDRawFile archive, ReadOnlySpan<byte> bytes,
        string provenance)
    {
        if (archive.References.Count == 0) return;
        DatStructRange.Capture(archive);
        uint dataSize = BinaryPrimitives.ReadUInt32BigEndian(bytes.Slice(4, 4));
        HashSet<int> patched = [];
        foreach (HSDRootNode external in archive.References)
        {
            int offset = archive.GetOffsetFromStruct(external.Data._s) - 0x20;
            while ((uint)offset < dataSize)
            {
                if (!patched.Add(offset) || (offset & 3) != 0 ||
                    offset > bytes.Length - 0x24)
                    throw new InvalidDataException(
                        $"invalid external chain '{provenance}:{external.Name}' at {offset:X}");
                HSDStruct cell = DatStructRange.AtOffset(archive, offset + 0x20)
                    ?? throw new InvalidDataException(
                        $"unmapped external chain '{provenance}:{external.Name}' at {offset:X}");
                if (cell.Length < 4)
                    throw new InvalidDataException($"truncated external cell in '{provenance}'");
                uint next = BinaryPrimitives.ReadUInt32BigEndian(bytes.Slice(offset + 0x20, 4));
                cell.References.Remove(0);
                cell.SetInt32(0, 0);
                offset = unchecked((int)next);
            }
        }
    }
}
