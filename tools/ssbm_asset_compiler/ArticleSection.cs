using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Melee.Pl;

internal static class ArticleSection
{
    public const string Name = "article.data.v1";
    public const uint Schema = 1;
    public const int SourceRecordSize = 40;
    public const int SlotRecordSize = 208;
    public const int StateRecordSize = 40;
    public const int HurtboxRecordSize = 32;
    public const int DescriptorRecordSize = 32;
    public const int ParameterRecordSize = 60;
    private const int HeaderSize = 112;

    private const uint HasCommonAttributes = 1U << 0;
    private const uint HasExtension = 1U << 1;
    private const uint HasHurtboxes = 1U << 2;
    private const uint HasStates = 1U << 3;
    private const uint HasModel = 1U << 4;
    private const uint HasDynamics = 1U << 5;

    public static ArticleSourceAsset ReadSource(
        string path,
        string rootName,
        uint groupKind,
        SBM_ArticlePointer source)
    {
        SBM_Article[] sourceSlots = source.Articles;
        ArticleSlotAsset?[] slots = new ArticleSlotAsset?[sourceSlots.Length];
        for (int slotIndex = 0; slotIndex < sourceSlots.Length; ++slotIndex)
        {
            SBM_Article? article = sourceSlots[slotIndex];
            if (article is null) continue;
            uint presence = 0;
            if (article.Parameters is not null) presence |= HasCommonAttributes;
            if (article.ParametersExt is not null) presence |= HasExtension;
            if (article.Hurtboxes is not null) presence |= HasHurtboxes;
            if (article.ItemState is not null) presence |= HasStates;
            if (article.Model is not null) presence |= HasModel;
            if (article.ItemDynamics is not null) presence |= HasDynamics;

            byte commonByte = 0;
            uint[] commonWords = [];
            int commonBytes = 0;
            if (article.Parameters is not null)
            {
                int storageBytes = article.Parameters._s.Length;
                commonBytes = Math.Min(storageBytes, 0x84);
                if (commonBytes < 4 || commonBytes % sizeof(uint) != 0)
                    throw new InvalidDataException(
                        $"invalid article common attributes in '{path}:{rootName}:{slotIndex}': " +
                        storageBytes);
                commonByte = article.Parameters._s.GetByte(0);
                commonWords = new uint[0x80 / sizeof(uint)];
                for (int index = 0; index < commonBytes / sizeof(uint) - 1; ++index)
                    commonWords[index] = article.Parameters._s.GetUInt32(4 + index * 4);
            }

            SBM_ItemHurtbox[] hurtboxStorage = article.Hurtboxes?.Hurtboxes ?? [];
            int hurtboxCount = article.Hurtboxes?._s.GetInt32(0) ?? 0;
            if (hurtboxCount < 0 || hurtboxStorage.Length < hurtboxCount)
                throw new InvalidDataException(
                    $"article hurtbox count mismatch in '{path}:{rootName}:{slotIndex}'");
            ArticleHurtbox[] hurtboxes = hurtboxStorage.Take(hurtboxCount)
                .Select(value => new ArticleHurtbox(
                    value.BoneIndex,
                    [Bits(value.X1), Bits(value.Y1), Bits(value.Z1),
                     Bits(value.X2), Bits(value.Y2), Bits(value.Z2), Bits(value.Size)]))
                .ToArray();

            ArticleState[] states = (article.ItemState?.Array ?? [])
                .Select(ReadState)
                .ToArray();
            ItemDynamics? dynamics = article.ItemDynamics;
            SBM_DynamicDesc[] descriptorStorage = dynamics?.DynamicsDesc ?? [];
            int descriptorCount = dynamics?.DynamicsNum ?? 0;
            if (descriptorCount < 0)
                throw new InvalidDataException(
                    $"article dynamics count mismatch in '{path}:{rootName}:{slotIndex}': " +
                    $"{descriptorCount}/{descriptorStorage.Length} raw=" +
                    Convert.ToHexString(dynamics?._s.GetData() ?? []));
            ArticleDynamicDescriptor[] descriptors =
                descriptorStorage.Length < descriptorCount
                    ? []
                    : descriptorStorage
                        .Take(descriptorCount)
                        .Select(value => ReadDescriptor(path, rootName, slotIndex, value))
                        .ToArray();
            slots[slotIndex] = new ArticleSlotAsset(
                presence,
                commonByte,
                commonWords,
                commonBytes,
                article.ParametersExt?._s.Length ?? 0,
                article.ParametersExt?._s.References.Count ?? 0,
                hurtboxes,
                states,
                article.Model?.RootModelJoint,
                article.Model?.BoneCount ?? 0,
                article.Model?.BoneAttachID ?? 0,
                article.Model?.BitField ?? 0,
                descriptors,
                descriptorCount,
                article.ParametersExt?._s);
        }
        return new(path, rootName, groupKind, slots);
    }

    public static string ModelTreeName(ArticleSourceAsset source, int slotIndex) =>
        $"{source.RootName}:article:{source.GroupKind}:{slotIndex}:model";

    public static byte[] Build(IReadOnlyList<ArticleSourceAsset> sources)
    {
        int slotCount = sources.Sum(source => source.Slots.Length);
        int stateCount = sources.Sum(source => source.Slots.Sum(slot => slot?.States.Length ?? 0));
        int hurtboxCount = sources.Sum(source => source.Slots.Sum(slot => slot?.Hurtboxes.Length ?? 0));
        int descriptorCount = sources.Sum(source => source.Slots.Sum(slot => slot?.Descriptors.Length ?? 0));
        int parameterCount = sources.Sum(source => source.Slots.Sum(slot =>
            slot?.Descriptors.Sum(descriptor => descriptor.Parameters.Length) ?? 0));
        int sourceOffset = HeaderSize;
        int slotOffset = Align8(checked(sourceOffset + sources.Count * SourceRecordSize));
        int stateOffset = Align8(checked(slotOffset + slotCount * SlotRecordSize));
        int hurtboxOffset = Align8(checked(stateOffset + stateCount * StateRecordSize));
        int descriptorOffset = Align8(checked(hurtboxOffset + hurtboxCount * HurtboxRecordSize));
        int parameterOffset = Align8(checked(descriptorOffset + descriptorCount * DescriptorRecordSize));
        int blobOffset = Align8(checked(parameterOffset + parameterCount * ParameterRecordSize));

        using MemoryStream blob = new();
        List<(int Offset, int Length)> scripts = new(stateCount);
        foreach (ArticleSourceAsset source in sources)
            foreach (ArticleSlotAsset? slot in source.Slots)
                if (slot is not null)
                    foreach (ArticleState state in slot.States)
                    {
                        scripts.Add((checked((int)blob.Position), state.Script.Length));
                        blob.Write(state.Script);
                    }
        byte[] result = new byte[checked(blobOffset + (int)blob.Length)];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)sources.Count));
        WriteU32(span, 8, checked((uint)slotCount));
        WriteU32(span, 12, checked((uint)stateCount));
        WriteU32(span, 16, checked((uint)hurtboxCount));
        WriteU32(span, 20, checked((uint)descriptorCount));
        WriteU32(span, 24, checked((uint)parameterCount));
        WriteU32(span, 28, SourceRecordSize);
        WriteU32(span, 32, SlotRecordSize);
        WriteU32(span, 36, StateRecordSize);
        WriteU32(span, 40, HurtboxRecordSize);
        WriteU32(span, 44, DescriptorRecordSize);
        WriteU32(span, 48, ParameterRecordSize);
        WriteU64(span, 56, checked((ulong)sourceOffset));
        WriteU64(span, 64, checked((ulong)slotOffset));
        WriteU64(span, 72, checked((ulong)stateOffset));
        WriteU64(span, 80, checked((ulong)hurtboxOffset));
        WriteU64(span, 88, checked((ulong)descriptorOffset));
        WriteU64(span, 96, checked((ulong)parameterOffset));
        WriteU64(span, 104, checked((ulong)blobOffset));
        blob.ToArray().CopyTo(span[blobOffset..]);

        int slotIndex = 0;
        int stateIndex = 0;
        int scriptIndex = 0;
        int hurtboxIndex = 0;
        int descriptorIndex = 0;
        int parameterIndex = 0;
        for (int sourceIndex = 0; sourceIndex < sources.Count; ++sourceIndex)
        {
            ArticleSourceAsset source = sources[sourceIndex];
            int sourceRecord = sourceOffset + sourceIndex * SourceRecordSize;
            WriteU64(span, sourceRecord, StableNameHash(source.Path));
            WriteU64(span, sourceRecord + 8, StableNameHash(source.RootName));
            WriteU32(span, sourceRecord + 16, source.GroupKind);
            WriteU32(span, sourceRecord + 20, checked((uint)slotIndex));
            WriteU32(span, sourceRecord + 24, checked((uint)source.Slots.Length));
            for (int localSlot = 0; localSlot < source.Slots.Length; ++localSlot, ++slotIndex)
            {
                ArticleSlotAsset? slot = source.Slots[localSlot];
                int slotRecord = slotOffset + slotIndex * SlotRecordSize;
                if (slot is null) continue;
                WriteU32(span, slotRecord, 1);
                WriteU32(span, slotRecord + 4, slot.Presence);
                if (slot.ModelJoint is not null)
                {
                    WriteU64(span, slotRecord + 8, StableNameHash(source.Path));
                    WriteU64(span, slotRecord + 16,
                        StableNameHash(ModelTreeName(source, localSlot)));
                }
                span[slotRecord + 24] = slot.CommonByte;
                WriteWords(span, slotRecord + 28, slot.CommonWords);
                WriteI32(span, slotRecord + 156, slot.ModelBoneCount);
                WriteI32(span, slotRecord + 160, slot.ModelAttachBone);
                WriteI32(span, slotRecord + 164, slot.ModelFlags);
                WriteU32(span, slotRecord + 168, checked((uint)hurtboxIndex));
                WriteU32(span, slotRecord + 172, checked((uint)slot.Hurtboxes.Length));
                WriteU32(span, slotRecord + 176, checked((uint)stateIndex));
                WriteU32(span, slotRecord + 180, checked((uint)slot.States.Length));
                WriteU32(span, slotRecord + 184, checked((uint)descriptorIndex));
                WriteU32(span, slotRecord + 188, checked((uint)slot.Descriptors.Length));
                WriteU32(span, slotRecord + 192, checked((uint)slot.ExtensionBytes));
                WriteU32(span, slotRecord + 196, checked((uint)slot.ExtensionReferences));
                WriteU32(span, slotRecord + 200, checked((uint)slot.DeclaredDynamicCount));
                WriteU32(span, slotRecord + 204, checked((uint)slot.CommonAttributeBytes));

                foreach (ArticleHurtbox hurtbox in slot.Hurtboxes)
                {
                    int record = hurtboxOffset + hurtboxIndex++ * HurtboxRecordSize;
                    WriteI32(span, record, hurtbox.BoneIndex);
                    WriteWords(span, record + 4, hurtbox.Words);
                }
                foreach (ArticleState state in slot.States)
                {
                    int record = stateOffset + stateIndex++ * StateRecordSize;
                    WriteU32(span, record, state.Presence);
                    WriteU64(span, record + 8, checked((ulong)(
                        blobOffset + scripts[scriptIndex].Offset)));
                    WriteU32(span, record + 16, checked((uint)scripts[scriptIndex].Length));
                    WriteU32(span, record + 20, checked((uint)state.ParameterBytes));
                    WriteU32(span, record + 24, checked((uint)state.ParameterReferences));
                    ++scriptIndex;
                }
                foreach (ArticleDynamicDescriptor descriptor in slot.Descriptors)
                {
                    int record = descriptorOffset + descriptorIndex++ * DescriptorRecordSize;
                    WriteI32(span, record, descriptor.BoneIndex);
                    WriteU32(span, record + 4, checked((uint)parameterIndex));
                    WriteU32(span, record + 8, checked((uint)descriptor.Parameters.Length));
                    WriteU32(span, record + 12, descriptor.DragBits);
                    WriteU32(span, record + 16, descriptor.StiffnessBits);
                    WriteU32(span, record + 20, descriptor.GravityBits);
                    foreach (ArticleDynamicParameters parameters in descriptor.Parameters)
                    {
                        WriteWords(span, parameterOffset +
                            parameterIndex++ * ParameterRecordSize, parameters.Words);
                    }
                }
            }
        }
        if (slotIndex != slotCount || stateIndex != stateCount ||
            scriptIndex != scripts.Count || hurtboxIndex != hurtboxCount ||
            descriptorIndex != descriptorCount || parameterIndex != parameterCount)
            throw new InvalidDataException("article layout mismatch");
        return result;
    }

    private static ArticleState ReadState(SBM_ItemState state)
    {
        uint presence = 0;
        if (state.AnimJoint is not null) presence |= 1U << 0;
        if (state.MatAnimJoint is not null) presence |= 1U << 1;
        if (state.Parameters is not null) presence |= 1U << 2;
        if (state.SubactionScript is not null) presence |= 1U << 3;
        return new(
            presence,
            state.SubactionScript?._s.GetData() ?? [],
            state.Parameters?._s.Length ?? 0,
            state.Parameters?._s.References.Count ?? 0,
            state.AnimJoint?._s,
            state.MatAnimJoint?._s,
            state.Parameters?._s);
    }

    private static ArticleDynamicDescriptor ReadDescriptor(
        string path,
        string rootName,
        int slotIndex,
        SBM_DynamicDesc source)
    {
        SBM_DynamicParams[] storage = source.Parameters ?? [];
        int count = source.ParameterCount;
        if (count < 0 || storage.Length < count)
            throw new InvalidDataException(
                $"article dynamic parameter mismatch in '{path}:{rootName}:{slotIndex}'");
        return new(
            source.BoneIndex,
            Bits(source.DragMultiplier),
            Bits(source.StiffnessMultiplier),
            Bits(source.GravityLengthCompensation),
            storage.Take(count).Select(value => new ArticleDynamicParameters([
                Bits(value.FollowDamping), Bits(value.Stiffness), Bits(value.RotX),
                Bits(value.RotY), Bits(value.RotZ), Bits(value.RotW),
                Bits(value.RotationLimit), Bits(value.PARAM8), Bits(value.PARAM9),
                Bits(value.PARAM10), Bits(value.PARAM11), Bits(value.PARAM12),
                Bits(value.PARAM13), Bits(value.InertiaDamping), Bits(value.Resistance)]))
            .ToArray());
    }

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

internal sealed record ArticleSourceAsset(
    string Path,
    string RootName,
    uint GroupKind,
    ArticleSlotAsset?[] Slots);
internal sealed record ArticleSlotAsset(
    uint Presence,
    byte CommonByte,
    uint[] CommonWords,
    int CommonAttributeBytes,
    int ExtensionBytes,
    int ExtensionReferences,
    ArticleHurtbox[] Hurtboxes,
    ArticleState[] States,
    HSD_JOBJ? ModelJoint,
    int ModelBoneCount,
    int ModelAttachBone,
    int ModelFlags,
    ArticleDynamicDescriptor[] Descriptors,
    int DeclaredDynamicCount,
    HSDStruct? ExtensionStruct);
internal sealed record ArticleHurtbox(int BoneIndex, uint[] Words);
internal sealed record ArticleState(
    uint Presence,
    byte[] Script,
    int ParameterBytes,
    int ParameterReferences,
    HSDStruct? AnimationStruct,
    HSDStruct? MaterialAnimationStruct,
    HSDStruct? ParameterStruct);
internal sealed record ArticleDynamicDescriptor(
    int BoneIndex,
    uint DragBits,
    uint StiffnessBits,
    uint GravityBits,
    ArticleDynamicParameters[] Parameters);
internal sealed record ArticleDynamicParameters(uint[] Words);
