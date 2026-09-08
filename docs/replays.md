# Replay diagnostics

First follow [setup](setup.md) to build the native runner, compile your game asset
pack and install the locked parser. Keep `.slp` files and generated reports local.
Reports may contain input paths and recording metadata.

```sh
python3 tools/ssbm_native_full_match.py /path/to/match.slp \
  --parser-prefix tools/replay \
  --runner build/native/ssbm_native_replay_runner \
  --asset-pack build/assets/gale01.pack \
  --report build/match-report.json
```

Use `--help` for all options. Default comparison scope is `all-frames`.
`--comparison-scope final-state` is a faster endpoint screen and must not be
reported as all-frame or canonical equivalence. The native runner accepts a CSV
input stream produced by the wrapper; prefer the wrapper for admission checks
and replay settings. `--input-csv` and `--native-csv` save diagnostic streams.

Admission is fail-closed: complete matches, legal stages, random/stage items off,
and an explicit frozen flag for Pokemon Stadium. Raw controller bytes, UCF state,
recording arithmetic profile and enabled gameplay modifications matter. Do not
switch arithmetic profiles mid-match to conceal a divergence.

## Corpus work

`tools/ssbm_acceptance_corpus.json` is an empty public template containing the
500-match target, fighter/stage IDs and admission policy. Copy it to
`build/local-corpus.json` and populate it with local recordings and provenance.
Use `python3 tools/ssbm_corpus_coverage.py --help` and pass your manifest to the
corpus tools. No private corpus, historical run counts, or players' metadata is
bundled. A complete-match pass on recorded fields is still pending full canonical
qualification.

## Separate headless Dolphin oracle

`tools/bootstrap_ssbm_checkpoint_oracle.sh` and
`tools/bootstrap_ssbm_exiai_oracle.sh` preserve the optional instrumented oracle
workflow. They have additional build/runtime dependencies and are outside the
default setup/CI lane. Read the scripts and run the diagnostic tools' `--help`
before use. They require your own GALE01 image and local oracle configuration.
The public release does not claim a freshly qualified oracle installation.

Dolphin must remain headless, with no GUI fallback. Oracle resynchronization,
startup spawn correction and selected observed fields can affect comparisons.
The acceptance target requires every future-affecting state field, stable
object/pointer identity, RNG, article and stage state, and terminal state over
complete matches. Selected-field diagnostic success is narrower evidence.
