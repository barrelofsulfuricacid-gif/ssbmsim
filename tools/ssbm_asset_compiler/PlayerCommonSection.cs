using System.Buffers.Binary;
using HSDRaw;

internal sealed record PlayerCommonAsset(
    string Path,
    string RootName,
    uint[] Words);

internal static class PlayerCommonSection
{
    public const string Name = "player.common_data.v1";
    public const uint Schema = 1;
    public const int HeaderSize = 32;
    public const int WordCount = 0x184 / sizeof(uint);
    public const int WordSize = sizeof(uint);

    public static PlayerCommonAsset Read(
        string path,
        string rootName,
        HSDAccessor root)
    {
        HSDAccessor? data = root._s.GetReference<HSDAccessor>(0);
        if (data is null || data._s.Length < WordCount * WordSize)
        {
            throw new InvalidDataException(
                $"player common data in '{path}:{rootName}' is shorter than 0x184 bytes");
        }
        uint[] words = new uint[WordCount];
        for (int index = 0; index < words.Length; ++index)
            words[index] = data._s.GetUInt32(index * WordSize);
        return new PlayerCommonAsset(path, rootName, words);
    }

    public static byte[] Build(PlayerCommonAsset asset)
    {
        if (asset.Words.Length != WordCount)
            throw new InvalidDataException("unexpected player common word count");
        byte[] result = new byte[HeaderSize + WordCount * WordSize];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, WordCount);
        WriteU32(span, 8, WordSize);
        WriteU32(span, 12, HeaderSize);
        WriteU64(span, 16, StableNameHash(asset.Path));
        WriteU64(span, 24, StableNameHash(asset.RootName));
        for (int index = 0; index < asset.Words.Length; ++index)
            WriteU32(span, HeaderSize + index * WordSize, asset.Words[index]);
        return result;
    }

    private static ulong StableNameHash(string value)
    {
        ulong hash = 14695981039346656037UL;
        foreach (byte item in System.Text.Encoding.UTF8.GetBytes(value))
        {
            hash ^= item;
            hash *= 1099511628211UL;
        }
        return hash;
    }

    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);

    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}
