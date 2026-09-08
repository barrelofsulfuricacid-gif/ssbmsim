using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Melee.Gr;

internal sealed record StageGroundParamAsset(
    string Path,
    string RootName,
    byte[] NativeImage,
    byte[][] StageParams);

internal static class StageGroundParamSection
{
    public const string Name = "stage.ground_param.v1";
    public const uint Schema = 1;
    public const int HeaderSize = 40;
    public const int RecordSize = 48;
    public const int NativeImageSize = 0xDC;
    public const int StageParamSize = 0x64;

    public static StageGroundParamAsset Read(
        string path,
        string rootName,
        SBM_GroundParam ground)
    {
        if (ground._s.Length < NativeImageSize)
            throw new InvalidDataException($"ground parameters in '{path}:{rootName}' are shorter than 0xDC bytes");

        int count = ground._s.GetInt32(0xB4);
        if (count < 0)
            throw new InvalidDataException($"negative stage parameter count in '{path}:{rootName}'");
        HSDAccessor? rows = ground._s.GetReference<HSDAccessor>(0xB0);
        if ((count == 0) != (rows is null || rows._s.Length == 0) ||
            (count != 0 && rows!._s.Length < checked(count * StageParamSize)))
        {
            throw new InvalidDataException($"invalid stage parameter rows in '{path}:{rootName}'");
        }

        byte[] image = new byte[NativeImageSize];
        CopyU32(ground._s, image, 0x00);
        CopyI16(ground._s, image, 0x04);
        CopyI16(ground._s, image, 0x08);
        CopyI16(ground._s, image, 0x0A);
        for (int offset = 0x0C; offset <= 0x28; offset += 4)
            CopyU32(ground._s, image, offset);
        CopyI16(ground._s, image, 0x2C);
        CopyI16(ground._s, image, 0x2E);
        for (int offset = 0x30; offset <= 0x64; offset += 4)
            CopyU32(ground._s, image, offset);
        for (int offset = 0x68; offset <= 0xAE; offset += 2)
            CopyI16(ground._s, image, offset);
        // 0xB0 is a host pointer and is rebuilt after the pack is mapped.
        WriteU32(image, 0xB4, checked((uint)count));
        for (int offset = 0xB8; offset < NativeImageSize; ++offset)
            image[offset] = ground._s.GetByte(offset);

        byte[][] outputRows = new byte[count][];
        for (int rowIndex = 0; rowIndex < count; ++rowIndex)
        {
            byte[] row = new byte[StageParamSize];
            int sourceOffset = rowIndex * StageParamSize;
            for (int offset = 0; offset <= 0x10; offset += 4)
                CopyU32(rows!._s, row, sourceOffset + offset, offset);
            for (int offset = 0x14; offset < StageParamSize; offset += 2)
                CopyI16(rows!._s, row, sourceOffset + offset, offset);
            outputRows[rowIndex] = row;
        }
        return new StageGroundParamAsset(path, rootName, image, outputRows);
    }

    public static byte[] Build(IReadOnlyList<StageGroundParamAsset> stages)
    {
        int recordsOffset = HeaderSize;
        int payloadOffset = Align8(checked(recordsOffset + stages.Count * RecordSize));
        int size = payloadOffset;
        foreach (StageGroundParamAsset stage in stages)
            size = checked(size + NativeImageSize + stage.StageParams.Length * StageParamSize);

        byte[] result = new byte[size];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)stages.Count));
        WriteU32(span, 8, RecordSize);
        WriteU32(span, 12, NativeImageSize);
        WriteU32(span, 16, StageParamSize);
        WriteU64(span, 24, checked((ulong)recordsOffset));
        WriteU64(span, 32, checked((ulong)payloadOffset));

        int dataOffset = payloadOffset;
        for (int index = 0; index < stages.Count; ++index)
        {
            StageGroundParamAsset stage = stages[index];
            if (stage.NativeImage.Length != NativeImageSize)
                throw new InvalidDataException($"unexpected ground parameter image size for '{stage.Path}'");
            int recordOffset = recordsOffset + index * RecordSize;
            int imageOffset = dataOffset;
            stage.NativeImage.CopyTo(span[imageOffset..]);
            dataOffset += NativeImageSize;
            int rowsOffset = dataOffset;
            foreach (byte[] row in stage.StageParams)
            {
                if (row.Length != StageParamSize)
                    throw new InvalidDataException($"unexpected stage parameter row size for '{stage.Path}'");
                row.CopyTo(span[dataOffset..]);
                dataOffset += StageParamSize;
            }

            WriteU64(span, recordOffset, StableNameHash(stage.Path));
            WriteU64(span, recordOffset + 8, StableNameHash(stage.RootName));
            WriteU64(span, recordOffset + 16, checked((ulong)imageOffset));
            WriteU64(span, recordOffset + 24, checked((ulong)rowsOffset));
            WriteU32(span, recordOffset + 32, checked((uint)stage.StageParams.Length));
        }
        if (dataOffset != result.Length)
            throw new InvalidDataException("stage ground parameter layout size mismatch");
        return result;
    }

    private static void CopyU32(HSDStruct source, byte[] destination, int offset) =>
        WriteU32(destination, offset, source.GetUInt32(offset));

    private static void CopyU32(
        HSDStruct source, byte[] destination, int sourceOffset, int destinationOffset) =>
        WriteU32(destination, destinationOffset, source.GetUInt32(sourceOffset));

    private static void CopyI16(HSDStruct source, byte[] destination, int offset) =>
        WriteI16(destination, offset, source.GetInt16(offset));

    private static void CopyI16(
        HSDStruct source, byte[] destination, int sourceOffset, int destinationOffset) =>
        WriteI16(destination, destinationOffset, source.GetInt16(sourceOffset));

    private static int Align8(int value) => checked((value + 7) & ~7);

    private static ulong StableNameHash(string value)
    {
        ulong hash = 14695981039346656037UL;
        foreach (byte item in Encoding.UTF8.GetBytes(value))
        {
            hash ^= item;
            hash *= 1099511628211UL;
        }
        return hash;
    }

    private static void WriteI16(Span<byte> bytes, int offset, short value) =>
        BinaryPrimitives.WriteInt16LittleEndian(bytes[offset..], value);

    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);

    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}
