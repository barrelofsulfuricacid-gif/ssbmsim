using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.Melee.Pl;

internal static class ArticleAuxiliaryGraphs
{
    internal sealed record JointSchema(string File, int Slot, int MinimumLength, int[] JointOffsets);
    internal sealed record FighterJointSchema(string File, int Slot);

    // Both OnLoad functions pass item_list[6] directly to ftParts_800753D4
    // as HSD_Joint*. These are fighter attachment trees, not SBM_Article.
    internal static readonly FighterJointSchema[] FighterJointSchemas = [
        new("PlLk.dat", 6),
        new("PlCl.dat", 6),
    ];

    // Original OnLoad item registrations and attribute structs in itCharItems.h
    // and itYoyo.h. A relocation alone does not type the descendant graph.
    internal static readonly JointSchema[] JointSchemas = [
        new("PlLk.dat", 1, 0x64, [0x44, 0x48]),
        new("PlCl.dat", 1, 0x64, [0x44, 0x48]),
        new("PlLk.dat", 2, 0x60, [0x54, 0x58, 0x5C]),
        new("PlCl.dat", 2, 0x60, [0x54, 0x58, 0x5C]),
        new("PlLk.dat", 3, 0x2C, [0x24, 0x28]),
        new("PlCl.dat", 3, 0x2C, [0x24, 0x28]),
        new("PlSs.dat", 3, 0xB0, [0x64, 0x68, 0x6C, 0x70]),
        // The source's unused trailing x5C word is outside this DAT node.
        new("PlNs.dat", 10, 0x5C, [0x50, 0x54]),
        new("PlSk.dat", 3, 0x6C, [0x64, 0x68]),
        // ftPp_OnLoad registers this shared article only for Popo. Nana's
        // slot 2 is a different, unused record without these graph pointers.
        new("PlPp.dat", 2, 0x2C, [0x24, 0x28]),
    ];
    // ftSs_Init_CreateThrowGrappleBeam consumes item_list[4] as UNK_SAMUS_S1,
    // not an Article: joint, four throw animation pointers, animation, material.
    internal static void DiscoverFighterAuxiliary(string relative, SBM_ArticlePointer? items)
    {
        foreach (FighterJointSchema schema in FighterJointSchemas.Where(s => s.File == relative))
        {
            int offset = checked(schema.Slot * sizeof(uint));
            if (items is null || items._s.Length < offset + sizeof(uint) ||
                !items._s.References.TryGetValue(offset, out HSDStruct? data) ||
                data.Length < 0x40)
                throw new InvalidDataException($"{relative} fighter joint slot {schema.Slot} is missing or truncated");
            HSD_JOBJ root = new() { _s = data };
            root.DiscoverScalarLayout();
            foreach (HSD_JOBJ joint in root.TreeList)
            {
                foreach (int scalar in new[] { 4, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0x30, 0x34 })
                {
                    if (!joint._s.ScalarFields.TryGetValue(scalar, out int width) || width != 4)
                        throw new InvalidDataException($"{relative} fighter joint slot {schema.Slot} has an untyped scalar at {scalar:X}");
                }
            }
        }
        if (relative != "PlSs.dat") return;
        if (items is null || !items._s.References.TryGetValue(16, out HSDStruct? beam) || beam.Length < 16)
            throw new InvalidDataException("Samus throw grapple descriptor is missing or truncated");
        beam.GetReference<HSD_JOBJ>(0)?.DiscoverScalarLayout();
        DiscoverTable<HSD_AnimJoint>(beam, 4);
        beam.GetReference<HSD_AnimJoint>(8)?.DiscoverScalarLayout();
        beam.GetReference<HSD_MatAnimJoint>(12)?.DiscoverScalarLayout();
    }

    internal static void RestoreExtent(HSDRawFile archive, string relative, int slot, HSDStruct attributes)
    {
        if (relative != "PlSs.dat" || slot != 3 || attributes.Length >= 0xB0) return;
        HSDStruct complete = DatStructRange.Read(archive, attributes, 0xB0,
            "itSamusGrappleAttributes");
        attributes.SetData(complete.GetData());
        attributes.References.Clear();
        foreach (var entry in complete.References)
            attributes.SetReferenceStruct(entry.Key, entry.Value);
    }

    // itSamusGrappleAttributes (itCharItems.h), consumed by itsamusgrapple.c:
    // four joint descriptors and five triples of animation pointer tables.
    internal static void Discover(string relative, int slot, HSDStruct attributes)
    {
        JointSchema? schema = JointSchemas.SingleOrDefault(s => s.File == relative && s.Slot == slot);
        if (schema is null) return;
        if (attributes.Length < schema.MinimumLength)
            throw new InvalidDataException($"{relative} article {slot} auxiliary attributes are truncated");
        foreach (int offset in schema.JointOffsets)
            attributes.GetReference<HSD_JOBJ>(offset)?.DiscoverScalarLayout();
        if ((relative is "PlLk.dat" or "PlCl.dat") && slot == 1)
        {
            DiscoverAnimationBundle(attributes, 0x4C);
            DiscoverAnimationBundle(attributes, 0x58);
        }
        if (relative == "PlNs.dat" && slot == 10)
            attributes.GetReference<HSD_MatAnimJoint>(0x58)?.DiscoverScalarLayout();
        if (relative != "PlSs.dat" || slot != 3) return;
        for (int offset = 0x74; offset <= 0xA4; offset += 12)
        {
            DiscoverTable<HSD_AnimJoint>(attributes, offset);
            DiscoverTable<HSD_MatAnimJoint>(attributes, offset + 4);
            DiscoverTable<HSD_ShapeAnimJoint>(attributes, offset + 8);
        }
    }

    private static void DiscoverAnimationBundle(HSDStruct owner, int offset)
    {
        owner.GetReference<HSD_AnimJoint>(offset)?.DiscoverScalarLayout();
        owner.GetReference<HSD_MatAnimJoint>(offset + 4)?.DiscoverScalarLayout();
        owner.GetReference<HSD_ShapeAnimJoint>(offset + 8)?.DiscoverScalarLayout();
    }

    private static void DiscoverTable<T>(HSDStruct owner, int offset)
        where T : HSDAccessor, new()
    {
        if (!owner.References.TryGetValue(offset, out HSDStruct? table)) return;
        foreach (var entry in table.References)
        {
            if ((entry.Key & 3) != 0 || entry.Key < 0 || entry.Key > table.Length - 4)
                throw new InvalidDataException($"invalid animation pointer table at {offset:X}");
            new T { _s = entry.Value }.DiscoverScalarLayout();
        }
    }
}
