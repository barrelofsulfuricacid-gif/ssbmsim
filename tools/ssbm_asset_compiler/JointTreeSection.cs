using System.Buffers.Binary;
using System.Text;
using HSDRaw;
using HSDRaw.Common;

internal static class JointTreeSection
{
    public const string Name = "joint.trees.v2";
    public const uint Schema = 2;
    public const int TreeRecordSize = 32;
    public const int JointRecordSize = 184;
    public const int ReferenceRecordSize = 32;
    public const int RvalueRecordSize = 16;
    private const int HeaderSize = 96;

    public static JointTreeAsset Read(
        string path,
        string rootName,
        HSD_JOBJ root)
    {
        List<JointAsset> joints = [];
        Dictionary<HSDStruct, int> seen = new(ReferenceEqualityComparer.Instance);
        int firstRoot = -1;
        int previousRoot = -1;
        for (HSD_JOBJ? item = root; item is not null; item = item.Next)
        {
            int index = Visit(item, -1, path, rootName, joints, seen);
            if (firstRoot < 0) firstRoot = index;
            if (previousRoot >= 0)
                joints[previousRoot] = joints[previousRoot] with { NextSibling = index };
            previousRoot = index;
        }
        if (firstRoot != 0 || joints.Count == 0)
            throw new InvalidDataException($"empty joint tree '{path}:{rootName}'");
        for (int index = 0; index < joints.Count; ++index)
        {
            joints[index] = joints[index] with
            {
                References = joints[index].References.Select(reference =>
                    reference with
                    {
                        TargetJoint = ResolveTarget(reference.TargetSource, seen, path, rootName),
                        Rvalues = reference.Rvalues.Select(value => value with
                        {
                            TargetJoint = ResolveTarget(value.TargetSource, seen, path, rootName),
                        }).ToArray(),
                    }).ToArray(),
            };
        }
        return new(path, rootName, joints.ToArray());
    }

    public static byte[] Build(IReadOnlyList<JointTreeAsset> trees)
    {
        int jointCount = trees.Sum(tree => tree.Joints.Length);
        int referenceCount = trees.Sum(tree =>
            tree.Joints.Sum(joint => joint.References.Length));
        int rvalueCount = trees.Sum(tree => tree.Joints.Sum(joint =>
            joint.References.Sum(reference => reference.Rvalues.Length)));
        int treesOffset = HeaderSize;
        int jointsOffset = Align8(checked(treesOffset + trees.Count * TreeRecordSize));
        int referencesOffset = Align8(checked(jointsOffset + jointCount * JointRecordSize));
        int rvaluesOffset = Align8(checked(
            referencesOffset + referenceCount * ReferenceRecordSize));
        int blobOffset = Align8(checked(rvaluesOffset + rvalueCount * RvalueRecordSize));
        using MemoryStream blob = new();
        List<JointBlobAsset> blobs = new(jointCount);
        foreach (JointTreeAsset tree in trees)
        {
            foreach (JointAsset joint in tree.Joints)
            {
                byte[] bytes = Encoding.UTF8.GetBytes(joint.ClassName);
                int nameOffset = checked((int)blob.Position);
                blob.Write(bytes);
                SplineAsset? spline = joint.Spline;
                int cvOffset = 0;
                int lengthOffset = 0;
                int segmentOffset = 0;
                if (spline is not null)
                {
                    Align4(blob);
                    cvOffset = checked((int)blob.Position);
                    WriteWords(blob, spline.CvBits);
                    lengthOffset = checked((int)blob.Position);
                    WriteWords(blob, spline.LengthBits);
                    segmentOffset = checked((int)blob.Position);
                    WriteWords(blob, spline.SegmentBits);
                }
                blobs.Add(new(
                    nameOffset,
                    bytes.Length,
                    cvOffset,
                    lengthOffset,
                    segmentOffset));
            }
        }
        byte[] result = new byte[checked(blobOffset + (int)blob.Length)];
        Span<byte> span = result;
        WriteU32(span, 0, Schema);
        WriteU32(span, 4, checked((uint)trees.Count));
        WriteU32(span, 8, checked((uint)jointCount));
        WriteU32(span, 12, checked((uint)referenceCount));
        WriteU32(span, 16, checked((uint)rvalueCount));
        WriteU32(span, 20, TreeRecordSize);
        WriteU32(span, 24, JointRecordSize);
        WriteU32(span, 28, ReferenceRecordSize);
        WriteU32(span, 32, RvalueRecordSize);
        WriteU64(span, 40, checked((ulong)treesOffset));
        WriteU64(span, 48, checked((ulong)jointsOffset));
        WriteU64(span, 56, checked((ulong)referencesOffset));
        WriteU64(span, 64, checked((ulong)rvaluesOffset));
        WriteU64(span, 72, checked((ulong)blobOffset));
        blob.ToArray().CopyTo(span[blobOffset..]);

        int jointIndex = 0;
        int referenceIndex = 0;
        int rvalueIndex = 0;
        foreach ((JointTreeAsset tree, int treeIndex) in trees.Select((value, index) => (value, index)))
        {
            int treeRecord = treesOffset + treeIndex * TreeRecordSize;
            WriteU64(span, treeRecord, StableNameHash(tree.Path));
            WriteU64(span, treeRecord + 8, StableNameHash(tree.RootName));
            WriteU64(span, treeRecord + 16, checked((ulong)(
                jointsOffset + jointIndex * JointRecordSize)));
            WriteU32(span, treeRecord + 24, checked((uint)tree.Joints.Length));
            int treeBase = jointIndex;
            foreach (JointAsset joint in tree.Joints)
            {
                int record = jointsOffset + jointIndex * JointRecordSize;
                WriteI32(span, record, GlobalIndex(joint.Parent, treeBase));
                WriteI32(span, record + 4, GlobalIndex(joint.FirstChild, treeBase));
                WriteI32(span, record + 8, GlobalIndex(joint.NextSibling, treeBase));
                WriteU32(span, record + 12, joint.Flags);
                WriteU64(span, record + 16, checked((ulong)(
                    blobOffset + blobs[jointIndex].NameOffset)));
                WriteU32(span, record + 24,
                    checked((uint)blobs[jointIndex].NameLength));
                WriteU32(span, record + 28, joint.InversePresent ? 1U : 0U);
                WriteWords(span, record + 32, joint.SrtBits);
                WriteWords(span, record + 68, joint.InverseBits);
                WriteU32(span, record + 116, joint.DisplayObjectPresent ? 1U : 0U);
                WriteU32(span, record + 120, checked((uint)referenceIndex));
                WriteU32(span, record + 124, checked((uint)joint.References.Length));
                if (joint.Spline is not null)
                {
                    SplineAsset spline = joint.Spline;
                    WriteU32(span, record + 128, 1);
                    WriteU32(span, record + 132, spline.Type);
                    WriteI32(span, record + 136, spline.NumCv);
                    WriteU32(span, record + 140, spline.TensionBits);
                    WriteU32(span, record + 144, spline.TotalLengthBits);
                    WriteU32(span, record + 148,
                        checked((uint)(spline.CvBits.Length / 3)));
                    WriteU32(span, record + 152,
                        checked((uint)spline.LengthBits.Length));
                    WriteU32(span, record + 156,
                        checked((uint)(spline.SegmentBits.Length / 5)));
                    WriteU64(span, record + 160, checked((ulong)(
                        blobOffset + blobs[jointIndex].CvOffset)));
                    WriteU64(span, record + 168, checked((ulong)(
                        blobOffset + blobs[jointIndex].LengthOffset)));
                    WriteU64(span, record + 176, checked((ulong)(
                        blobOffset + blobs[jointIndex].SegmentOffset)));
                }
                foreach (JointReferenceAsset reference in joint.References)
                {
                    int referenceRecord = referencesOffset +
                        referenceIndex++ * ReferenceRecordSize;
                    WriteI32(span, referenceRecord, reference.Flags);
                    WriteU32(span, referenceRecord + 4, reference.RefType);
                    WriteU32(span, referenceRecord + 8, checked((uint)rvalueIndex));
                    WriteU32(span, referenceRecord + 12,
                        checked((uint)reference.Rvalues.Length));
                    WriteU32(span, referenceRecord + 16, reference.PayloadBits);
                    WriteI32(span, referenceRecord + 20, reference.TargetJoint < 0
                        ? -1
                        : checked(reference.TargetJoint + treeBase));
                    WriteU32(span, referenceRecord + 24, reference.IkBoneBits);
                    WriteU32(span, referenceRecord + 28, reference.IkRotateBits);
                    foreach (JointRvalueAsset rvalue in reference.Rvalues)
                    {
                        int rvalueRecord = rvaluesOffset +
                            rvalueIndex++ * RvalueRecordSize;
                        WriteI32(span, rvalueRecord, rvalue.Flags);
                        WriteI32(span, rvalueRecord + 4, rvalue.TargetJoint < 0
                            ? -1
                            : checked(rvalue.TargetJoint + treeBase));
                    }
                }
                ++jointIndex;
            }
        }
        if (jointIndex != jointCount || referenceIndex != referenceCount ||
            rvalueIndex != rvalueCount || blobs.Count != jointCount)
            throw new InvalidDataException("joint tree layout mismatch");
        return result;
    }

    private static int Visit(
        HSD_JOBJ source,
        int parent,
        string path,
        string rootName,
        List<JointAsset> joints,
        Dictionary<HSDStruct, int> seen)
    {
        if (seen.ContainsKey(source._s))
            throw new InvalidDataException($"shared/cyclic joint in '{path}:{rootName}'");
        int index = joints.Count;
        seen.Add(source._s, index);
        HSD_Matrix4x3? inverse = source.InverseWorldTransform;
        joints.Add(new JointAsset(
            parent,
            -1,
            -1,
            unchecked((uint)source.Flags),
            source.ClassName ?? string.Empty,
            [Bits(source.RX), Bits(source.RY), Bits(source.RZ),
             Bits(source.SX), Bits(source.SY), Bits(source.SZ),
             Bits(source.TX), Bits(source.TY), Bits(source.TZ)],
            inverse is null ? [] : [
                Bits(inverse.M11), Bits(inverse.M12), Bits(inverse.M13), Bits(inverse.M14),
                Bits(inverse.M21), Bits(inverse.M22), Bits(inverse.M23), Bits(inverse.M24),
                Bits(inverse.M31), Bits(inverse.M32), Bits(inverse.M33), Bits(inverse.M34)],
            inverse is not null,
            source.Dobj is not null,
            ReadSpline(source.Spline),
            ReadReferences(source.ROBJ, path, rootName)));
        int firstChild = -1;
        int previousChild = -1;
        for (HSD_JOBJ? child = source.Child; child is not null; child = child.Next)
        {
            int childIndex = Visit(child, index, path, rootName, joints, seen);
            if (firstChild < 0) firstChild = childIndex;
            if (previousChild >= 0)
                joints[previousChild] = joints[previousChild] with { NextSibling = childIndex };
            previousChild = childIndex;
        }
        joints[index] = joints[index] with { FirstChild = firstChild };
        return index;
    }

    private static int GlobalIndex(int local, int treeBase) =>
        local < 0 ? -1 : checked(local + treeBase);

    private static JointReferenceAsset[] ReadReferences(
        HSD_ROBJ? source,
        string path,
        string rootName)
    {
        return (source?.List ?? []).Select(reference =>
        {
            uint refType = unchecked((uint)reference.RefType);
            uint payload = 0;
            uint ikBone = 0;
            uint ikRotate = 0;
            HSD_JOBJ? target = null;
            HSD_RValueList[] rvalues = [];
            switch (reference.RefType)
            {
                case REFTYPE.EXP:
                    if (reference.Ref_Exp is null) throw MissingReference(path, rootName);
                    payload = Bits(reference.Ref_Exp.func);
                    rvalues = reference.Ref_Exp.rvalue?.List.ToArray() ?? [];
                    break;
                case REFTYPE.JOBJ:
                    target = reference.Ref_Joint;
                    if (target is null) throw MissingReference(path, rootName);
                    break;
                case REFTYPE.LIMIT:
                    payload = Bits(reference.Ref_Limit);
                    break;
                case REFTYPE.BYTECODE:
                    if (reference.Ref_ByteCodeExp is null)
                        throw MissingReference(path, rootName);
                    payload = reference.Ref_ByteCodeExp.ByteCode;
                    rvalues = reference.Ref_ByteCodeExp.rvalue?.List.ToArray() ?? [];
                    break;
                case REFTYPE.IKHINT:
                    if (reference.Ref_IkHint is null) throw MissingReference(path, rootName);
                    ikBone = Bits(reference.Ref_IkHint.BoneLength);
                    ikRotate = Bits(reference.Ref_IkHint.RotateX);
                    break;
                default:
                    throw new InvalidDataException(
                        $"unknown joint reference type {refType:x8} in '{path}:{rootName}'");
            }
            return new JointReferenceAsset(
                reference.Flags,
                refType,
                payload,
                target,
                -1,
                ikBone,
                ikRotate,
                rvalues.Select(value => new JointRvalueAsset(
                    value.Flags, value.JOBJ, -1)).ToArray());
        }).ToArray();
    }

    private static int ResolveTarget(
        HSD_JOBJ? target,
        Dictionary<HSDStruct, int> seen,
        string path,
        string rootName)
    {
        if (target is null) return -1;
        if (!seen.TryGetValue(target._s, out int index))
            throw new InvalidDataException(
                $"joint reference escapes tree '{path}:{rootName}'");
        return index;
    }

    private static InvalidDataException MissingReference(string path, string rootName) =>
        new($"null joint reference payload in '{path}:{rootName}'");

    private static SplineAsset? ReadSpline(HSD_Spline? source)
    {
        if (source is null) return null;
        HSD_Vector3[] cvs = source.CV ?? [];
        float[] lengths = source.Lengths?.Array ?? [];
        HSD_SegPoly[] segments = source.SegPolys?.Array ?? [];
        uint[] cvBits = new uint[checked(cvs.Length * 3)];
        for (int index = 0; index < cvs.Length; ++index)
        {
            cvBits[index * 3] = Bits(cvs[index].X);
            cvBits[index * 3 + 1] = Bits(cvs[index].Y);
            cvBits[index * 3 + 2] = Bits(cvs[index].Z);
        }
        uint[] segmentBits = new uint[checked(segments.Length * 5)];
        for (int index = 0; index < segments.Length; ++index)
        {
            segmentBits[index * 5] = Bits(segments[index].Value1);
            segmentBits[index * 5 + 1] = Bits(segments[index].Value2);
            segmentBits[index * 5 + 2] = Bits(segments[index].Value3);
            segmentBits[index * 5 + 3] = Bits(segments[index].Value4);
            segmentBits[index * 5 + 4] = Bits(segments[index].Value5);
        }
        return new(
            source.Type,
            source.NumCV,
            Bits(source.Tension),
            Bits(source.TotalLength),
            cvBits,
            lengths.Select(Bits).ToArray(),
            segmentBits);
    }

    private static void Align4(MemoryStream stream)
    {
        while ((stream.Position & 3) != 0) stream.WriteByte(0);
    }

    private static void WriteWords(MemoryStream stream, uint[] words)
    {
        Span<byte> bytes = stackalloc byte[4];
        foreach (uint word in words)
        {
            BinaryPrimitives.WriteUInt32LittleEndian(bytes, word);
            stream.Write(bytes);
        }
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

internal sealed record JointTreeAsset(
    string Path,
    string RootName,
    JointAsset[] Joints);
internal sealed record JointAsset(
    int Parent,
    int FirstChild,
    int NextSibling,
    uint Flags,
    string ClassName,
    uint[] SrtBits,
    uint[] InverseBits,
    bool InversePresent,
    bool DisplayObjectPresent,
    SplineAsset? Spline,
    JointReferenceAsset[] References);
internal sealed record SplineAsset(
    byte Type,
    short NumCv,
    uint TensionBits,
    uint TotalLengthBits,
    uint[] CvBits,
    uint[] LengthBits,
    uint[] SegmentBits);
internal sealed record JointBlobAsset(
    int NameOffset,
    int NameLength,
    int CvOffset,
    int LengthOffset,
    int SegmentOffset);
internal sealed record JointReferenceAsset(
    int Flags,
    uint RefType,
    uint PayloadBits,
    HSD_JOBJ? TargetSource,
    int TargetJoint,
    uint IkBoneBits,
    uint IkRotateBits,
    JointRvalueAsset[] Rvalues);
internal sealed record JointRvalueAsset(
    int Flags,
    HSD_JOBJ? TargetSource,
    int TargetJoint);
