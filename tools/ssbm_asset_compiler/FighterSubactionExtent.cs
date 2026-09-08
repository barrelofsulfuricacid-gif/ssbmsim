using System.Buffers.Binary;
using HSDRaw;
using HSDRaw.Melee.Pl;
using HSDRaw.Tools.Melee;

// DAT relocation targets split HSDStruct nodes; they do not terminate a
// fighter command stream. HSDLib may insert synthetic Gotos across shared tails.
// Restore both bytes and relocations from the DAT, never from that rewritten
// graph. Preserve node identities so other references still reach the scripts.
internal static class FighterSubactionExtent
{
    public static void Restore(
        HSDRawFile archive, ReadOnlySpan<byte> sourceBytes,
        IEnumerable<SBM_FighterAction> actions, string provenance)
    {
        if (sourceBytes.Length < 32)
            throw new InvalidDataException($"truncated DAT header in '{provenance}'");
        uint dataSize = BinaryPrimitives.ReadUInt32BigEndian(sourceBytes.Slice(4, 4));
        uint relocationCount = BinaryPrimitives.ReadUInt32BigEndian(sourceBytes.Slice(8, 4));
        if (32UL + dataSize + 4UL * relocationCount > (ulong)sourceBytes.Length)
            throw new InvalidDataException($"truncated DAT relocations in '{provenance}'");
        int dataEnd = checked(32 + (int)dataSize);
        SortedSet<int> relocationSlots = [];
        for (int i = 0; i < relocationCount; ++i)
        {
            uint slot = BinaryPrimitives.ReadUInt32BigEndian(
                sourceBytes.Slice(dataEnd + i * 4, 4));
            if (dataSize < 4 || slot > dataSize - 4 ||
                !relocationSlots.Add(checked(32 + (int)slot)))
                throw new InvalidDataException($"invalid DAT relocation in '{provenance}'");
        }
        DatStructRange.Capture(archive);
        HashSet<HSDStruct> visited = new(ReferenceEqualityComparer.Instance);
        Queue<HSDStruct> pending = new(actions
            .Select(action => action.SubAction?._s)
            .OfType<HSDStruct>());
        while (pending.TryDequeue(out HSDStruct? script))
        {
            if (!visited.Add(script)) continue;
            int start = archive.GetOffsetFromStruct(script);
            if (start < 32 || start > dataEnd - 4)
                throw new InvalidDataException(
                    $"unmapped fighter subaction in '{provenance}'");
            int cursor = start;
            while (true)
            {
                if (cursor > dataEnd - 4 || cursor - start > 0x10000)
                    throw new InvalidDataException(
                        $"unterminated fighter subaction in '{provenance}' at {start:X}");
                byte opcode = (byte)(sourceBytes[cursor] >> 2);
                MeleeCMDAction? command = ActionCommon.SubActions
                    .Find(candidate => candidate.Command == opcode);
                if (command is null || command.ByteSize < 4 ||
                    command.ByteSize % 4 != 0 ||
                    cursor > dataEnd - command.ByteSize)
                    throw new InvalidDataException(
                        $"invalid fighter command {opcode} in '{provenance}' at {cursor:X}");
                cursor = checked(cursor + command.ByteSize);
                // End, return, and unconditional goto end linear execution.
                // Subroutine/goto target nodes are followed below.
                if (opcode is 0 or 6 or 7) break;
                // Command_05 assigns its operand directly to info->u. A
                // non-relocated zero terminates the interpreter just as a
                // null goto does; it is not DAT data-offset zero.
                if (opcode == 5 && !relocationSlots.Contains(cursor - 4) &&
                    BinaryPrimitives.ReadUInt32BigEndian(sourceBytes.Slice(cursor - 4, 4)) == 0)
                    break;
            }
            int extent = cursor - start;
            Dictionary<int, HSDStruct> originalReferences = [];
            foreach (int slot in relocationSlots.GetViewBetween(start, cursor - 1))
            {
                uint targetOffset = BinaryPrimitives.ReadUInt32BigEndian(sourceBytes.Slice(slot, 4));
                if (slot > cursor - 4 || targetOffset >= dataSize)
                    throw new InvalidDataException($"invalid script relocation in '{provenance}' at {slot:X}");
                // A relocated zero is the start of DAT data, not a null pointer.
                HSDStruct target = DatStructRange.AtOffset(archive, checked(32 + (int)targetOffset))
                    ?? throw new InvalidDataException(
                        $"unmapped script target in '{provenance}' at {slot:X}");
                originalReferences.Add(slot - start, target);
            }
            int previousLength = script.Length;
            // Loader repairs may have inspected an opcode through a numeric
            // accessor. Packed command bytes must not inherit that layout.
            script.ClearScalarLayout();
            script.References.Clear();
            script.SetData(sourceBytes.Slice(start, extent).ToArray());
            foreach ((int offset, HSDStruct target) in originalReferences)
                script.SetReferenceStruct(offset, target);
            if (previousLength != extent)
                Console.WriteLine(
                    $"fighter-script-extent {provenance} offset={start:X} " +
                    $"before={previousLength} after={extent}");
            // Only control-flow operands are scripts. Other command operands
            // can reference models or effect data and must not be decoded here.
            for (cursor = start; cursor < start + extent;)
            {
                byte opcode = (byte)(sourceBytes[cursor] >> 2);
                if (opcode is 5 or 7)
                {
                    if (!script.References.TryGetValue(cursor - start + 4,
                            out HSDStruct? target))
                    {
                        uint operand = BinaryPrimitives.ReadUInt32BigEndian(sourceBytes.Slice(cursor + 4, 4));
                        if (operand != 0)
                            throw new InvalidDataException(
                                $"unrelocated fighter control flow in '{provenance}' at {cursor:X}");
                    }
                    else pending.Enqueue(target);
                }
                cursor += ActionCommon.SubActions
                    .Find(candidate => candidate.Command == opcode)!.ByteSize;
            }
        }
    }
}
