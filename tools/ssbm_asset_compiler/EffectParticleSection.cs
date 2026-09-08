using System.Buffers.Binary;
using System.Numerics;
using System.Text;
using HSDRaw.Common;
using HSDRaw.Melee.Ef;

internal static class EffectParticleSection
{
    public const string Name = "effect.particle_banks.v2";
    public const uint Schema = 2;
    public const int BankRecordSize = 64;
    public const int GeneratorRecordSize = 80;
    public const int TextureRecordSize = 32;
    private const int HeaderSize = 64;

    public static EffectParticleBank Read(
        string path,
        string rootName,
        SBM_EffectTable table)
    {
        HSD_ParticleGroup? particles = table.Particles;
        HSD_TEXGraphicBank? textures = table.TextureGraphics;
        HSD_ParticleGenerator[] sourceGenerators = particles?.Generators ?? [];
        EffectParticleGenerator?[] generators = sourceGenerators
            .Select(generator => generator.IsBlank()
                ? null
                : new EffectParticleGenerator(
                    checked((ushort)((int)generator.TypeShape |
                        (int)generator.Flags)),
                    generator.TexGroup,
                    generator.GenLife,
                    generator.Life,
                    checked((uint)generator.Kind),
                    BitConverter.SingleToUInt32Bits(generator.Gravity),
                    BitConverter.SingleToUInt32Bits(generator.Friction),
                    BitConverter.SingleToUInt32Bits(generator.VX),
                    BitConverter.SingleToUInt32Bits(generator.VY),
                    BitConverter.SingleToUInt32Bits(generator.VZ),
                    BitConverter.SingleToUInt32Bits(generator.Radius),
                    BitConverter.SingleToUInt32Bits(generator.Angle),
                    BitConverter.SingleToUInt32Bits(generator.Random),
                    BitConverter.SingleToUInt32Bits(generator.Size),
                    BitConverter.SingleToUInt32Bits(generator.Param1),
                    BitConverter.SingleToUInt32Bits(generator.Param2),
                    BitConverter.SingleToUInt32Bits(generator.Param3),
                    NormalizeBytecode(generator.TrackData, path, rootName)))
            .ToArray();
        EffectParticleTexture[] textureGroups = (textures?.ParticleImages ?? [])
            .Select(texture => new EffectParticleTexture(
                checked((uint)texture.ImageCount),
                checked((uint)texture.ImageFormat),
                checked((uint)texture.PaletteFormat),
                checked((uint)texture.Width),
                checked((uint)texture.Height),
                texture._s.GetUInt16(0x14),
                texture._s.GetUInt16(0x16)))
            .ToArray();

        return new(
            path,
            rootName,
            particles?.Unknown1 ?? 0,
            particles?.Unknown2 ?? 0,
            particles?.EffectIDStart ?? 0,
            checked((uint)table.Models.Length),
            particles is not null,
            textures is not null,
            generators,
            textureGroups);
    }

    public static byte[] Build(IReadOnlyList<EffectParticleBank> banks)
    {
        int generatorCount = banks.Sum(bank => bank.Generators.Length);
        int textureCount = banks.Sum(bank => bank.Textures.Length);
        int bankOffset = HeaderSize;
        int generatorOffset = Align8(checked(
            bankOffset + banks.Count * BankRecordSize));
        int textureOffset = Align8(checked(
            generatorOffset + generatorCount * GeneratorRecordSize));
        int blobOffset = Align8(checked(
            textureOffset + textureCount * TextureRecordSize));
        int blobBytes = banks.Sum(bank => bank.Generators.Sum(
            generator => generator?.Bytecode.Length ?? 0));
        byte[] result = new byte[checked(blobOffset + blobBytes)];
        Span<byte> span = result;

        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)banks.Count));
        WriteU32(span, 8, checked((uint)generatorCount));
        WriteU32(span, 12, checked((uint)textureCount));
        WriteU32(span, 16, BankRecordSize);
        WriteU32(span, 20, GeneratorRecordSize);
        WriteU32(span, 24, TextureRecordSize);
        WriteU64(span, 32, checked((ulong)bankOffset));
        WriteU64(span, 40, checked((ulong)generatorOffset));
        WriteU64(span, 48, checked((ulong)textureOffset));
        WriteU64(span, 56, checked((ulong)blobOffset));

        int nextGenerator = 0;
        int nextTexture = 0;
        int nextBlob = blobOffset;
        for (int bankIndex = 0; bankIndex < banks.Count; ++bankIndex)
        {
            EffectParticleBank bank = banks[bankIndex];
            int record = bankOffset + bankIndex * BankRecordSize;
            WriteU64(span, record, StableNameHash(bank.Path));
            WriteU64(span, record + 8, StableNameHash(bank.RootName));
            WriteI16(span, record + 16, bank.Unknown1);
            WriteI16(span, record + 18, bank.Unknown2);
            WriteI32(span, record + 20, bank.EffectIdStart);
            WriteU32(span, record + 24, checked((uint)nextGenerator));
            WriteU32(span, record + 28, checked((uint)bank.Generators.Length));
            WriteU32(span, record + 32, checked((uint)nextTexture));
            WriteU32(span, record + 36, checked((uint)bank.Textures.Length));
            WriteU32(span, record + 40, bank.ModelCount);
            WriteU32(span, record + 44,
                (bank.ParticlesPresent ? 1U : 0U) |
                (bank.TexturesPresent ? 2U : 0U));

            foreach (EffectParticleGenerator? generator in bank.Generators)
            {
                int generatorRecord = generatorOffset +
                    nextGenerator++ * GeneratorRecordSize;
                if (generator is null)
                    continue;
                WriteU32(span, generatorRecord, 1);
                WriteU16(span, generatorRecord + 4, generator.TypeFlags);
                WriteI16(span, generatorRecord + 6, generator.TextureGroup);
                WriteI16(span, generatorRecord + 8, generator.GeneratorLife);
                WriteI16(span, generatorRecord + 10, generator.ParticleLife);
                WriteU32(span, generatorRecord + 12, generator.Kind);
                for (int scalar = 0; scalar < generator.ScalarBits.Length; ++scalar)
                    WriteU32(span, generatorRecord + 16 + scalar * sizeof(uint),
                        generator.ScalarBits[scalar]);
                WriteU64(span, generatorRecord + 64, checked((ulong)nextBlob));
                WriteU32(span, generatorRecord + 72,
                    checked((uint)generator.Bytecode.Length));
                generator.Bytecode.CopyTo(span[nextBlob..]);
                nextBlob += generator.Bytecode.Length;
            }
            foreach (EffectParticleTexture texture in bank.Textures)
            {
                int textureRecord = textureOffset +
                    nextTexture++ * TextureRecordSize;
                WriteU32(span, textureRecord, texture.ImageCount);
                WriteU32(span, textureRecord + 4, texture.Format);
                WriteU32(span, textureRecord + 8, texture.PaletteFormat);
                WriteU32(span, textureRecord + 12, texture.Width);
                WriteU32(span, textureRecord + 16, texture.Height);
                WriteU16(span, textureRecord + 20, texture.PaletteCount);
                WriteU16(span, textureRecord + 22, texture.PaletteFlags);
            }
        }
        if (nextGenerator != generatorCount || nextTexture != textureCount ||
            nextBlob != result.Length)
            throw new InvalidDataException("effect particle layout size mismatch");
        return result;
    }

    private static byte[] NormalizeBytecode(
        byte[] source,
        string path,
        string rootName)
    {
        byte[] result = source.ToArray();
        int cursor = 0;
        while (cursor < result.Length)
        {
            byte opcode = result[cursor++];
            if (opcode < 0x80)
            {
                if ((opcode & 0x20) != 0)
                    Require(result, ref cursor, 1, path, rootName, opcode);
                if ((opcode & 0xC0) == 0x40)
                    Require(result, ref cursor, 1, path, rootName, opcode);
                continue;
            }

            if (opcode is >= 0x80 and <= 0x9F)
            {
                for (int component = 0; component < 3; ++component)
                    if ((opcode & (1 << component)) != 0)
                        ReverseFloat(result, ref cursor, path, rootName, opcode);
            }
            else
            {
                string operands = OperandLayout(opcode) ?? throw new
                    InvalidDataException(
                        $"unknown particle opcode 0x{opcode:X2} in " +
                        $"'{path}:{rootName}'");
                foreach (char operand in operands)
                {
                    switch (operand)
                    {
                    case 'b':
                        Require(result, ref cursor, 1, path, rootName, opcode);
                        break;
                    case 's':
                        Require(result, ref cursor, 2, path, rootName, opcode);
                        break;
                    case 'f':
                        ReverseFloat(result, ref cursor, path, rootName, opcode);
                        break;
                    case 'e':
                        Require(result, ref cursor, 1, path, rootName, opcode);
                        if ((result[cursor - 1] & 0x80) != 0)
                            Require(result, ref cursor, 1, path, rootName, opcode);
                        break;
                    case 'c':
                        Require(result, ref cursor,
                            BitOperations.PopCount((uint)(opcode & 0x0F)),
                            path, rootName, opcode);
                        break;
                    case 'r':
                    {
                        Require(result, ref cursor, 2, path, rootName, opcode);
                        byte behavior = result[cursor - 2];
                        Require(result, ref cursor,
                            BitOperations.PopCount((uint)(behavior & 0x0F)),
                            path, rootName, opcode);
                        break;
                    }
                    case 'm':
                    {
                        Require(result, ref cursor, 1, path, rootName, opcode);
                        byte behavior = result[cursor - 1];
                        if ((behavior & 0x01) != 0)
                            Require(result, ref cursor, 1, path, rootName, opcode);
                        if ((behavior & 0x08) != 0)
                            Require(result, ref cursor, 1, path, rootName, opcode);
                        break;
                    }
                    default:
                        throw new InvalidDataException(
                            $"invalid particle operand descriptor '{operand}'");
                    }
                }
            }

            if (opcode is 0xFD or 0xFE or 0xFF)
            {
                Array.Resize(ref result, cursor);
                return result;
            }
        }
        throw new InvalidDataException(
            $"unterminated particle bytecode in '{path}:{rootName}'");
    }

    private static string? OperandLayout(byte opcode) => opcode switch
    {
        0xA0 => "ef", 0xA1 => "", 0xA2 => "f", 0xA3 => "f",
        0xA4 => "bb", 0xA5 => "bb", 0xA6 => "ss", 0xA7 => "b",
        0xA8 => "fff", 0xA9 => "f", 0xAA => "ss", 0xAB => "f",
        0xAC => "eff", 0xAD => "", 0xAE => "", 0xAF => "",
        0xB0 => "", 0xB1 => "", 0xB2 => "", 0xB3 => "ebbb",
        0xB4 => "", 0xB5 => "", 0xB6 => "ef", 0xB7 => "b",
        0xB8 => "bff", 0xB9 => "bb", 0xBA => "bbbb", 0xBB => "bbbb",
        0xBC => "bb", 0xBD => "ff", 0xBE => "fff", 0xBF => "b",
        >= 0xC0 and <= 0xCF => "ec",
        >= 0xD0 and <= 0xDF => "ec",
        0xE0 => "bbbb", 0xE1 => "b", 0xE2 => "", 0xE3 => "b",
        0xE4 => "b", 0xE5 => "b", 0xE6 => "", 0xE7 => "",
        0xE8 => "f", 0xE9 => "r", 0xEA => "em", 0xEB => "em",
        0xEC => "bf", 0xED or 0xEE => "ffb", 0xEF => "sb",
        0xF0 => "sb", 0xF1 => "sm", >= 0xF2 and <= 0xF9 => "sm",
        0xFA => "b", 0xFB => "", 0xFC => "", 0xFD => "",
        0xFE => "", 0xFF => "",
        _ => null,
    };

    private static void ReverseFloat(
        byte[] bytes,
        ref int cursor,
        string path,
        string rootName,
        byte opcode)
    {
        int start = cursor;
        Require(bytes, ref cursor, sizeof(float), path, rootName, opcode);
        Array.Reverse(bytes, start, sizeof(float));
    }

    private static void Require(
        byte[] bytes,
        ref int cursor,
        int count,
        string path,
        string rootName,
        byte opcode)
    {
        if (count < 0 || cursor > bytes.Length - count)
            throw new InvalidDataException(
                $"truncated particle opcode 0x{opcode:X2} in " +
                $"'{path}:{rootName}' at byte {cursor}");
        cursor += count;
    }

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

    private static void WriteU16(Span<byte> bytes, int offset, ushort value) =>
        BinaryPrimitives.WriteUInt16LittleEndian(bytes[offset..], value);
    private static void WriteI16(Span<byte> bytes, int offset, short value) =>
        BinaryPrimitives.WriteInt16LittleEndian(bytes[offset..], value);
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record EffectParticleBank(
    string Path,
    string RootName,
    short Unknown1,
    short Unknown2,
    int EffectIdStart,
    uint ModelCount,
    bool ParticlesPresent,
    bool TexturesPresent,
    EffectParticleGenerator?[] Generators,
    EffectParticleTexture[] Textures);

internal sealed record EffectParticleGenerator(
    ushort TypeFlags,
    short TextureGroup,
    short GeneratorLife,
    short ParticleLife,
    uint Kind,
    uint GravityBits,
    uint FrictionBits,
    uint VelocityXBits,
    uint VelocityYBits,
    uint VelocityZBits,
    uint RadiusBits,
    uint AngleBits,
    uint RandomBits,
    uint SizeBits,
    uint Param1Bits,
    uint Param2Bits,
    uint Param3Bits,
    byte[] Bytecode)
{
    public uint[] ScalarBits =>
    [
        GravityBits, FrictionBits, VelocityXBits, VelocityYBits, VelocityZBits,
        RadiusBits, AngleBits, RandomBits, SizeBits, Param1Bits, Param2Bits,
        Param3Bits,
    ];
}

internal readonly record struct EffectParticleTexture(
    uint ImageCount,
    uint Format,
    uint PaletteFormat,
    uint Width,
    uint Height,
    ushort PaletteCount,
    ushort PaletteFlags);
