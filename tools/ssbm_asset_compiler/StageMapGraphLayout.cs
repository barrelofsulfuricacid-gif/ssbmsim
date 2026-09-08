using HSDRaw;
using HSDRaw.Melee.Gr;

internal static class StageMapGraphLayout
{
    internal static void Discover(HSDRawFile archive, SBM_Map_Head map, string provenance, SourceGraphBuilder? graph = null)
    {
        int[] strides = [12, 0x34, 4, 8, 8, 4];
        for (int pair = 0; pair < strides.Length; ++pair)
            RestoreArray(archive, map._s, pair * 8, pair * 8 + 4, strides[pair], provenance);
        foreach (SBM_GeneralPoints group in map.GeneralPoints?.Array ?? [])
            RestoreArray(archive, group._s, 4, 8, 4, provenance);
        foreach (SBM_Map_GOBJ group in map.ModelGroups?.Array ?? [])
        {
            RestoreArray(archive, group._s, 0x20, 0x24, 6, provenance);
            RestoreArray(archive, group._s, 0x2C, 0x30, 2, provenance);
        }
        if (graph is not null)
        {
            void Preserve(HSDAccessor[] records, int stride)
            {
                if (records.Length == 0) return;
                int start = archive.GetOffsetFromStruct(records[0]._s);
                if (start < 0 || records.Where((record, index) =>
                    archive.GetOffsetFromStruct(record._s) != start + index * stride).Any())
                    throw new InvalidDataException($"{provenance}: noncontiguous animation record array");
                graph.PreserveContiguousRecords(records.Select(record => record._s).ToArray(), stride, provenance);
            }
            foreach (SBM_Map_GOBJ group in map.ModelGroups?.Array ?? [])
            {
                foreach (var root in group.JointAnimations?.Array ?? [])
                    if (root is not null) Preserve(root.TreeList.Cast<HSDAccessor>().ToArray(), 20);
                foreach (var root in group.MaterialAnimations?.Array ?? [])
                    if (root is not null) Preserve(root.TreeList.Cast<HSDAccessor>().ToArray(), 12);
                foreach (var root in group.ShapeAnimations?.Array ?? [])
                    if (root is not null) Preserve(root.TreeList.Cast<HSDAccessor>().ToArray(), 12);
            }
        }
        map.DiscoverScalarLayout();
    }

    private static void RestoreArray(HSDRawFile archive, HSDStruct owner,
        int pointerOffset, int countOffset, int stride, string provenance)
    {
        if (owner.Length < countOffset + 4)
            throw new InvalidDataException($"{provenance}: truncated counted stage descriptor");
        int count = owner.GetInt32(countOffset);
        if (count < 0)
            throw new InvalidDataException($"{provenance}: negative stage array count");
        if (count == 0) return;
        if (!owner.References.TryGetValue(pointerOffset, out HSDStruct? target))
            throw new InvalidDataException($"{provenance}: missing counted stage array");
        int extent = checked(count * stride);
        if (target.Length < extent)
        {
            HSDStruct complete = DatStructRange.Read(archive, target, extent, provenance);
            target.SetData(complete.GetData());
            target.References.Clear();
            foreach (var edge in complete.References)
                target.SetReferenceStruct(edge.Key, edge.Value);
        }
    }
}
