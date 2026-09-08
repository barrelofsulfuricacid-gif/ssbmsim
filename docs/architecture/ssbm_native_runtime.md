# Native SSBM runtime architecture

Status: implementation in progress; acceptance is not yet qualified.

## Definition

The simulator is a native host program built from the gameplay-relevant source
and data of GALE01 NTSC 1.02, plus a native translation of UCF 0.84. It is not
an emulator or static recompiler. Gameplay functions operate on native state,
native references, and pointer-free native assets.

The runtime therefore has no PowerPC registers, guest program counter, guest
RAM/address mapping, GameCube MMIO, translated instruction blocks, or hardware
device model. Rendering and audio calls are removed at reviewed API boundaries;
they are not replaced with fake hardware. Dolphin remains a separate headless
oracle used only to produce comparison traces.

## Source import

A pinned doldecomp/melee revision is the authority for gameplay types,
functions, globals, callback tables, state machines, and update order. The
offline importer and closure tooling:

1. inventory every gameplay-relevant translation unit and dependency;
2. classify platform, rendering, audio, menu, and gameplay symbols explicitly;
3. generate host-compatible includes and native global/table declarations;
4. preserve source function bodies and floating-point expression order where
   host-compilable;
5. emit a manifest linking every generated artifact to the exact upstream
   source file and revision; and
6. fail when a required function, global, callback, or dependency is omitted.

Address-valued constants from the original executable are provenance only.
They are replaced by typed native references or generated indices, never by a
guest address lookup. Undecompiled required gameplay code is a tracked gap; it
cannot fall back to PowerPC execution.

## Asset compiler and loader

`tools/ssbm_asset_compiler` is an offline .NET 8 tool using pinned HSDLib. It
reads owner-extracted DAT files and emits versioned, endian-normalized,
pointer-free sections. Current typed sections cover source provenance and
graphs, fighter attributes, actions/FigaTree data, geometry, dynamics, joint
trees, articles/article graphs, stage collision, effect particle banks, and the
global player-common gameplay table. The stage section also contains typed,
field-by-field endian-normalized `SBM_GroundParam` images and nested stage-
parameter rows for all extracted stage archives.

The pack intentionally contains no DOL image, guest-memory archive image,
relocation-to-guest-address table, boot block, or emulated disc filesystem.
Every relationship is encoded as a checked section-relative offset or stable
index.

Startup maps the pack read-only, validates its sections, and constructs writable
native storage for source objects. `source.storage.v1` preserves implicit
contiguous arrays alongside the explicit graph edges. Required legal-stage
map-head graphs are loaded through the shared source graph loader.

The required step contract forbids host allocation, DAT parsing, filesystem
access, rendering and audio. Fixed arenas and prewarmed pools support this
contract, but allocation-free stepping and complete repeated-match reset
coverage are not yet qualified.

Particle command bytecode remains byte-addressed, but embedded big-endian
floating operands are normalized offline. Startup reconstructs the original
particle bank pointer tables in the fixed arena, while the original source
interpreter retains per-frame ownership and RNG effects. The immutable
`PdPm.dat` common table is referenced directly from the mapped pack because the
decomp only reads it. Imported model effects and legal-stage map-head graphs
are consumed by the native runtime; complete behavioral coverage remains open.

Stage startup copies collision vertices, lines, groups, and their pointer-
bearing header into writable native storage because the original map
initialization mutates line topology. Ground parameters are likewise rebuilt
with native pointers only after the complete section validates. The imported
`grDatFiles_801C6038` now consumes these native views directly, so it performs
no disc lookup or runtime DAT parsing. Source graph storage preserves the
contiguous joint/material animation arrays used by stage callbacks.

## Update order

The native runtime invokes the imported HSD GObj scheduler and native function
pointers directly. Match initialization populates the gameplay process graph;
complete replays run through this loop. Source-owned scene callbacks surround
the scheduler in the original order.

Camera, stage display, particle and text-related CPU state is retained wherever
it affects gameplay, RNG or lifecycle. Only audited low-level graphics/audio
output is bounded. Import and reachability do not establish full equivalence.

Floating-point compilation disables fast math and unintended contraction.
Audited source adaptations preserve the target arithmetic operations. Acceptance
uses exact comparisons; tolerances never turn divergent state into a pass.

## UCF and Slippi validation

Native hooks preserve separate raw controller bytes, processed axes and UCF
input history. Exact UCF 0.84 configuration and recording arithmetic provenance
remain qualification requirements.

Validation maintains three separate results:

- Native endpoint screening compares final recorded fields after all inputs run.
- All-frame recording diagnostics compare the fields exposed in the SLP file.
- Dolphin diagnostics compare instrumented internal state at aligned boundaries.

Slippi playback's first-frame spawn correction can produce values different
from the original recording even with resynchronization disabled. Two startup
witnesses confirm this distinction. Neither a recording-field pass nor a
selected-field oracle pass proves full canonical equivalence.

The full comparator must cover all future-affecting state, stable object and
pointer identities, RNG, articles, stage dynamics and terminal state. This
coverage is incomplete. Acceptance requires 500 complete matches with zero
canonical frame/state divergence, all playable fighters/forms and six legal
stages, as tracked in `docs/status.md`.
