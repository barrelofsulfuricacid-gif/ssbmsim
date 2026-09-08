using HSDRaw;

// Source-owned mixed-width ranges in Fighter::dat_attrs. Unlisted words are
// f32/s32/u32 storage; pointer relocations remain owned by the graph serializer.
internal static class FighterSpecialScalarLayout
{
    internal static IEnumerable<(int Offset, int Width)> Fields(string relative, int length)
    {
        string file = Path.GetFileName(relative);
        if ((length & 3) != 0 || (file == "PlYs.dat" && length < 0x138) ||
            (file == "PlKb.dat" && length < 0x38))
            throw new InvalidDataException($"invalid fighter special attribute extent in '{relative}': {length}");
        for (int offset = 0; offset < length; offset += 4)
        {
            // ftYoshiAttributes::x12C: 12 raw lookup bytes, read by CatchPull.
            if (file == "PlYs.dat" && offset >= 0x12C && offset < 0x138)
                continue;
            // ftKb_DatAttrs::jumpaerial_unk is s16 at 0x34; 0x36..37 is
            // padding. ftkirbyspecialn.c reads the halfword, not a u32.
            if (file == "PlKb.dat" && offset == 0x34)
                yield return (offset, 2);
            else
                yield return (offset, 4);
        }
    }

    internal static void Discover(string relative, HSDAccessor? attributes)
    {
        if (attributes is null) return;
        foreach (var field in Fields(relative, attributes._s.Length))
        {
            if (field.Width == 2) _ = attributes._s.GetInt16(field.Offset);
            else _ = attributes._s.GetUInt32(field.Offset);
        }
    }

    internal static void Validate(string relative, HSDAccessor? attributes)
    {
        if (attributes is null) return;
        var expected = Fields(relative, attributes._s.Length).ToDictionary(f => f.Offset, f => f.Width);
        foreach (var field in expected)
            if (!attributes._s.ScalarFields.TryGetValue(field.Key, out int width) || width != field.Value)
                throw new InvalidDataException($"missing fighter special scalar {field.Key:X}+{field.Value} in '{relative}'");
        foreach (var field in attributes._s.ScalarFields)
            if (!expected.TryGetValue(field.Key, out int width) || width != field.Value)
                throw new InvalidDataException($"unexpected fighter special scalar {field.Key:X}+{field.Value} in '{relative}'");
    }
}
