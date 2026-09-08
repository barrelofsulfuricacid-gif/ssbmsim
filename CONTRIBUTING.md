# Contributing

Fork this repository, create a branch, and run `./setup.sh` followed by
`python3 tools/test.py`. Open a pull request explaining the concrete problem,
changed behavior and verification. Prefer a regression that exposes the failure
class over a replay-specific workaround. Game assets are not required for the
default build and test suite.

## Native gameplay changes

Read the [architecture](docs/architecture/ssbm_native_runtime.md) and
[status](docs/status.md). Use pinned source and authoritative game data for
behavioral decisions. Preserve source callback/update order, binary32 operation
order, UCF history, object lifetime and reset semantics. Do not add emulation,
per-replay exceptions, oracle-fed production state, or silent unsupported-path
fallbacks. Unsupported reached behavior must fail closed.

Host adaptations belong in `tools/host_adaptations/`. Source and adaptation
hashes are checked by the importer; changes require corresponding manifest and
readiness evidence. `python3 tools/probe_ssbm_native_sources.py --help` describes
the readiness probe. Build success alone does not qualify gameplay fidelity.

Before adding substantial tooling or subsystems, inspect maintained upstreams,
forks, releases and issues. Record compatible reusable work, pinned revisions,
licenses and the reason for custom code in a focused design note.

## Tests and replay evidence

`./setup.sh` runs the compiled native CTest suite. `python3 tools/test.py` runs
the Python/source regressions using the fetched dependencies. Install replay
tools to also run the JavaScript replay-mod tests. Report any skipped optional
checks. [Replay validation](docs/replays.md) explains the additional evidence
required for match comparisons.

Keep personal paths, names, emails, connect codes, replay metadata, credentials
and generated game assets out of commits and issue attachments. Run
`python3 tools/check_public_tree.py` before submitting. Git commit identities
are public; configure your preferred public identity or GitHub noreply address
before committing. Review diagnostics before sharing them.

## Licensing

Contributions to original project code are accepted under 0BSD. Preserve
upstream copyright notices and source provenance. The project license does not
relicense third-party/game-derived source or grant rights to game assets.
See [THIRD_PARTY.md](THIRD_PARTY.md).
