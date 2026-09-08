internal static class GameplaySourceGraphScope
{
    // GALE01 playable fighter DAT names from ft/kinds/* Init_DatFilename.
    // Nana and Kirby's copy/hat archives are reached gameplay dependencies.
    internal static readonly string[] FighterPrefixes =
    [
        "PlCa", "PlDk", "PlFx", "PlGw", "PlKb", "PlKp", "PlLk",
        "PlLg", "PlMr", "PlMs", "PlMt", "PlNs", "PlPe", "PlPk",
        "PlPp", "PlNn", "PlPr", "PlSs", "PlYs", "PlZd", "PlSk",
        "PlFc", "PlCl", "PlDr", "PlFe", "PlPc", "PlGn",
    ];

    private static readonly HashSet<string> EffectFiles = new(StringComparer.Ordinal)
    {
        "EfCaData.dat", "EfCoData.dat", "EfDkData.dat", "EfFeData.dat",
        "EfFxData.dat", "EfGnData.dat", "EfIcData.dat", "EfKbData.dat",
        "EfKpData.dat", "EfLgData.dat", "EfLkData.dat", "EfMnData.dat",
        "EfMrData.dat", "EfMsData.dat", "EfMtData.dat", "EfNsData.dat",
        "EfPeData.dat", "EfPkData.dat", "EfPrData.dat", "EfSsData.dat",
        "EfYsData.dat", "EfZdData.dat",
        // efAsync_DatEntries copy-ability banks, reached through Kirby's
        // original preload table even when a copied fighter is absent at start.
        "EfKbMs.dat", "EfKbZd.dat", "EfKbMr.dat", "EfKbFx.dat",
        "EfKbSs.dat", "EfKbPk.dat", "EfKbLg.dat", "EfKbCa.dat",
        "EfKbDk.dat", "EfKbKp.dat", "EfKbIc.dat", "EfKbGn.dat",
        "EfKbFe.dat",
    };

    internal static bool Includes(string relative)
    {
        string file = Path.GetFileName(relative);
        return file is "PlCo.dat" or "ItCo.dat" or "PdPm.dat" ||
            EffectFiles.Contains(file) ||
            (!file.EndsWith("AJ.dat", StringComparison.Ordinal) &&
             FighterPrefixes.Any(prefix => file.StartsWith(prefix, StringComparison.Ordinal)));
    }

    internal static void ValidateRequiredInputs(IEnumerable<string> paths)
    {
        HashSet<string> files = new(paths.Select(Path.GetFileName)!, StringComparer.Ordinal);
        string[] missing = FighterPrefixes.Select(prefix => prefix + ".dat")
            .Concat(EffectFiles).Where(file => !files.Contains(file)).Order(StringComparer.Ordinal).ToArray();
        if (missing.Length != 0)
            throw new InvalidDataException("Incomplete playable-roster asset input: " + string.Join(", ", missing));
    }
}
