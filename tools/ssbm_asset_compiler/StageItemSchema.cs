using HSDRaw;
using HSDRaw.Melee.Gr;
using HSDRaw.Melee.Pl;

internal static class StageItemSchema
{
    public static void Restore(HSDRawFile archive, SBM_MapItem item, string provenance)
    {
        // The six legal archives contain only It_Kind_Heiho (210) itemdata.
        // doldecomp 32420c5f464f itheiho.c:it_803F83F0 selects descriptor
        // indices {-1, 0, -1, -1, 2}. ItemStateArray[8] is a source capacity,
        // not the on-disc length: reading eight would consume the next Article.
        int descriptorCount = item.Index switch
        {
            210 => 3,
            _ => throw new InvalidDataException(
                $"untyped legal-stage item {item.Index} in '{provenance}'"),
        };
        SBM_Article article = item.Article
            ?? throw new InvalidDataException($"missing stage article in '{provenance}'");
        HSDArrayAccessor<SBM_ItemState> states = article.ItemState
            ?? throw new InvalidDataException($"missing stage item states in '{provenance}'");
        HSDStruct restored = DatStructRange.Read(archive, states._s,
            descriptorCount * 0x10, $"{provenance}:item={item.Index}:states");
        states._s.SetData(restored.GetData());
        states._s.References.Clear();
        foreach ((int offset, HSDStruct target) in restored.References)
            states._s.SetReferenceStruct(offset, target);
        states.DiscoverScalarLayout();

        // it_802D8EC8 reads **(s32**)Article::x4_specialAttributes for the
        // damage threshold. Its pointed payload must be typed independently
        // of the enclosing scalar/pointer table. Preserve unknown tail bytes.
        HSDStruct? damage = article.ParametersExt?._s
            .GetReference<HSDAccessor>(0)?._s;
        if (damage is null || damage.Length < 4)
            throw new InvalidDataException($"missing stage damage threshold in '{provenance}'");
        _ = damage.GetInt32(0);
    }
}
