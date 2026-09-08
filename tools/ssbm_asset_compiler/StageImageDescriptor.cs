using HSDRaw;
using HSDRaw.Common;

internal static class StageImageDescriptor
{
    public static HSD_Image Discover(HSDStruct source, string provenance)
    {
        HSD_Image image = new() { _s = source };
        if (source.Length < image.TrimmedSize)
            throw new InvalidDataException(
                $"truncated public stage image '{provenance}'");
        image.DiscoverScalarLayout();
        foreach ((int offset, int width) in new (int, int)[]
                 { (4, 2), (6, 2), (8, 4), (12, 4), (16, 4), (20, 4) })
        {
            if (!source.ScalarFields.TryGetValue(offset, out int actual) ||
                actual != width)
                throw new InvalidDataException(
                    $"untyped public stage image '{provenance}' at {offset}+{width}");
        }
        return image;
    }
}
