using HSDRaw;

internal static class ArticleVisibilityLayout
{
    // All callers of it_8027CE64 consume attributes[0] as two pairs of
    // { u16 count; u16 padding; u8* indices }. This includes copied articles.
    internal static void DiscoverRoot(string file, string rootName, HSDStruct root)
    {
        if (file == "PlGw.dat" && rootName == "ftDataGamewatch")
        {
            HSDStruct articles = Target(root, 0x48, file);
            for (int slot = 0; slot < 10; ++slot)
                DiscoverArticle(Target(articles, slot * 4, file), $"{file}:article[{slot}]");
        }
        else if (file == "PlKbCpGw.dat" && rootName == "ftDataKirbyCopyGamewatch")
        {
            // ftKb_SpecialN_800F16D0 registers hat_dynamics[5] and [6].
            foreach (int slot in new[] { 5, 6 })
                DiscoverArticle(Target(root, 0xC + slot * 4, file), $"{file}:hat_dynamics[{slot}]");
        }
    }

    private static void DiscoverArticle(HSDStruct article, string provenance)
    {
        HSDStruct attributes = Target(article, 4, provenance);
        Discover(Target(attributes, 0, provenance), provenance);
    }

    private static HSDStruct Target(HSDStruct source, int offset, string provenance)
    {
        if (offset > source.Length - 4 ||
            !source.References.TryGetValue(offset, out HSDStruct? target))
            throw new InvalidDataException($"{provenance}: missing article visibility reference at {offset:X}");
        return target;
    }

    internal static void Discover(HSDStruct descriptor, string provenance)
    {
        if (descriptor.Length < 16)
            throw new InvalidDataException($"{provenance}: truncated article visibility descriptor");
        foreach (int offset in new[] { 0, 8 })
        {
            int count = descriptor.GetUInt16(offset);
            if (count != 0)
            {
                HSDStruct indices = Target(descriptor, offset + 4, provenance);
                if (indices.Length < count)
                    throw new InvalidDataException($"{provenance}: truncated article visibility indices");
            }
        }
    }
}
