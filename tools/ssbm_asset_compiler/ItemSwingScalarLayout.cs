using HSDRaw;

internal static class ItemSwingScalarLayout
{
    // Fighter_LoadCommonData pData[2], indexed by ftswing.c:
    // six weapon classes, five attack variants per class.
    internal const int ByteCount = 6 * 5 * sizeof(uint);

    internal static void Discover(HSDStruct root)
    {
        HSDStruct? table = root.Length >= 12
            ? root.GetReference<HSDAccessor>(8)?._s : null;
        if (table is null || table.Length < ByteCount)
            throw new InvalidDataException(
                "PlCo.dat:ftLoadCommonData is missing the complete 6x5 " +
                "Fighter_804D654C item-swing speed table");
        for (int offset = 0; offset < ByteCount; offset += sizeof(uint))
            _ = table.GetUInt32(offset);
    }
}
