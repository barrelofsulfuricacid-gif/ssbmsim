using HSDRaw;

// FtPartsVisLookup[model_num] -> TempS[count] -> byte[count]. Auxiliary
// fighter tables use this same schema even when reached through x48_items.
internal static class FighterVisibilityLayout
{
    public static void Discover(HSDStruct lookup, int modelCount, string provenance)
    {
        if (modelCount < 0 || modelCount > 11 || lookup.Length < modelCount * 8)
            throw new InvalidDataException($"{provenance}: invalid visibility model extent");
        for (int model = 0; model < modelCount; ++model)
        {
            int offset = model * 8;
            int count = lookup.GetInt32(offset);
            HSDStruct? variants = ArrayTarget(lookup, offset + 4, count, 8, provenance);
            for (int variant = 0; variant < count; ++variant)
            {
                int entry = variant * 8;
                int partCount = variants!.GetInt32(entry);
                // The leaves are byte indices, never arrays of endian-swapped words.
                _ = ArrayTarget(variants, entry + 4, partCount, 1, provenance);
            }
        }
    }

    private static HSDStruct? ArrayTarget(
        HSDStruct source, int offset, int count, int stride, string provenance)
    {
        source.References.TryGetValue(offset, out HSDStruct? target);
        if (count < 0 || (count > 0 &&
            (target is null || count > target.Length / stride)))
            throw new InvalidDataException($"{provenance}: invalid visibility array at {offset}");
        return target;
    }
}
