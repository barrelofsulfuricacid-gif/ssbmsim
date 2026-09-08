using System.Buffers.Binary;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.Melee;
using HSDRaw.Melee.Ef;
using HSDRaw.Melee.Gr;
using HSDRaw.Melee.Pl;
using HSDRaw.Tools.Melee;

const uint PackVersion = 1;
const uint HeaderSize = 96;
const uint DirectoryRecordSize = 80;
const string SourceCatalogSectionName = "source.catalog.v1";
const string FighterAttributesSectionName = "fighter.common_attributes.v1";
const string RequiredHsdLibRevision = "5cf0c4d2d2f0d8d9301f3ed56c3cb826ee80536b";
HashSet<string> legalStageFiles = new(StringComparer.Ordinal)
{
    "GrNBa.dat", "GrNLa.dat", "GrSt.dat",
    "GrOp.dat", "GrIz.dat", "GrPs.dat",
};

if (args.Length != 8 ||
    args[0] != "--input-root" ||
    args[2] != "--output" ||
    args[4] != "--manifest" ||
    args[6] != "--hsdlib-revision")
{
    Console.Error.WriteLine(
        "usage: asset-compiler --input-root <dir> --output <pack> " +
        "--manifest <json> --hsdlib-revision <sha>");
    return 2;
}

string inputRoot = Path.GetFullPath(args[1]);
string outputPath = Path.GetFullPath(args[3]);
string manifestPath = Path.GetFullPath(args[5]);
string hsdLibRevision = args[7].ToLowerInvariant();
if (hsdLibRevision != RequiredHsdLibRevision)
{
    throw new InvalidDataException(
        $"HSDLib revision must be {RequiredHsdLibRevision}, got {hsdLibRevision}");
}
if (!Directory.Exists(inputRoot))
{
    throw new DirectoryNotFoundException(inputRoot);
}
string[] paths = Directory
    .EnumerateFiles(inputRoot, "*", SearchOption.AllDirectories)
    .Where(path =>
    {
        string extension = Path.GetExtension(path);
        string fileName = Path.GetFileName(path);
        return extension.Equals(".dat", StringComparison.OrdinalIgnoreCase) ||
            (extension.Equals(".usd", StringComparison.OrdinalIgnoreCase) &&
             fileName.StartsWith("Pl", StringComparison.Ordinal));
    })
    .OrderBy(path => Path.GetRelativePath(inputRoot, path), StringComparer.Ordinal)
    .ToArray();
if (paths.Length == 0)
{
    throw new InvalidDataException("input root contains no DAT files");
}
GameplaySourceGraphScope.ValidateRequiredInputs(paths);

List<SourceFile> sources = new(paths.Length);
List<FighterAttributes> fighterAttributes = [];
List<FighterActionAsset> fighterActions = [];
List<FighterGeometryAsset> fighterGeometry = [];
List<FighterDynamicsAsset> fighterDynamics = [];
List<JointTreeAsset> jointTrees = [];
List<ArticleSourceAsset> articleSources = [];
List<StageCollisionAsset> stageCollisions = [];
List<StageGroundParamAsset> stageGroundParams = [];
List<StageMapHeadAsset> stageMapHeads = [];
List<StageJointAnimationSet> stageJointAnimations = [];
List<EffectParticleBank> effectParticleBanks = [];
PlayerCommonAsset? playerCommon = null;
SourceGraphBuilder sourceGraphBuilder = new();
List<(string Path, string RootName, SBM_FighterData Fighter)> pendingFighterActions = [];
Dictionary<string, FighterAJManager> fighterAnimationArchives =
    new(StringComparer.Ordinal);
foreach (string path in paths)
{
    byte[] bytes = File.ReadAllBytes(path);
    string relative = Path
        .GetRelativePath(inputRoot, path)
        .Replace(Path.DirectorySeparatorChar, '/');
    HSDRawFile? archive = null;
    if (bytes.Length != 0)
    {
        try
        {
            archive = new HSDRawFile(bytes);
        }
        catch (Exception exception)
        {
            throw new InvalidDataException(
                $"HSDLib rejected DAT '{relative}' ({bytes.Length} bytes)",
                exception);
        }
    }
    sources.Add(new SourceFile(
        relative,
        bytes.LongLength,
        Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
        bytes.Length == 0,
        archive?.Roots.Select(root => new Root(root.Name, root.Data.GetType().FullName ?? "unknown")).ToArray() ?? [],
        archive?.References.Select(root => new Root(root.Name, root.Data.GetType().FullName ?? "unknown")).ToArray() ?? []));
    if (archive is not null)
    {
        ArchiveExternalReferences.ResolveToNull(archive, bytes, relative);
        bool includeSourceGraph = GameplaySourceGraphScope.Includes(relative);
        bool includeLegalStageAuxiliaryGraphs =
            legalStageFiles.Contains(Path.GetFileName(relative));
        for (int rootIndex = 0;
             rootIndex < archive.Roots.Count;
             ++rootIndex)
        {
            HSDRootNode root = archive.Roots[rootIndex];
            bool publicStageImage = includeLegalStageAuxiliaryGraphs &&
                root.Name.EndsWith("_image_desc", StringComparison.Ordinal);
            if (!includeSourceGraph &&
                !(includeLegalStageAuxiliaryGraphs &&
                  (root.Name == "map_head" ||
                   root.Name == "quake_model_set" ||
                   root.Name == "yakumono_param" ||
                   root.Name == "itemdata" ||
                   root.Name == "map_ptcl" ||
                   root.Name == "map_texg" ||
                   (relative == "GrPs.dat" && root.Name == "SIS_GrPStadiumData") ||
                   publicStageImage ||
                   (relative == "GrIz.dat" &&
                    root.Name == "GrdIzumiStar_TopN_joint"))))
            {
                continue;
            }
            if (includeLegalStageAuxiliaryGraphs && root.Data is SBM_Map_Head sourceMap)
                StageMapGraphLayout.Discover(archive, sourceMap, $"{relative}:{root.Name}", sourceGraphBuilder);
            if (publicStageImage)
            {
                // Public image descriptors are looked up by the original stage
                // initialization code even with GX output disabled. HSDLib's
                // name guesser may leave these as HSDAccessor: use its typed
                // descriptor accessor to normalize the mixed u16/u32/f32 fields.
                // Keep the original graph node and image-data relocation.
                root.Data = StageImageDescriptor.Discover(
                    root.Data._s, $"{relative}:{root.Name}");
            }
            if (root.Name == "yakumono_param")
                DiscoverLegalStageYakumonoScalarLayout(relative, root.Data._s);
            if (root.Name == "itemdata")
                DiscoverLegalStageItemScalarLayout(archive, relative, root.Data);
            ArticleVisibilityLayout.DiscoverRoot(relative, root.Name, root.Data._s);
            if (root.Data is SBM_FighterData graphFighter)
            {
                FighterSubactionExtent.Restore(archive, bytes,
                    graphFighter.FighterActionTable?.Commands ?? [],
                    $"{relative}:{root.Name}");
                FighterSpecialScalarLayout.Discover(relative, graphFighter.Attributes2);
                DiscoverArticleSpecialScalarLayout(archive, relative, graphFighter.Articles);
                DiscoverFighterAuxiliaryPartsScalarLayout(
                    relative, root.Name, graphFighter.Articles);
                if (relative == "PlGw.dat" && root.Name == "ftDataGamewatch")
                {
                    HSDStruct lookup = graphFighter.Articles?._s
                        .GetReference<HSDAccessor>(10 * sizeof(uint))?._s
                        ?? throw new InvalidDataException("missing Game & Watch visibility table");
                    int modelCount = graphFighter.ModelLookupTables?.VisibilityLookupLength
                        ?? throw new InvalidDataException("missing Game & Watch model count");
                    FighterVisibilityLayout.Discover(lookup, modelCount,
                        $"{relative}:{root.Name}:items[10]");
                }
                DiscoverFighterAuxiliaryJointScalarLayout(
                    relative, root.Name, graphFighter.Articles);
                ArticleAuxiliaryGraphs.DiscoverFighterAuxiliary(relative, graphFighter.Articles);
                foreach (SBM_FighterAction command in
                         graphFighter.FighterActionTable?.Commands ?? [])
                {
                    if (command.Animation is not null)
                        DiscoverFigaTreeScalarLayout(
                            command.Animation,
                            sourceGraphBuilder,
                            $"{relative}:{root.Name}:{command.Name}");
                }
            }
            if (relative == "PlCo.dat" && root.Name == "ftLoadCommonData")
                DiscoverFighterCommonScalarLayout(root.Data._s);
            if (relative == "ItCo.dat" && root.Name == "itPublicData")
            {
                DiscoverItemCommonScalarLayout(root.Data._s);
                if (root.Data is itPublicData commonItems)
                {
                    ItemStateExtent.RestoreCommon(archive, commonItems.Items);
                    DiscoverArticleSpecialScalarLayout(archive, relative, commonItems.Items);
                    DiscoverArticleSpecialScalarLayout(archive, relative, commonItems.Pokemon);
                }
            }
            try
            {
                root.Data.DiscoverScalarLayout();
            }
            catch (Exception exception)
            {
                throw new InvalidDataException(
                    $"scalar-layout discovery failed for '{relative}:{root.Name}' " +
                    $"({root.Data.GetType().FullName})",
                    exception);
            }
            if (root.Data is HSD_JOBJ jointRoot)
                ValidateJointScalarLayout(relative, root.Name, jointRoot);
            if (root.Data is SBM_FighterData validatedFighter)
            {
                FighterSpecialScalarLayout.Validate(
                    relative, validatedFighter.Attributes2);
            }
            sourceGraphBuilder.AddRoot(
                relative,
                root.Name,
                root.Data.GetType().FullName ?? "unknown",
                0,
                rootIndex,
                root.Data._s);
        }
        for (int referenceIndex = 0;
             includeSourceGraph && referenceIndex < archive.References.Count;
             ++referenceIndex)
        {
            HSDRootNode reference = archive.References[referenceIndex];
            try
            {
                reference.Data.DiscoverScalarLayout();
            }
            catch (Exception exception)
            {
                throw new InvalidDataException(
                    $"scalar-layout discovery failed for reference " +
                    $"'{relative}:{reference.Name}' " +
                    $"({reference.Data.GetType().FullName})",
                    exception);
            }
            sourceGraphBuilder.AddRoot(
                relative,
                reference.Name,
                reference.Data.GetType().FullName ?? "unknown",
                1,
                referenceIndex,
                reference.Data._s);
        }
        if (includeSourceGraph || includeLegalStageAuxiliaryGraphs)
            sourceGraphBuilder.EndArchive();
        string fileName = Path.GetFileName(relative);
        if (fileName.Length == 10 &&
            fileName.StartsWith("Pl", StringComparison.Ordinal) &&
            fileName.EndsWith("AJ.dat", StringComparison.Ordinal) &&
            archive.Roots.Count == 1)
        {
            FighterAJManager manager = new(bytes);
            fighterAnimationArchives.Add(relative, manager);
        }
        foreach (HSDRootNode root in archive.Roots)
        {
            if (relative == "PdPm.dat" && root.Name == "plLoadCommonData")
            {
                if (playerCommon is not null)
                    throw new InvalidDataException("duplicate player common data");
                playerCommon = PlayerCommonSection.Read(
                    relative, root.Name, root.Data);
            }
            if (root.Data is HSD_JOBJ jointTree)
            {
                jointTrees.Add(JointTreeSection.Read(relative, root.Name, jointTree));
            }
            if (root.Data is SBM_Coll_Data collision)
            {
                stageCollisions.Add(StageCollisionSection.Read(relative, root.Name, collision));
            }
            if (root.Data is SBM_GroundParam groundParam)
            {
                stageGroundParams.Add(StageGroundParamSection.Read(
                    relative, root.Name, groundParam));
            }
            if (legalStageFiles.Contains(fileName) &&
                root.Data is SBM_Map_Head mapHead)
            {
                StageMapHeadAsset map = StageMapHeadSection.Read(
                    relative, root.Name, archive, mapHead);
                stageMapHeads.Add(map);
                foreach (StageGeneralPointGroup group in map.GeneralGroups)
                {
                    if (group.RootNode is not null)
                        jointTrees.Add(JointTreeSection.Read(
                            relative, group.TreeName, group.RootNode));
                }
                for (int groupIndex = 0;
                     groupIndex < map.ModelGroups.Length;
                     ++groupIndex)
                {
                    StageModelGroup group = map.ModelGroups[groupIndex];
                    if (group.RootNode is not null)
                        jointTrees.Add(JointTreeSection.Read(
                            relative, group.TreeName, group.RootNode));
                    StageJointAnimationSet[] animationSets =
                        StageJointAnimationSection.Read(
                            relative, root.Name, groupIndex,
                            group.RootNode,
                            group.JointAnimations);
                    stageJointAnimations.AddRange(animationSets);
                    foreach (StageJointAnimationSet set in animationSets)
                    {
                        foreach (StageJointAnimationNode node in set.Nodes)
                        {
                            if (node.ObjectReference is not null &&
                                node.ObjectTreeName is not null)
                                jointTrees.Add(JointTreeSection.Read(
                                    relative, node.ObjectTreeName,
                                    node.ObjectReference));
                        }
                    }
                }
            }
            if (root.Data is SBM_EffectTable effectTable)
            {
                effectParticleBanks.Add(EffectParticleSection.Read(
                    relative, root.Name, effectTable));
            }
            if (root.Data is not SBM_FighterData fighter || fighter.Attributes is null)
            {
                if (root.Data is itPublicData commonItems)
                {
                    if (commonItems.Items is not null)
                        articleSources.Add(ArticleSection.ReadSource(
                            relative, root.Name, 1, commonItems.Items));
                    if (commonItems.Pokemon is not null)
                        articleSources.Add(ArticleSection.ReadSource(
                            relative, root.Name, 2, commonItems.Pokemon));
                }
                continue;
            }
            pendingFighterActions.Add((relative, root.Name, fighter));
            fighterGeometry.Add(FighterGeometrySection.Read(relative, root.Name, fighter));
            fighterDynamics.Add(FighterDynamicsSection.Read(relative, root.Name, fighter));
            if (fighter.Articles is not null)
                articleSources.Add(ArticleSection.ReadSource(
                    relative, root.Name, 0, fighter.Articles));
            const int attributeBytes = 0x184;
            const int attributeWords = attributeBytes / sizeof(uint);
            if (fighter.Attributes._s.Length < attributeBytes)
            {
                throw new InvalidDataException(
                    $"fighter attributes in '{relative}:{root.Name}' are " +
                    $"{fighter.Attributes._s.Length} bytes, expected at least {attributeBytes}");
            }
            uint[] words = new uint[attributeWords];
            for (int index = 0; index < words.Length - 1; ++index)
            {
                words[index] = fighter.Attributes._s.GetUInt32(index * sizeof(uint));
            }
            // ftCo_DatAttrs ends with one u8 weight-independent-throw mask at
            // 0x180 followed by three padding bytes. Treating that mixed word
            // as a PowerPC u32 moves the mask to 0x183 in the native image.
            words[^1] = fighter.Attributes._s.GetByte(0x180);
            fighterAttributes.Add(new FighterAttributes(relative, root.Name, words));
        }
    }
}

static void DiscoverFigaTreeScalarLayout(
    HSD_FigaTree animation,
    SourceGraphBuilder sourceGraphs,
    string provenance)
{
    animation.DiscoverScalarLayout();

    // HSDLib exposes FigaTree.flags only as raw storage, while its track
    // descriptors are embedded in one untyped buffer. Record those scalar
    // fields explicitly so the pointer-free native source graph normalizes
    // their PowerPC byte order instead of materializing byte-swapped u32/u16
    // values on the i686 host.
    _ = animation._s.GetUInt32(0x04);
    int nodeIndex = 0;
    foreach (FigaTreeNode node in animation.Nodes)
    {
        int trackIndex = 0;
        foreach (HSD_Track track in node.Tracks)
        {
            track.DiscoverScalarLayout();
            HSDStruct? buffer = track._s
                .GetReference<HSDAccessor>(0x08)?._s;
            if (buffer is null)
                throw new InvalidDataException(
                    $"FigaTree track buffer is missing for '{provenance}' " +
                    $"at node {nodeIndex}, track {trackIndex}");
            sourceGraphs.PreserveOpaqueBytes(
                buffer,
                $"{provenance}:node={nodeIndex}:track={trackIndex}");
            ++trackIndex;
        }
        ++nodeIndex;
    }
}

static void ValidateJointScalarLayout(
    string relative,
    string rootName,
    HSD_JOBJ root)
{
    int jointIndex = 0;
    foreach (HSD_JOBJ joint in root.TreeList)
    {
        int[] scalarOffsets =
        [
            0x04,
            0x14, 0x18, 0x1C,
            0x20, 0x24, 0x28,
            0x2C, 0x30, 0x34,
        ];
        foreach (int offset in scalarOffsets)
        {
            if (!joint._s.ScalarFields.TryGetValue(offset, out int width) ||
                width != sizeof(uint))
            {
                throw new InvalidDataException(
                    $"JObj scalar layout is incomplete for " +
                    $"'{relative}:{rootName}' joint {jointIndex}: " +
                    $"missing {offset}+4");
            }
        }
        ++jointIndex;
    }
}

static void DiscoverArticleSpecialScalarLayout(
    HSDRawFile archive,
    string relative,
    SBM_ArticlePointer? articles)
{
    if (articles is null)
        return;

    SBM_Article[] slots = articles.Articles;
    for (int slotIndex = 0; slotIndex < slots.Length; ++slotIndex)
    {
        SBM_Article? article = slots[slotIndex];
        RestoreItemSubactionGraphs(relative, slotIndex, article);
        HSDStruct? attributes = article?.ParametersExt?._s;
        if (attributes is null)
            continue;
        ArticleAuxiliaryGraphs.RestoreExtent(archive, relative, slotIndex, attributes);
        ArticleAuxiliaryGraphs.Discover(relative, slotIndex, attributes);
        if ((attributes.Length & (sizeof(uint) - 1)) != 0)
        {
            throw new InvalidDataException(
                $"article special attributes are not word-aligned in " +
                $"'{relative}' slot {slotIndex}: {attributes.Length} bytes");
        }

        // SBM_Article.ParametersExt is the character/item-specific attribute
        // block assigned directly to Article::x4_specialAttributes. HSDLib
        // necessarily exposes this character-dependent C struct as an opaque
        // accessor. Imported gameplay code consumes its non-pointer storage as
        // 32-bit f32/s32/u32 fields, so explicitly discover each such word and
        // leave relocation words for SourceGraphBuilder to replace with native
        // pointers. This is archive-wide normalization, not an item-specific
        // replay correction.
        for (int offset = 0; offset < attributes.Length; offset += sizeof(uint))
        {
            if (!attributes.References.ContainsKey(offset))
                _ = attributes.GetUInt32(offset);
        }
    }
}

static void DiscoverFighterAuxiliaryPartsScalarLayout(
    string relative,
    string rootName,
    SBM_ArticlePointer? items)
{
    if (relative != "PlPr.dat" || rootName != "ftDataPurin")
        return;

    // ftPr_Init_8013C360 treats x48_items[1] as an opaque word array and
    // passes &items_shifted[1] to ftParts_8007487C. In source terms the
    // embedded record is { u32 model_num; void* (*vis_table)[4] } at offsets
    // 4 and 8 of that target node. HSDLib preserves the relocation at 8 but
    // cannot infer the scalar at 4 through SBM_ArticlePointer, so discover
    // precisely that field before pointer-free graph serialization.
    if (items is null || items._s.Length < 2 * sizeof(uint))
    {
        throw new InvalidDataException(
            "PlPr.dat:ftDataPurin is missing x48_items[1]");
    }
    HSDAccessor? shifted =
        items._s.GetReference<HSDAccessor>(sizeof(uint));
    if (shifted is null || shifted._s.Length < 3 * sizeof(uint) ||
        !shifted._s.References.ContainsKey(2 * sizeof(uint)))
    {
        throw new InvalidDataException(
            "PlPr.dat:ftDataPurin x48_items[1] is missing its FtPartsDesc");
    }
    uint modelNum = shifted._s.GetUInt32(sizeof(uint));
    if (modelNum > 11U)
    {
        throw new InvalidDataException(
            $"PlPr.dat:ftDataPurin has invalid auxiliary model count {modelNum}");
    }

    HSDStruct visTable =
        shifted._s.References[2 * sizeof(uint)];
    if ((visTable.Length % (4 * sizeof(uint))) != 0)
    {
        throw new InvalidDataException(
            "PlPr.dat:ftDataPurin auxiliary visibility table is misaligned");
    }
    foreach ((int tableOffset, HSDStruct lookup) in visTable.References)
    {
        if ((tableOffset % sizeof(uint)) != 0 ||
            tableOffset > visTable.Length - sizeof(uint) ||
            lookup.Length < checked((int) modelNum * 2 * sizeof(uint)))
        {
            throw new InvalidDataException(
                "PlPr.dat:ftDataPurin has an invalid FtPartsVisLookup table");
        }
        FighterVisibilityLayout.Discover(lookup, checked((int)modelNum),
            $"{relative}:{rootName}:auxiliary visibility");
    }
}

static void DiscoverFighterAuxiliaryJointScalarLayout(
    string relative,
    string rootName,
    SBM_ArticlePointer? items)
{
    if (relative != "PlSk.dat" || rootName != "ftDataSeak")
        return;

    // Sheik's side-special source treats x48_items[4] and x48_items[5] as
    // HSD_Joint** tables and consumes item[2] as an HSD_Joint tree
    // (ftSk_SpecialS_80110610). HSDLib's generic SBM_Article view instead
    // interprets offset 8 as a hurtbox-bank pointer, so reflection-based
    // discovery cannot see the joint scalars below that relocation. Apply the
    // source-proven view explicitly; the underlying pointer graph is unchanged.
    foreach (int slotIndex in new[] { 4, 5 })
    {
        if (items is null ||
            items._s.Length < checked((slotIndex + 1) * sizeof(uint)) ||
            items._s.GetReference<HSDAccessor>(
                slotIndex * sizeof(uint)) is not HSDAccessor table ||
            table._s.Length < 3 * sizeof(uint) ||
            table._s.GetReference<HSD_JOBJ>(
                2 * sizeof(uint)) is not HSD_JOBJ joint)
        {
            throw new InvalidDataException(
                $"{relative}:{rootName} is missing x48_items" +
                $"[{slotIndex}][2] HSD_Joint data");
        }
        joint.DiscoverScalarLayout();
        ValidateJointScalarLayout(
            relative,
            $"{rootName}:x48_items[{slotIndex}][2]",
            joint);
    }
}

static void RestoreItemSubactionGraphs(
    string relative,
    int slotIndex,
    SBM_Article? article)
{
    HSDArrayAccessor<SBM_ItemState>? states = article?.ItemState;
    if (states is null)
        return;

    HashSet<HSDStruct> visited = new(ReferenceEqualityComparer.Instance);
    SBM_ItemState[] entries = states.Array;
    for (int stateIndex = 0; stateIndex < entries.Length; ++stateIndex)
    {
        HSDStruct? script = entries[stateIndex].SubactionScript?._s;
        if (script is not null)
        {
            RestoreItemSubactionGraph(
                relative, slotIndex, stateIndex, script, visited);
        }
    }
}

static void RestoreItemSubactionGraph(
    string relative,
    int slotIndex,
    int stateIndex,
    HSDStruct script,
    HashSet<HSDStruct> visited)
{
    if (!visited.Add(script))
        return;

    if (script.Length == 0 || (script.Length & 3) != 0)
    {
        throw new InvalidDataException(
            $"item command graph has invalid extent in '{relative}' " +
            $"slot {slotIndex} state {stateIndex}: {script.Length} bytes");
    }

    int offset = 0;
    while (true)
    {
        byte[] bytes = script.GetData().ToArray();
        if (offset == bytes.Length)
        {
            // DAT structure discovery omits trailing all-zero words. The item
            // interpreter nevertheless requires an explicit four-byte reset
            // command after the final nonzero command.
            script.Resize(checked(offset + sizeof(uint)));
            break;
        }
        if (offset > bytes.Length - sizeof(uint))
        {
            throw new InvalidDataException(
                $"item command word is truncated in '{relative}' slot " +
                $"{slotIndex} state {stateIndex} at byte {offset}");
        }

        int opcode = bytes[offset] >> 2;
        if (opcode == 0)
            break;
        int commandBytes = opcode switch
        {
            5 or 7 => 8,
            10 => 20,
            11 => 24,
            16 => ItemCommand16Bytes(bytes, offset),
            >= 1 and <= 25 => 4,
            _ => throw new InvalidDataException(
                $"invalid item command opcode {opcode} in '{relative}' " +
                $"slot {slotIndex} state {stateIndex} at byte {offset}"),
        };
        int next = checked(offset + commandBytes);
        if (next > bytes.Length)
        {
            // Every byte omitted by HSDLib here is zero in the original
            // contiguous archive image. Restore the command's full logical
            // extent plus its zero reset word so native node allocations do
            // not make the source interpreter walk into an adjacent heap node.
            script.Resize(checked(next + sizeof(uint)));
            break;
        }
        offset = next;
    }

    foreach (HSDStruct target in script.References.Values)
    {
        RestoreItemSubactionGraph(
            relative, slotIndex, stateIndex, target, visited);
    }
}

static int ItemCommand16Bytes(byte[] bytes, int offset)
{
    int nestedOpcode =
        (((bytes[offset] << 8) | bytes[offset + 1]) >> 2) & 0xFF;
    return nestedOpcode is >= 0 and <= 2 or >= 10 and <= 11 ? 12 : 8;
}

static void DiscoverFighterCommonScalarLayout(HSDStruct root)
{
    ItemSwingScalarLayout.Discover(root);
    const int fighterCommonBytes = 0x818;
    HSDAccessor? fighterCommon = root.GetReference<HSDAccessor>(0);
    if (fighterCommon is null ||
        fighterCommon._s.Length < fighterCommonBytes)
    {
        throw new InvalidDataException(
            "PlCo.dat:ftLoadCommonData is missing the complete " +
            "0x818-byte ftCommonData table");
    }
    for (int offset = 0;
         offset < fighterCommonBytes;
         offset += sizeof(uint))
    {
        _ = fighterCommon._s.GetUInt32(offset);
    }

    // pData[1] is Fighter_804D6550: one ftCo_ItemThrowAttrs record for every
    // common item-throw motion from ftCo_MS_LightThrowF through
    // ftCo_MS_HeavyThrowLw4, inclusive. ftCo_80095D5C indexes this table via
    // motion_id * 12 - 0x468, while ftCo_80095EFC casts the same base directly
    // to { f32 velocity_mul, f32 angle, f32 x8 } records. HSDLib preserves the
    // relocation but exposes the table as untyped bytes, so mark all 26 * 3
    // words before graph serialization rather than fixing only a reached row.
    const int itemThrowRecordCount = 26;
    const int itemThrowScalarCount = 3;
    const int itemThrowTableBytes =
        itemThrowRecordCount * itemThrowScalarCount * sizeof(uint);
    HSDAccessor? itemThrowAttributes =
        root.GetReference<HSDAccessor>(sizeof(uint));
    if (itemThrowAttributes is null ||
        itemThrowAttributes._s.Length < itemThrowTableBytes)
    {
        throw new InvalidDataException(
            "PlCo.dat:ftLoadCommonData is missing the complete 26-row " +
            "Fighter_804D6550 item-throw table");
    }
    for (int offset = 0; offset < itemThrowTableBytes; offset += sizeof(uint))
        _ = itemThrowAttributes._s.GetUInt32(offset);

    // pData[3] is Fighter_804D6548: the nine newest-to-oldest stale-move
    // damage reductions consumed directly as f32 by ft_80089118. The archive
    // exposes this table as an untyped accessor, so mark every word before
    // graph serialization or the native runtime sees raw PowerPC byte order.
    const int staleMoveSlotCount = 9;
    HSDAccessor? staleMoveWeights =
        root.GetReference<HSDAccessor>(3 * sizeof(uint));
    if (staleMoveWeights is null ||
        staleMoveWeights._s.Length < staleMoveSlotCount * sizeof(uint))
    {
        throw new InvalidDataException(
            "PlCo.dat:ftLoadCommonData is missing the nine stale-move weights");
    }
    for (int slot = 0; slot < staleMoveSlotCount; ++slot)
        _ = staleMoveWeights._s.GetUInt32(slot * sizeof(uint));

    // pData[5] is Fighter_804D6540: one pointer per FighterKind. Each
    // pointed-to record is { u8[4]* parts, s32 count }. HSDLib preserves the
    // relocation topology but exposes these nested records as untyped data,
    // so DiscoverScalarLayout cannot know that x4 is a PowerPC s32. Mark it
    // explicitly or a count of one materializes as 0x01000000 on i686.
    // The runtime also indexes the FTKIND_NONE (0x21) descriptor when a
    // common action's FigaTree is not character-specific, so this serialized
    // table has FTKIND_MAX + 1 entries even though ordinary fighter loops use
    // kinds [0, FTKIND_MAX).
    const int fighterKindDescriptorCount = 0x22;
    HSDAccessor? partTables =
        root.GetReference<HSDAccessor>(5 * sizeof(uint));
    if (partTables is null ||
        partTables._s.Length < fighterKindDescriptorCount * sizeof(uint))
    {
        throw new InvalidDataException(
            "PlCo.dat:ftLoadCommonData is missing the complete " +
            "Fighter_804D6540 pointer table");
    }
    for (int kind = 0; kind < fighterKindDescriptorCount; ++kind)
    {
        HSDAccessor? descriptor =
            partTables._s.GetReference<HSDAccessor>(kind * sizeof(uint));
        if (descriptor is null)
            continue;
        if (descriptor._s.Length < 2 * sizeof(uint))
        {
            throw new InvalidDataException(
                $"PlCo.dat Fighter_804D6540[{kind}] is shorter than 8 bytes");
        }
        HSDAccessor? parts = descriptor._s.GetReference<HSDAccessor>(0);
        int count = descriptor._s.GetInt32(sizeof(uint));
        if (count < 0 || count > 32)
        {
            throw new InvalidDataException(
                $"PlCo.dat Fighter_804D6540[{kind}] has invalid count {count}");
        }
        if ((count == 0 && parts is not null) ||
            (count != 0 &&
             (parts is null || parts._s.Length < count * sizeof(uint))))
        {
            throw new InvalidDataException(
                $"PlCo.dat Fighter_804D6540[{kind}] has an invalid parts array");
        }
    }
}

static void DiscoverItemCommonScalarLayout(HSDStruct root)
{
    const int itemCommonBytes = 0x160;
    HSDAccessor? itemCommon = root.GetReference<HSDAccessor>(0);
    if (itemCommon is null || itemCommon._s.Length < itemCommonBytes)
    {
        throw new InvalidDataException(
            "ItCo.dat:itPublicData is missing the complete " +
            "0x160-byte ItemCommonData table");
    }

    // HSDLib's itPublicData accessor preserves the relocation to this table,
    // but does not type its scalar fields. ItemCommonData is consumed directly
    // by the imported item physics and collision code. Mark its PowerPC words
    // explicitly so source.graphs.v2 serializes host-endian scalars. Offset
    // 0x48 is the sole byte field and must retain its original byte position.
    for (int offset = 0; offset < 0x48; offset += sizeof(uint))
        _ = itemCommon._s.GetUInt32(offset);
    for (int offset = 0x4C;
         offset < itemCommonBytes;
         offset += sizeof(uint))
    {
        _ = itemCommon._s.GetUInt32(offset);
    }
}

foreach ((string path, string rootName, SBM_FighterData fighter) in
         pendingFighterActions)
{
    string? directory = Path.GetDirectoryName(path)?.Replace('\\', '/');
    string animationFile = Path.GetFileNameWithoutExtension(path) + "AJ.dat";
    string animationPath = string.IsNullOrEmpty(directory)
        ? animationFile
        : directory + "/" + animationFile;
    fighterAnimationArchives.TryGetValue(animationPath, out FighterAJManager? animations);
    fighterActions.Add(FighterActionSection.Read(path, rootName, fighter, animations));

    SBM_FighterAction[] commands = fighter.FighterActionTable?.Commands ?? [];
    List<Root> animationRoots = [];
    foreach (SBM_FighterAction command in commands)
    {
        if (command.AnimationSize == 0)
            continue;
        string actionName = command.Name ?? string.Empty;
        byte[]? animationData = animations?.GetAnimationData(actionName);
        HSD_FigaTree? animation = command.Animation;
        if (animationData is not null)
        {
            HSDRawFile animationFileData = new(animationData);
            if (animationFileData.Roots.Count != 1 ||
                animationFileData.Roots[0].Name != actionName ||
                animationFileData.Roots[0].Data is not HSD_FigaTree animationTree)
            {
                throw new InvalidDataException(
                    $"invalid AJ animation mini-DAT '{actionName}' for " +
                    $"'{path}:{rootName}'");
            }
            animation = animationTree;
        }
        if (animation is null)
            throw new InvalidDataException(
                $"missing AJ source graph '{actionName}' for " +
                $"'{path}:{rootName}'");
        DiscoverFigaTreeScalarLayout(
            animation,
            sourceGraphBuilder,
            $"{animationPath}:{actionName}");
        int animationRootIndex = animationRoots.Count;
        animationRoots.Add(new(
            actionName,
            animation.GetType().FullName ?? "unknown"));
        sourceGraphBuilder.AddRoot(
            animationPath,
            actionName,
            animation.GetType().FullName ?? "unknown",
            0,
            animationRootIndex,
            animation._s);
    }
    sourceGraphBuilder.EndArchive();
    int animationSourceIndex = sources.FindIndex(source =>
        source.Path == animationPath);
    if (animationSourceIndex < 0)
        throw new InvalidDataException(
            $"missing AJ source catalog entry '{animationPath}'");
    SourceFile animationSource = sources[animationSourceIndex];
    sources[animationSourceIndex] = animationSource with
    {
        Roots = animationRoots.ToArray(),
    };
}

foreach (ArticleSourceAsset source in articleSources)
{
    for (int slotIndex = 0; slotIndex < source.Slots.Length; ++slotIndex)
    {
        HSD_JOBJ? model = source.Slots[slotIndex]?.ModelJoint;
        if (model is not null)
            jointTrees.Add(JointTreeSection.Read(
                source.Path,
                ArticleSection.ModelTreeName(source, slotIndex),
                model));
    }
}

// The source font atlas is embedded in the owner's DOL, not a DAT.
// Pinned decomp config/GALE01/config.yml declares this exact byte range.
string dolPath = Path.GetFullPath(Path.Combine(inputRoot, "..", "sys", "main.dol"));
byte[] dolBytes = File.ReadAllBytes(dolPath);
string dolDigest = Convert.ToHexString(SHA256.HashData(dolBytes)).ToLowerInvariant();
if (dolDigest != "dc21504513424350bda17a7c65e82371b45112a5dfc1e9f2749a8b7ab0eff646")
    throw new InvalidDataException("SIS font atlas requires the pinned GALE01 1.02 main.dol");
byte[] sisFontAtlas = ExtractDolData(dolBytes, 0x8040CD40, 0x23E00);
sources.Add(new SourceFile("../sys/main.dol", dolBytes.Length, dolDigest, false,
    [new Root("HSD_SisLib_FontAtlas", "TextGlyphTexture[287]")], []));
sources.Sort((left, right) => StringComparer.Ordinal.Compare(left.Path, right.Path));
byte[] catalog = BuildCatalog(sources);
SourceGraphAsset sourceGraphs = sourceGraphBuilder.Build();
byte[] fighterData = BuildFighterAttributes(fighterAttributes);
byte[] fighterActionData = FighterActionSection.Build(fighterActions);
byte[] fighterGeometryData = FighterGeometrySection.Build(fighterGeometry);
byte[] fighterDynamicsData = FighterDynamicsSection.Build(fighterDynamics);
byte[] jointTreeData = JointTreeSection.Build(jointTrees);
byte[] articleData = ArticleSection.Build(articleSources);
ArticleGraphAsset articleGraphs = ArticleGraphSection.Build(articleSources);
byte[] stageCollisionData = StageCollisionSection.Build(stageCollisions);
byte[] stageGroundParamData = StageGroundParamSection.Build(stageGroundParams);
byte[] stageMapHeadData = StageMapHeadSection.Build(stageMapHeads);
byte[] stageJointAnimationData =
    StageJointAnimationSection.Build(stageJointAnimations);
byte[] effectParticleData = EffectParticleSection.Build(effectParticleBanks);
if (playerCommon is null)
    throw new InvalidDataException("PdPm.dat:plLoadCommonData is missing");
byte[] playerCommonData = PlayerCommonSection.Build(playerCommon);
byte[] sourceSetDigest = ComputeSourceSetDigest(sources);
PackSection[] sections =
[
    new(1, 1, StableNameHash(SourceCatalogSectionName), catalog, sources.Count, 72),
    new(1, 1, StableNameHash("sis.font_atlas.v1"), sisFontAtlas, 287, 512),
    new(1, 1, StableNameHash("source.storage.v1"), sourceGraphs.StorageData, sourceGraphs.NodeCount, 12),
    new(
        1,
        SourceGraphBuilder.Schema,
        StableNameHash(SourceGraphBuilder.Name),
        sourceGraphs.Data,
        sourceGraphs.RootCount,
        SourceGraphBuilder.RootRecordSize),
    new(
        4,
        1,
        StableNameHash(FighterAttributesSectionName),
        fighterData,
        fighterAttributes.Count,
        32),
    new(
        5,
        StageCollisionSection.Schema,
        StableNameHash(StageCollisionSection.Name),
        stageCollisionData,
        stageCollisions.Count,
        StageCollisionSection.RecordSize),
    new(
        5,
        StageGroundParamSection.Schema,
        StableNameHash(StageGroundParamSection.Name),
        stageGroundParamData,
        stageGroundParams.Count,
        StageGroundParamSection.RecordSize),
    new(
        5,
        StageMapHeadSection.Schema,
        StableNameHash(StageMapHeadSection.Name),
        stageMapHeadData,
        stageMapHeads.Count,
        StageMapHeadSection.MapRecordSize),
    new(
        7,
        StageJointAnimationSection.Schema,
        StableNameHash(StageJointAnimationSection.Name),
        stageJointAnimationData,
        stageJointAnimations.Count,
        StageJointAnimationSection.SetRecordSize),
    new(
        7,
        FighterActionSection.Schema,
        StableNameHash(FighterActionSection.Name),
        fighterActionData,
        fighterActions.Sum(fighter => fighter.Actions.Length),
        FighterActionSection.ActionRecordSize),
    new(
        4,
        FighterGeometrySection.Schema,
        StableNameHash(FighterGeometrySection.Name),
        fighterGeometryData,
        fighterGeometry.Count,
        FighterGeometrySection.FighterRecordSize),
    new(
        4,
        FighterDynamicsSection.Schema,
        StableNameHash(FighterDynamicsSection.Name),
        fighterDynamicsData,
        fighterDynamics.Count,
        FighterDynamicsSection.FighterRecordSize),
    new(
        7,
        JointTreeSection.Schema,
        StableNameHash(JointTreeSection.Name),
        jointTreeData,
        jointTrees.Sum(tree => tree.Joints.Length),
        JointTreeSection.JointRecordSize),
    new(
        6,
        ArticleSection.Schema,
        StableNameHash(ArticleSection.Name),
        articleData,
        articleSources.Sum(source => source.Slots.Length),
        ArticleSection.SlotRecordSize),
    new(
        6,
        ArticleGraphSection.Schema,
        StableNameHash(ArticleGraphSection.Name),
        articleGraphs.Data,
        articleGraphs.RootCount,
        ArticleGraphSection.RootRecordSize),
    new(
        8,
        EffectParticleSection.Schema,
        StableNameHash(EffectParticleSection.Name),
        effectParticleData,
        effectParticleBanks.Count,
        EffectParticleSection.BankRecordSize),
    new(
        9,
        PlayerCommonSection.Schema,
        StableNameHash(PlayerCommonSection.Name),
        playerCommonData,
        PlayerCommonSection.WordCount,
        PlayerCommonSection.WordSize),
];
byte[] pack = BuildPack(sections, sourceSetDigest);

Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
Directory.CreateDirectory(Path.GetDirectoryName(manifestPath)!);
File.WriteAllBytes(outputPath, pack);
Manifest manifest = new(
    PackVersion,
    RequiredHsdLibRevision,
    Convert.ToHexString(sourceSetDigest).ToLowerInvariant(),
    Convert.ToHexString(SHA256.HashData(pack)).ToLowerInvariant(),
    sections.Select(section => new SectionManifest(
        section.Kind,
        section.Schema,
        section.NameHash.ToString("x16"),
        section.Data.Length,
        section.Count,
        section.Stride,
        Convert.ToHexString(SHA256.HashData(section.Data)).ToLowerInvariant())).ToArray(),
    sources,
    DescribeToolAssembly(Assembly.GetExecutingAssembly()),
    DescribeToolAssembly(typeof(HSDRawFile).Assembly));
File.WriteAllText(
    manifestPath,
    JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }) + "\n",
    new UTF8Encoding(false));

Console.WriteLine(
    $"asset-pack=pass files={sources.Count} bytes={pack.Length} " +
    $"sha256={manifest.PackSha256}");
return 0;

static ToolAssemblyManifest DescribeToolAssembly(Assembly assembly)
{
    string configuration = assembly.GetCustomAttribute<AssemblyConfigurationAttribute>()?.Configuration
        ?? throw new InvalidDataException($"Missing build configuration for {assembly.GetName().Name}");
    return new ToolAssemblyManifest(configuration,
        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assembly.Location))).ToLowerInvariant());
}

static byte[] BuildCatalog(IReadOnlyList<SourceFile> sources)
{
    using MemoryStream strings = new();
    List<(ulong Offset, ulong Length)> names = new(sources.Count);
    foreach (SourceFile source in sources)
    {
        byte[] name = Encoding.UTF8.GetBytes(source.Path);
        names.Add(((ulong)strings.Position, (ulong)name.Length));
        strings.Write(name);
    }

    const int catalogHeaderSize = 32;
    const int recordSize = 72;
    int recordsBytes = checked(sources.Count * recordSize);
    byte[] result = new byte[catalogHeaderSize + recordsBytes + checked((int)strings.Length)];
    Span<byte> span = result;
    WriteU32(span, 0, 1);
    WriteU32(span, 4, (uint)sources.Count);
    WriteU64(span, 8, catalogHeaderSize);
    WriteU64(span, 16, (ulong)(catalogHeaderSize + recordsBytes));
    WriteU64(span, 24, (ulong)strings.Length);
    for (int index = 0; index < sources.Count; ++index)
    {
        SourceFile source = sources[index];
        int offset = catalogHeaderSize + index * recordSize;
        WriteU64(span, offset, names[index].Offset);
        WriteU64(span, offset + 8, names[index].Length);
        WriteU64(span, offset + 16, checked((ulong)source.Size));
        Convert.FromHexString(source.Sha256).CopyTo(span[(offset + 24)..(offset + 56)]);
        WriteU32(span, offset + 56, (uint)source.Roots.Count);
        WriteU32(span, offset + 60, (uint)source.References.Count);
        WriteU32(span, offset + 64, source.Empty ? 1U : 0U);
    }
    strings.ToArray().CopyTo(span[(catalogHeaderSize + recordsBytes)..]);
    return result;
}

static byte[] ComputeSourceSetDigest(IReadOnlyList<SourceFile> sources)
{
    using IncrementalHash hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    Span<byte> scalar = stackalloc byte[8];
    foreach (SourceFile source in sources)
    {
        byte[] path = Encoding.UTF8.GetBytes(source.Path);
        BinaryPrimitives.WriteUInt64LittleEndian(scalar, (ulong)path.Length);
        hash.AppendData(scalar);
        hash.AppendData(path);
        BinaryPrimitives.WriteUInt64LittleEndian(scalar, checked((ulong)source.Size));
        hash.AppendData(scalar);
        hash.AppendData(Convert.FromHexString(source.Sha256));
    }
    return hash.GetHashAndReset();
}

static void DiscoverLegalStageYakumonoScalarLayout(
    string relative,
    HSDStruct data)
{
    static void MarkU32(HSDStruct source, int start, int endInclusive)
    {
        for (int offset = start; offset <= endInclusive; offset += sizeof(uint))
            _ = source.GetUInt32(offset);
    }

    static void MarkI16(HSDStruct source, int start, int endInclusive)
    {
        for (int offset = start; offset <= endInclusive; offset += sizeof(short))
            _ = source.GetInt16(offset);
    }

    switch (relative)
    {
        case "GrSt.dat":
            MarkU32(data, 0x00, 0x20);
            break;
        case "GrIz.dat":
            MarkU32(data, 0x00, 0x50);
            break;
        case "GrOp.dat":
            MarkI16(data, 0x00, 0x06);
            MarkU32(data, 0x08, 0x30);
            break;
        case "GrNBa.dat":
            MarkU32(data, 0x00, 0x04);
            break;
        case "GrNLa.dat":
            MarkU32(data, 0x00, 0x0C);
            break;
        case "GrPs.dat":
            MarkU32(data, 0x00, 0x18);
            MarkU32(data, 0x20, 0x44);
            MarkI16(data, 0x48, 0x50);
            break;
    }
}

static void DiscoverLegalStageItemScalarLayout(
    HSDRawFile archive,
    string relative,
    HSDAccessor root)
{
    if (root is not HSDNullPointerArrayAccessor<SBM_MapItem> items)
        throw new InvalidDataException(
            $"legal-stage itemdata has unexpected type in '{relative}'");
    foreach (SBM_MapItem item in items.Array)
    {
        SBM_Article? article = item.Article;
        StageItemSchema.Restore(archive, item, relative);
        RestoreItemSubactionGraphs(relative, item.Index, article);
        HSDAccessor? attributes = article?.ParametersExt;
        if (attributes is null) continue;
        if ((attributes._s.Length & 3) != 0)
            throw new InvalidDataException(
                $"legal-stage item attributes are not word-aligned in " +
                $"'{relative}' for kind {item.Index}");
        // Legal-stage item special attributes are consumed by the imported
        // gameplay code as f32/s32 word arrays. HSDLib intentionally exposes
        // this archive-specific table as an untyped accessor, so record its
        // exact scalar layout before endian normalization.
        for (int offset = 0; offset < attributes._s.Length; offset += 4)
            _ = attributes._s.GetUInt32(offset);
    }
}

static byte[] BuildFighterAttributes(IReadOnlyList<FighterAttributes> fighters)
{
    const int headerSize = 32;
    const int recordSize = 32;
    const int attributeWords = 0x184 / sizeof(uint);
    int recordsBytes = checked(fighters.Count * recordSize);
    int payloadOffset = headerSize + recordsBytes;
    byte[] result = new byte[checked(payloadOffset + fighters.Count * attributeWords * sizeof(uint))];
    Span<byte> span = result;
    WriteU32(span, 0, 1);
    WriteU32(span, 4, (uint)fighters.Count);
    WriteU32(span, 8, attributeWords);
    WriteU32(span, 12, recordSize);
    WriteU64(span, 16, headerSize);
    WriteU64(span, 24, (ulong)payloadOffset);
    for (int fighterIndex = 0; fighterIndex < fighters.Count; ++fighterIndex)
    {
        FighterAttributes fighter = fighters[fighterIndex];
        if (fighter.Words.Length != attributeWords)
        {
            throw new InvalidDataException($"unexpected fighter word count for {fighter.Path}");
        }
        int recordOffset = headerSize + fighterIndex * recordSize;
        int wordsOffset = payloadOffset + fighterIndex * attributeWords * sizeof(uint);
        WriteU64(span, recordOffset, StableNameHash(fighter.Path));
        WriteU64(span, recordOffset + 8, StableNameHash(fighter.RootName));
        WriteU64(span, recordOffset + 16, (ulong)wordsOffset);
        WriteU32(span, recordOffset + 24, attributeWords);
        for (int wordIndex = 0; wordIndex < fighter.Words.Length; ++wordIndex)
        {
            WriteU32(span, wordsOffset + wordIndex * sizeof(uint), fighter.Words[wordIndex]);
        }
    }
    return result;
}

static byte[] ExtractDolData(byte[] dol, uint address, uint length)
{
    if (dol.Length < 0x100) throw new InvalidDataException("Truncated DOL header");
    byte[]? result = null;
    for (int index = 0; index < 11; ++index)
    {
        uint offset = BinaryPrimitives.ReadUInt32BigEndian(dol.AsSpan(0x1C + index * 4));
        uint start = BinaryPrimitives.ReadUInt32BigEndian(dol.AsSpan(0x64 + index * 4));
        uint size = BinaryPrimitives.ReadUInt32BigEndian(dol.AsSpan(0xAC + index * 4));
        if ((ulong)address < start || (ulong)address + length > (ulong)start + size) continue;
        ulong fileOffset = (ulong)offset + address - start;
        if (fileOffset + length > (ulong)dol.Length || result is not null)
            throw new InvalidDataException("Invalid or ambiguous DOL data extent");
        result = dol.AsSpan(checked((int)fileOffset), checked((int)length)).ToArray();
    }
    return result ?? throw new InvalidDataException("DOL does not contain the SIS font atlas");
}

static byte[] BuildPack(IReadOnlyList<PackSection> sections, byte[] sourceSetDigest)
{
    int directoryBytes = checked(sections.Count * (int)DirectoryRecordSize);
    int payloadOffset = Align8(checked((int)HeaderSize + directoryBytes));
    int fileSize = payloadOffset;
    foreach (PackSection section in sections)
    {
        fileSize = checked(Align8(fileSize) + section.Data.Length);
    }
    byte[] result = new byte[fileSize];
    Span<byte> span = result;
    "PFSAPCK\0"u8.CopyTo(span);
    WriteU32(span, 8, PackVersion);
    WriteU32(span, 12, 0x01020304);
    WriteU32(span, 16, HeaderSize);
    WriteU32(span, 20, DirectoryRecordSize);
    WriteU32(span, 24, (uint)sections.Count);
    WriteU64(span, 32, (ulong)result.Length);
    WriteU64(span, 40, HeaderSize);
    WriteU64(span, 48, (ulong)payloadOffset);
    sourceSetDigest.CopyTo(span[56..88]);

    int dataOffset = payloadOffset;
    for (int index = 0; index < sections.Count; ++index)
    {
        PackSection section = sections[index];
        dataOffset = Align8(dataOffset);
        int recordOffset = checked((int)HeaderSize + index * (int)DirectoryRecordSize);
        WriteU32(span, recordOffset, section.Kind);
        WriteU32(span, recordOffset + 4, section.Schema);
        WriteU64(span, recordOffset + 8, section.NameHash);
        WriteU64(span, recordOffset + 16, (ulong)dataOffset);
        WriteU64(span, recordOffset + 24, (ulong)section.Data.Length);
        WriteU32(span, recordOffset + 32, (uint)section.Count);
        WriteU32(span, recordOffset + 36, (uint)section.Stride);
        SHA256.HashData(section.Data).CopyTo(span[(recordOffset + 40)..(recordOffset + 72)]);
        section.Data.CopyTo(span[dataOffset..]);
        dataOffset += section.Data.Length;
    }
    return result;
}

static int Align8(int value) => checked((value + 7) & ~7);

static ulong StableNameHash(string value)
{
    ulong hash = 14695981039346656037UL;
    foreach (byte item in Encoding.UTF8.GetBytes(value))
    {
        hash ^= item;
        hash *= 1099511628211UL;
    }
    return hash;
}

static void WriteU32(Span<byte> bytes, int offset, uint value) =>
    BinaryPrimitives.WriteUInt32LittleEndian(bytes[offset..], value);

static void WriteU64(Span<byte> bytes, int offset, ulong value) =>
    BinaryPrimitives.WriteUInt64LittleEndian(bytes[offset..], value);

internal sealed record Root(string Name, string Type);
internal sealed record FighterAttributes(string Path, string RootName, uint[] Words);
internal sealed record PackSection(
    uint Kind,
    uint Schema,
    ulong NameHash,
    byte[] Data,
    int Count,
    int Stride);
internal sealed record SectionManifest(
    uint Kind,
    uint Schema,
    string NameHash,
    int Bytes,
    int Count,
    int Stride,
    string Sha256);
internal sealed record SourceFile(
    string Path,
    long Size,
    string Sha256,
    bool Empty,
    IReadOnlyList<Root> Roots,
    IReadOnlyList<Root> References);
internal sealed record Manifest(
    uint PackFormatVersion,
    string HsdLibRevision,
    string SourceSetSha256,
    string PackSha256,
    IReadOnlyList<SectionManifest> Sections,
    IReadOnlyList<SourceFile> Files,
    ToolAssemblyManifest ExtractorBuild,
    ToolAssemblyManifest HsdLibBuild);
internal sealed record ToolAssemblyManifest(string Configuration, string AssemblySha256);
