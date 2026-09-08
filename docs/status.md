# Implementation status

This release contains the current native runtime, source import/adaptation
pipeline, asset compiler, replay diagnostics and regression tests. The retired
authored platform-fighter prototype, its web playtest, milestone journals and
historical captured data are not part of this native distribution.

The following claims are distinct:

| Evidence | What it establishes |
| --- | --- |
| Source/readiness manifest | Identified units and host compile readiness |
| Native build and unit tests | Link closure and tested local contracts |
| Complete Slippi recorded-field comparison | Agreement on the recording's exposed fields |
| Instrumented Dolphin comparison | Agreement on the explicitly observed internal fields |
| Full canonical oracle acceptance | All future-affecting state agrees throughout 500 complete matches |

**Full canonical acceptance is not met.** Unsupported reached functions,
unresolved state identities and incomplete oracle coverage remain tracked gaps.
Allocation-free stepping and repeated-match reset coverage also remain unqualified.
No private run counts or private corpus entries are presented as reproducible
public qualification evidence.

The acceptance target covers all 26 playable fighter/form IDs, both Ice Climbers
subfighters, Battlefield, Final Destination, Yoshi's Story, Dream Land, Fountain
of Dreams and frozen Pokemon Stadium, with random/stage item spawning disabled.
Fighter-created articles and projectiles remain in scope.

Contributors should prioritize complete native source closure, preserved update
order and binary32 arithmetic, explicit startup/reset ownership, canonical state
serialization, and reproducible complete-match evidence. The machine-readable
source authority and compile gaps live in `tools/ssbm_native_import.json` and
`tools/ssbm_native_source_readiness.json`. These describe compile readiness, not
behavioral completeness. The empty public corpus template describes admission
rules without redistributing replay metadata.

## Public release validation

The release was built in a fresh Linux directory using only the published setup
and public dependency downloads. All 28 compiled CTest contracts, 225 Python
tests, two standalone flag-layout regressions and the JavaScript replay-mod
checks passed. Re-running setup also passed.

The optional asset compiler was exercised with local extracted game files, and
the resulting pack was used to execute a complete 10,505-frame recording. The
runner finished and the comparator reported a recorded-field divergence. This
verifies the setup-to-diagnostic workflow; it is not exact-match qualification.
The local inputs, asset pack and report are deliberately not distributed.

The public build also repairs stale test integration: layout tests avoid a
glibc/SDK declaration collision, source-link tests receive the native asset
providers, and memory tests invoke the imported routines explicitly. The old
partial-pack success fixture now checks rejection of missing mandatory sections.
An obsolete null item-draw call was removed because the current source-owned
function requires a real game object. Assertions stay enabled in release tests.
