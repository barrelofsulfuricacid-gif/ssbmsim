using HSDRaw;
using HSDRaw.Melee.Pl;

internal static class ItemStateExtent
{
    // Minimum descriptor counts: max(nonnegative anim_id)+1 in the 43
    // ItemStateTable providers registered by it_803F14C4, doldecomp ae5898ee.
    // Per-provider hashes and animation IDs: tools/ssbm_common_item_state_extents.json.
    // Public DAT roots and external-link cells can split these C arrays.
    // The source's nominal ItemStateArray[8] is not an allocation bound.
    internal static readonly int[] CommonMinimumRows = [
        2, 3, 4, 2, 5, 4, 7, 4, 0, 0, 1, 1, 2, 8, 1, 1,
        2, 2, 0, 3, 3, 1, 1, 2, 5, 5, 1, 1, 2, 3, 1, 0,
        0, 1, 2, 1, 1, 2, 10, 1, 1, 1, 1,
    ];

    public static void RestoreCommon(HSDRawFile archive, SBM_ArticlePointer? items)
    {
        SBM_Article[] slots = items?.Articles
            ?? throw new InvalidDataException("missing common item articles");
        // The DAT pointer table also reserves null slots up to Pokemon kinds;
        // only the first 43 entries have common-item logic registrations.
        if (slots.Length < CommonMinimumRows.Length)
            throw new InvalidDataException("unexpected common item article count");
        for (int i = 0; i < CommonMinimumRows.Length; ++i)
            Restore(archive, slots[i], CommonMinimumRows[i], $"ItCo.dat item {i}");
    }

    internal static void Restore(HSDRawFile archive, SBM_Article? article,
        int minimumRows, string context)
    {
        if (minimumRows < 0) throw new InvalidDataException(context);
        if (minimumRows == 0) return;
        HSDStruct original = article?.ItemState?._s
            ?? throw new InvalidDataException($"missing item state array: {context}");
        int required = checked(minimumRows * 16);
        if (original.Length >= required) return;
        // Read the original fragments after external-link initialization, so
        // null external pointers and concrete local relocations stay distinct.
        HSDStruct restored = DatStructRange.Read(archive, original, required, context);
        original.ClearScalarLayout();
        original.References.Clear();
        original.SetData(restored.GetData());
        foreach ((int offset, HSDStruct target) in restored.References)
            original.SetReferenceStruct(offset, target);
    }
}
