using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Melee.Pl;

internal static class FighterDynamicsSection
{
    public const string Name = "fighter.dynamics.v1";
    public const uint Schema = 1;
    public const int FighterRecordSize = 64;
    public const int DescriptorRecordSize = 32;
    public const int ParameterRecordSize = 60;
    public const int BubbleRecordSize = 20;
    public const int ApplyTableRecordSize = 16;
    private const int HeaderSize = 80;

    public static FighterDynamicsAsset Read(
        string path,
        string rootName,
        SBM_FighterData fighter)
    {
        SBM_PhysicsGroup? physics = fighter.Physics;
        if (physics is null)
            return new(path, rootName, false, [], [], []);

        SBM_DynamicDesc[] descriptorStorage = physics.DynamicDesc?.Array ?? [];
        SBM_DynamicHitBubble[] bubbleStorage = physics.Hitbubbles?.Array ?? [];
        if (physics.DynamicDescCount < 0 ||
            physics.DynamicHitBubbleCount < 0 ||
            descriptorStorage.Length < physics.DynamicDescCount ||
            bubbleStorage.Length < physics.DynamicHitBubbleCount)
        {
            throw new InvalidDataException(
                $"physics count mismatch in '{path}:{rootName}': " +
                $"descriptors {physics.DynamicDescCount}/{descriptorStorage.Length}, " +
                $"bubbles {physics.DynamicHitBubbleCount}/{bubbleStorage.Length}");
        }
        SBM_DynamicDesc[] sourceDescriptors = descriptorStorage
            .Take(physics.DynamicDescCount)
            .ToArray();
        SBM_DynamicHitBubble[] sourceBubbles = bubbleStorage
            .Take(physics.DynamicHitBubbleCount)
            .ToArray();
        DynamicDescriptor[] descriptors = sourceDescriptors.Select(source =>
        {
            SBM_DynamicParams[] parameterStorage = source.Parameters ?? [];
            int declared = source.ParameterCount;
            if (declared < 0 || parameterStorage.Length < declared)
            {
                throw new InvalidDataException(
                    $"dynamic parameter count mismatch in '{path}:{rootName}'");
            }
            SBM_DynamicParams[] parameters = parameterStorage.Take(declared).ToArray();
            return new DynamicDescriptor(
                source.BoneIndex,
                Bits(source.DragMultiplier),
                Bits(source.StiffnessMultiplier),
                Bits(source.GravityLengthCompensation),
                parameters.Select(ReadParameters).ToArray());
        }).ToArray();
        DynamicBubble[] bubbles = sourceBubbles.Select(source => new DynamicBubble(
            source.BoneIndex,
            [Bits(source.Z), Bits(source.Y), Bits(source.X), Bits(source.Size)])).ToArray();

        HSDFixedLengthPointerArrayAccessor<HSDIntArray>? sourceTables =
            physics.BoneApplyTable;
        HSDIntArray[] tableStorage = sourceTables?.Array ?? [];
        ApplyTable[] tables = tableStorage
            .Select(source => source is null
                ? new ApplyTable(false, [])
                : new ApplyTable(true, source.Array)).ToArray();
        return new(path, rootName, true, descriptors, bubbles, tables);
    }

    public static byte[] Build(IReadOnlyList<FighterDynamicsAsset> fighters)
    {
        int descriptorCount = fighters.Sum(fighter => fighter.Descriptors.Length);
        int parameterCount = fighters.Sum(fighter =>
            fighter.Descriptors.Sum(descriptor => descriptor.Parameters.Length));
        int bubbleCount = fighters.Sum(fighter => fighter.Bubbles.Length);
        int tableCount = fighters.Sum(fighter => fighter.ApplyTables.Length);
        int valueCount = fighters.Sum(fighter =>
            fighter.ApplyTables.Sum(table => table.Values.Length));

        int fightersOffset = HeaderSize;
        int descriptorsOffset = Align8(checked(
            fightersOffset + fighters.Count * FighterRecordSize));
        int parametersOffset = Align8(checked(
            descriptorsOffset + descriptorCount * DescriptorRecordSize));
        int bubblesOffset = Align8(checked(
            parametersOffset + parameterCount * ParameterRecordSize));
        int tablesOffset = Align8(checked(
            bubblesOffset + bubbleCount * BubbleRecordSize));
        int valuesOffset = Align8(checked(
            tablesOffset + tableCount * ApplyTableRecordSize));
        byte[] result = new byte[checked(valuesOffset + valueCount * sizeof(int))];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)fighters.Count));
        WriteU32(span, 8, FighterRecordSize);
        WriteU32(span, 12, DescriptorRecordSize);
        WriteU32(span, 16, ParameterRecordSize);
        WriteU32(span, 20, BubbleRecordSize);
        WriteU32(span, 24, ApplyTableRecordSize);
        WriteU64(span, 32, checked((ulong)fightersOffset));
        WriteU64(span, 40, checked((ulong)descriptorsOffset));
        WriteU64(span, 48, checked((ulong)parametersOffset));
        WriteU64(span, 56, checked((ulong)bubblesOffset));
        WriteU64(span, 64, checked((ulong)tablesOffset));
        WriteU64(span, 72, checked((ulong)valuesOffset));

        int descriptorIndex = 0;
        int parameterIndex = 0;
        int bubbleIndex = 0;
        int tableIndex = 0;
        int valueIndex = 0;
        for (int fighterIndex = 0; fighterIndex < fighters.Count; ++fighterIndex)
        {
            FighterDynamicsAsset fighter = fighters[fighterIndex];
            int fighterRecord = fightersOffset + fighterIndex * FighterRecordSize;
            WriteU64(span, fighterRecord, StableNameHash(fighter.Path));
            WriteU64(span, fighterRecord + 8, StableNameHash(fighter.RootName));
            WriteU32(span, fighterRecord + 16, fighter.Present ? 1U : 0U);
            WriteU32(span, fighterRecord + 20, checked((uint)fighter.Descriptors.Length));
            WriteU64(span, fighterRecord + 24, checked((ulong)(
                descriptorsOffset + descriptorIndex * DescriptorRecordSize)));
            WriteU32(span, fighterRecord + 32, checked((uint)fighter.Bubbles.Length));
            WriteU64(span, fighterRecord + 40, checked((ulong)(
                bubblesOffset + bubbleIndex * BubbleRecordSize)));
            WriteU32(span, fighterRecord + 48, checked((uint)fighter.ApplyTables.Length));
            WriteU64(span, fighterRecord + 56, checked((ulong)(
                tablesOffset + tableIndex * ApplyTableRecordSize)));

            foreach (DynamicDescriptor descriptor in fighter.Descriptors)
            {
                int offset = descriptorsOffset + descriptorIndex++ * DescriptorRecordSize;
                WriteI32(span, offset, descriptor.BoneIndex);
                WriteU64(span, offset + 8, checked((ulong)(
                    parametersOffset + parameterIndex * ParameterRecordSize)));
                WriteU32(span, offset + 16, checked((uint)descriptor.Parameters.Length));
                WriteU32(span, offset + 20, descriptor.DragBits);
                WriteU32(span, offset + 24, descriptor.StiffnessBits);
                WriteU32(span, offset + 28, descriptor.GravityBits);
                foreach (DynamicParameters parameters in descriptor.Parameters)
                {
                    int parameterOffset = parametersOffset +
                        parameterIndex++ * ParameterRecordSize;
                    WriteWords(span, parameterOffset, parameters.Words);
                }
            }
            foreach (DynamicBubble bubble in fighter.Bubbles)
            {
                int offset = bubblesOffset + bubbleIndex++ * BubbleRecordSize;
                WriteI32(span, offset, bubble.BoneIndex);
                WriteWords(span, offset + 4, bubble.Words);
            }
            foreach (ApplyTable table in fighter.ApplyTables)
            {
                int offset = tablesOffset + tableIndex++ * ApplyTableRecordSize;
                WriteU64(span, offset, checked((ulong)(
                    valuesOffset + valueIndex * sizeof(int))));
                WriteU32(span, offset + 8, checked((uint)table.Values.Length));
                WriteU32(span, offset + 12, table.Present ? 1U : 0U);
                foreach (int value in table.Values)
                    WriteI32(span, valuesOffset + valueIndex++ * sizeof(int), value);
            }
        }
        if (descriptorIndex != descriptorCount || parameterIndex != parameterCount ||
            bubbleIndex != bubbleCount || tableIndex != tableCount ||
            valueIndex != valueCount)
        {
            throw new InvalidDataException("fighter dynamics layout mismatch");
        }
        return result;
    }

    private static DynamicParameters ReadParameters(SBM_DynamicParams value) => new([
        Bits(value.FollowDamping), Bits(value.Stiffness), Bits(value.RotX),
        Bits(value.RotY), Bits(value.RotZ), Bits(value.RotW),
        Bits(value.RotationLimit), Bits(value.PARAM8), Bits(value.PARAM9),
        Bits(value.PARAM10), Bits(value.PARAM11), Bits(value.PARAM12),
        Bits(value.PARAM13), Bits(value.InertiaDamping), Bits(value.Resistance)]);
    private static uint Bits(float value) => BitConverter.SingleToUInt32Bits(value);
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
    private static void WriteWords(Span<byte> bytes, int offset, uint[] words)
    {
        for (int index = 0; index < words.Length; ++index)
            WriteU32(bytes, offset + index * 4, words[index]);
    }
    private static void WriteU32(Span<byte> bytes, int offset, uint value) =>
        BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);
    private static void WriteI32(Span<byte> bytes, int offset, int value) =>
        BinaryPrimitives.WriteInt32LittleEndian(bytes[offset..], value);
    private static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
        BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);
}

internal sealed record FighterDynamicsAsset(
    string Path,
    string RootName,
    bool Present,
    DynamicDescriptor[] Descriptors,
    DynamicBubble[] Bubbles,
    ApplyTable[] ApplyTables);
internal sealed record DynamicDescriptor(
    int BoneIndex,
    uint DragBits,
    uint StiffnessBits,
    uint GravityBits,
    DynamicParameters[] Parameters);
internal sealed record DynamicParameters(uint[] Words);
internal sealed record DynamicBubble(int BoneIndex, uint[] Words);
internal sealed record ApplyTable(bool Present, int[] Values);
