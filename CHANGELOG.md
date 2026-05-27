# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2026-05-27

Pure PyPI-polish patch. No code changes, no behavior changes — just signals downstream tooling reads off PyPI metadata.

### Added
- `src/llmhq_promptops/py.typed` (PEP 561 marker). Downstream type-checkers (mypy, pyright, basedpyright) now trust the type hints we already ship throughout the public API. The marker is included in the wheel via a new `[tool.setuptools.package-data]` block in `pyproject.toml`.
- `Typing :: Typed` classifier. The companion PyPI signal to the marker — surfaced on the project page next to the existing classifiers.

### Changed
- `Development Status` classifier bumped from `4 - Beta` to `5 - Production/Stable`. Two stable releases (v0.3.0, v0.3.1), 210 tests, a documented production runtime path (`AutoResolver` + snapshot), and an incident-archaeology hero flow shipped — the package is past Beta in practice. The PyPI badge now reflects that.

### Not in this release (intentionally deferred)
- Dropping Python 3.8 / 3.9 classifiers + bumping `requires-python` to `>=3.10`. That's a breaking change in semver terms (existing 3.8/3.9 users would suddenly fail to install the next version), so it batches into v0.4.0 alongside D9 (hooks-opt-in default change) and M9 (Tier 2 error codes).

## [0.3.1] - 2026-05-27

Patch release. Phase 1.5b's first batch: docs + demo + a resolver bug discovered while smoke-testing the demo.

### Added (Phase 1.5b — M6: Incident-archaeology sample repo)
- New `examples/incident-archaeology-demo/` directory with `setup.sh` that builds `/tmp/promptops-demo` as a fresh git repo with deterministic pre-baked history (5 prompt commits + 4 deploy events spanning 2026-05-15 → 2026-05-24). Backdates via `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` so the demo timeline is the same regardless of when the script runs. Idempotent — re-running rebuilds from scratch.
- Three sample prompts (`summarizer`, `intent-classifier`, `refund-resolver`) with realistic, lightly-evolving content across the timeline so blame queries return meaningful diffs.
- `examples/incident-archaeology-demo/README.md` walks through the hero flow (`deploy list` → `blame --at <ts>` → `blame --at <ts> --prompt <id>` → `snapshot build`) with an ASCII timeline so users can predict what each query resolves to.

### Added (Phase 1.5b — M7: Scripted screencast)
- New `examples/incident-archaeology-demo/screencast.sh` — 60-second regenerable walkthrough. Color-coded prompts, sleeps between steps, recording instructions in the header (`asciinema rec`, `agg` for GIF). `PAUSE=1 ./screencast.sh` runs faster for CI smoke testing.

### Changed (Phase 1.5b — M8: README + URL fix)
- **Fixed:** `pyproject.toml [project.urls]` pointed at `github.com/llmhq-hub/llmhq-promptops` (with a spurious `llmhq-` prefix) — broken since at least v0.2.0. Now resolves to the actual repo at `github.com/llmhq-hub/promptops`. PyPI Homepage / Documentation / Repository / Issues / Changelog links work again.
- README rewritten per D10/D11 from the original DX plan: new tagline (*"Git blame for prompts..."*), Key Features reordered to lead with v0.3.0 hero surface (blame, snapshot, deploy log), dual Quick Start (Path A: 60-second demo via the sample repo; Path B: try it on your own repo).
- Stale prod placeholder URLs (`your-org/llmhq-promptops`) replaced everywhere with the correct `github.com/llmhq-hub/promptops`.

### Fixed (Phase 1.5b — M5c: Resolver multi-prompt blame)
- `GitVersioning._resolve_version_to_commit` previously only walked the prompt's own commit history, so resolving prompt A at a commit that only touched prompt B failed with "not found" — even though prompt A existed at that commit unchanged. This made `promptops blame` fail for any prompt not directly modified by the deploy commit (i.e. most prompts in any realistic deploy). Discovered while smoke-testing the M6 demo, where 2 of 3 prompts failed to resolve at the demo's hero-query timestamp.
- Fix: after the prompt-history walk, fall back to `Repo.commit(version)` so any valid git ref (full SHA, prefix, tag name, `HEAD~N`) resolves. `get_prompt_at_version`'s `commit.tree[path]` lookup already handles "file existed at that commit but wasn't changed by it" cleanly. Net effect: `promptops blame` now resolves every prompt that existed at the deploy commit, not just ones that were directly touched.

### Tests
- 4 new regression tests in `tests/test_git_versioning.py::TestResolveAtUnrelatedCommit`: resolve at commit that only touched another prompt (the actual bug), resolve at full SHA, resolve at 7-char SHA prefix (was previously rejected), invalid refs still return None.
- Demo `setup.sh` smoke-tested end-to-end: pre-fix resolved 1 of 3 prompts at the hero timestamp, post-fix resolves 3 of 3.
- 220 tests pass in dev (was 216 in v0.3.0). Zero regressions across M1–M5b.

### Deferred to v0.4.0
- D9 from the original M8 spec (`promptops init repo` defaulting to `--no-hooks` so hooks become a deliberate second step via `promptops hooks install`). Held out of v0.3.1 because it's a backwards-incompatible default change inappropriate for a patch release.

## [0.3.0] - 2026-05-27

Phase 1.5a — Production Runtime + Incident Archaeology. Adds a pluggable Resolver layer, build-time snapshot support (Docker images without `.git/`), a deploy event log, and `promptops blame --at <timestamp>` for incident archaeology. Also fixes a long-standing bug where untagged commits returned a position-based fake semver, and ships a migration tool for users moving off that behavior. Plus a pre-existing version-string desync (`__version__` was stuck at "0.1.0" while the package shipped as 0.2.0) is fixed here.

### Added (Phase 1.5a — M1: Resolver Protocol)
- New `core/resolver.py` module with `Resolver` Protocol (PEP 544 `@runtime_checkable`), `ResolvedPrompt` frozen dataclass (text + version + commit + resolved_at + source + prompt_id), and `GitResolver` implementation.
- `PromptManager.__init__` now accepts an optional `resolver=` keyword argument. Default is `GitResolver(repo_path)`, preserving v0.2.0 behavior.
- `PromptManager.resolve(prompt_reference)` returns a `ResolvedPrompt` with provenance metadata — for callers that need version/commit info (e.g., incident archaeology logging), not just a rendered string.
- Public exports: `Resolver`, `ResolvedPrompt`, `GitResolver`.

### Changed
- `PromptManager._validate_setup` no longer checks for git directly. Git presence validation now lives in `GitResolver.__init__`. This allows future resolvers (e.g., `SnapshotResolver` in M3) to validate their own backends, enabling production usage in Docker images without `.git/`.

### Fixed (Phase 1.5a — M2: Stable version identifiers)
- `GitVersioning._generate_version` no longer fabricates a position-based semver (`v1.0.0`, `v1.0.1`, …) for untagged commits. The previous fallback derived the version from a commit's index in `iter_commits` output, so the same commit's "version" would shift every time a new commit landed — directly breaking incident archaeology (`promptops blame --at <timestamp>`).
- Untagged commits now return a stable, immutable identifier of the form `commit-<8charsha>`. Tagged-commit behavior is unchanged. Lookup by short SHA continues to work, and lookup by the new `commit-<sha>` form also works.

### Added (Phase 1.5a — M2b: Retroactive version tagging)
- New `promptops migrate tag-history` CLI command. Walks each prompt's commit history (oldest first) and creates immutable per-prompt git tags of the form `prompt-<id>-v<X>.<Y>.<Z>`. This is the migration path for users moving off the pre-M2 fake-semver fallback: after tagging, `get_latest_version()` returns the real version instead of `commit-<sha>`. Options: `--prompt <id>` (single-prompt mode), `--dry-run`, `--start-version v0.1.0`. The command is idempotent — existing tags are skipped, not overwritten.
- `GitVersioning._get_tag_version` is now prompt-aware: per-prompt tags scoped to the resolved prompt take priority over legacy global `v1.2.3` tags. Both forms are still recognized.

### Added (Phase 1.5a — M4: Deploy event log)
- New `core/deploys.py` module with `DeployEvent` frozen dataclass (timestamp + env + commit + deployed_by + metadata) and `DeployLog` class providing append-only access to `.promptops/deploys.jsonl`. `DeployLog.find_at(timestamp, env=None)` is the lookup primitive that M5's `promptops blame --at <ts>` will use: given a moment in production, return the most recent deploy event at-or-before that moment.
- New `promptops deploy event` CLI command. Appends one record to `.promptops/deploys.jsonl` capturing the env, commit (default HEAD), actor (default git user.name, then `$USER`), and arbitrary `--metadata key=value` annotations. Atomic POSIX `O_APPEND` writes — safe under concurrent deploys.
- New `promptops deploy list` CLI command. Prints recent events newest-first, optionally filtered by `--env`, capped by `--limit`.
- Public exports: `DeployEvent`, `DeployLog`.
- Tolerant reader: empty lines and lines that fail to parse as a `DeployEvent` are skipped with a logged warning, not a hard error. A single corrupted line should not stop the audit trail from being readable.

### Changed (Phase 1.5a — M4: Pre-commit early-exit)
- `hooks/pre_commit.py` now defers `SemanticVersionDetector` instantiation until prompts are detected. Commits that don't touch `.promptops/prompts/*.yaml` (e.g. ordinary source-code commits, or `[deploy]` commits that only append to `deploys.jsonl`) skip the heavy regex/diff setup and exit immediately. The non-verbose path also drops its banner so clean commits stay silent.

### Added (Phase 1.5a — M3: Snapshot + AutoResolver)
- New `core/snapshot.py` module with `write_snapshot()` (builds a self-contained JSON file from a git repo), `SnapshotResolver` (implements the `Resolver` Protocol by reading the snapshot — no git needed at runtime), and `AutoResolver` (auto-picks snapshot when available, falls back to git, supports explicit `prefer="snapshot"`/`"git"`). This unlocks the production-runtime use case: ship a Docker image without `.git/`, point `PromptManager(resolver=AutoResolver(...))` at the snapshot.
- New `promptops snapshot build` CLI command. Builds `.promptops/snapshot.json` containing raw YAML text + resolved version + commit for every prompt. Options: `--output PATH`, `--commit <sha|tag>` (default HEAD), `--pretty` (indented JSON). Atomic temp-file + `os.replace` write so concurrent readers never see a half-written snapshot.
- New `promptops snapshot inspect` CLI command. Summary view by default, `--detail` to show full prompt text. Supports `--snapshot PATH` for non-default locations.
- Public exports: `SnapshotResolver`, `AutoResolver`, `write_snapshot`.
- Snapshot file format documented in `core/snapshot.py` (schema_version=1).

### Changed (M3 fallout — GitVersioning)
- `GitVersioning._resolve_version_to_commit` now also accepts a full 40-char SHA as a valid lookup (in addition to the existing version-label and 8-char short-SHA matches). This was needed for `write_snapshot(commit=<sha>)` to pin to a specific commit; the previous behaviour required callers to round-trip through tags or short SHAs. Internal helper change — no public-API impact for v0.2.0 callers.

### Added (Phase 1.5a — M5: Incident archaeology)
- New `promptops blame --at <timestamp>` CLI command. The Phase 1.5a hero use case: given a moment in production, show *which* deploy was running and *which* prompt versions were resolved at that deploy's commit. Composes `DeployLog.find_at()` (M4) with `AutoResolver.resolve()` (M3) — no new core code needed, just the CLI glue.
- Supports `--at <iso>` / `--at <date>` / `--at now`. Naive timestamps are assumed UTC with a stderr note. Defaults to `--env prod`; `--prompt <id>` switches from the all-prompts summary to a full-text view of that prompt. Helpful errors when the timestamp predates any deploy or when the env filter has no matches.

### Added (Phase 1.5a — M5b: Backfill from git log)
- New `promptops backfill-deploys --from-git-log` CLI command. Walks git log, finds commits matching a regex (default `^\[deploy\]`), and creates one `DeployEvent` per match using the commit's authored timestamp + author. Escape hatch for repos that adopt promptops mid-stream and need the audit trail to cover historical deploys.
- Idempotent: `(commit, env)` is the dedupe key, so repeated runs and parallel `--env prod` + `--env staging` runs are both safe.
- Backfilled events carry `metadata.backfilled="true"` + `metadata.source="git-log"` so downstream analytics can distinguish them from real-time events recorded by `promptops deploy event`.
- `--dry-run` to preview, `--pattern` for custom commit-message regex.

### Tests
- New `tests/test_resolver.py` with 26 tests covering ResolvedPrompt roundtrip, Resolver Protocol structural typing, GitResolver constructor + all version references, PromptManager resolver injection, and backwards compatibility.
- New `tests/test_git_versioning.py` with 13 tests covering the M2 fix (commit-reference format, immutability across new commits, tagged-commit precedence, roundtrip via `get_prompt_at_version`) and the M2b per-prompt tag recognition (priority over legacy tags, scoping to the correct prompt, the no-`v`-prefix form).
- New `tests/test_migrate_cli.py` with 11 tests covering the `migrate tag-history` CLI: happy path (single prompt, all prompts, custom start version), idempotency, error paths (invalid version, invalid prompt id, non-git directory, empty prompts dir), and end-to-end integration with `GitVersioning.get_latest_version`.
- New `tests/test_deploys.py` with 25 tests covering `DeployEvent` (construction validation, tz-aware timestamp required, to/from-dict roundtrip, JSONL format) and `DeployLog` (atomic append, multi-event ordering, tolerant iter_events that skips empty + malformed lines, `find_at` semantics with env filter, `events_for_env` chronological ordering).
- New `tests/test_deploy_cli.py` with 13 tests covering `promptops deploy event` (defaults from git, explicit `--commit`/`--by`/`--metadata`, malformed metadata errors, missing-env errors, multiple events in a row, file format) and `promptops deploy list` (empty-log helpful message, newest-first ordering, env filter, `--limit` cap).
- New `tests/test_snapshot.py` with 27 tests covering `write_snapshot` (default + custom path, top-level fields, prompt coverage, entry shape, pretty vs packed, pinning to a specific commit, non-git rejection) and `SnapshotResolver` (missing-file/invalid-JSON/wrong-schema/missing-prompts rejection, every documented version reference, every error path, full round-trip parity with `GitResolver.resolve(...,"working")`).
- New `tests/test_auto_resolver.py` with 12 tests covering `AutoResolver` (`prefer="auto"` detection: snapshot-present, no-snapshot-but-git, snapshot-only-no-git Docker case, neither-available; `prefer="snapshot"` and `prefer="git"` explicit modes with missing-backend errors; invalid `prefer` rejected; `resolve()` delegation; `PromptManager(resolver=AutoResolver(...))` end-to-end on a Docker-style directory without `.git/`).
- New `tests/test_snapshot_cli.py` with 13 tests covering `promptops snapshot build` (default path, custom output, pretty vs packed, `--commit` pinning to historical SHA, prompt count summary, non-git error) and `promptops snapshot inspect` (summary mode, `--detail` mode showing full text, missing-file error, malformed-snapshot error, `--snapshot PATH` for explicit path).
- New `tests/test_blame_cli.py` with 15 tests covering `promptops blame`: `_parse_timestamp` (now alias, ISO Z, ISO offset, bare date as UTC midnight, invalid input); happy path (finds deploy, lists prompts, query-after-deploy still finds it, `--prompt` full-text view, `now` alias); error paths (no deploy log with helpful message, timestamp before any deploy, wrong env filter, invalid prompt id, missing `--at`, unknown prompt at deploy commit).
- New `tests/test_backfill_deploys_cli.py` with 12 tests covering `promptops backfill-deploys`: requires `--from-git-log` gate, creates one event per matching commit with backfilled metadata, chronological oldest-first ordering, summary count, `--dry-run` writes nothing, idempotency (re-run skips), `(commit, env)` dedupe key (same commit recorded for prod and staging both succeeds), custom `--pattern`, invalid-regex error, zero-matches reports nothing, `--env` override, non-git directory error.

## [0.2.0] - 2026-04-18

### Security
- Fixed Jinja2 Server-Side Template Injection (SSTI) — replaced `Environment` with `SandboxedEnvironment` to block class traversal attacks
- Fixed path traversal via unsanitized `prompt_id` in SDK and CLI — added strict input validation (`[a-zA-Z0-9][a-zA-Z0-9_-]*`)
- Fixed arbitrary code execution via `exec()` in hook test validation — replaced with `ast.parse()` syntax checking
- Fixed git argument injection via filenames starting with `--` — added `--` separators to git subprocess calls
- Fixed non-atomic file writes in pre-commit hook — now uses temp file + `os.replace()`
- Fixed TOCTOU race condition in hook installation backup

### Added
- Input validation module (`core/validation.py`) with `validate_prompt_id`, `validate_version`, `sanitize_path`, `check_file_size`
- 35 security regression tests (`tests/test_security.py`)

### Changed
- CLI `render` and `create` commands now validate file paths are within the working directory
- File reads now enforce a 1MB size limit to prevent memory exhaustion

## [0.1.0] - 2024-07-01

### Added
- 🚀 **Initial Release** - Core prompt management framework
- 🔄 **Automated Git Versioning** - Zero-manual versioning with git hooks
- 📝 **Version References** - Support for `:unstaged`, `:working`, `:latest`, `:v1.2.3` references
- 🐍 **Python SDK** - Complete SDK for prompt resolution and management
- 🔧 **CLI Framework** - Comprehensive command-line interface
- ⚙️ **Git Hooks** - Pre-commit and post-commit automation
- 📊 **Markdown Reports** - Automated version change documentation
- 🧪 **Testing Framework** - Prompt validation and testing capabilities

### Features

#### Core SDK
- `PromptManager` - Central prompt resolution and management
- `GitVersioning` - Git-based version control and file state detection  
- `PromptTemplate` - YAML parsing and Jinja2 template rendering
- `SemanticVersionDetector` - Automated MAJOR/MINOR/PATCH analysis

#### CLI Commands
- `promptops init repo` - Project initialization with automatic hook setup
- `promptops test status` - Show all prompt states and version information
- `promptops test diff` - Compare versions with detailed output
- `promptops test runtest` - Version-aware prompt testing
- `promptops hooks install/status/configure` - Git hook management
- `promptops create prompt` - New prompt template creation

#### Git Integration
- **Pre-commit Hook** - Automatic version detection and updating
- **Post-commit Hook** - Git tagging and report generation
- **Semantic Versioning** - Intelligent change analysis
- **File State Tracking** - Working/staged/committed state detection

#### SDK Features
- **Version-aware Resolution** - Smart default version selection
- **Variable Validation** - Type checking and required field validation
- **Framework Agnostic** - Works with any LLM framework (OpenAI, Anthropic, etc.)

### Technical Details
- **Python Support**: 3.8+
- **Dependencies**: Minimal core dependencies (Typer, Jinja2, PyYAML, GitPython)
- **License**: MIT
- **Package Format**: Modern Python packaging with pyproject.toml

### Documentation
- Comprehensive README with usage examples
- CLI help documentation for all commands
- SDK API documentation with type hints
- Git workflow integration guides

### Known Issues
- Rich formatting disabled in CLI help to ensure compatibility across environments
- Some LLM provider integrations require optional dependencies

---

## Release Notes

### v0.1.0 - Foundation Release
This initial release establishes the core architecture for git-native prompt management. The focus is on reliability, automation, and developer experience.

**Key Achievement**: Zero-manual versioning workflow where developers can commit prompt changes and have versions automatically detected, updated, and tagged without any manual intervention.

**Next Planned Features**:
- Framework adapters (LangChain, LangGraph)
- Multi-LLM testing and comparison
- Advanced analytics and reporting  
- CI/CD pipeline integrations

### Migration Guide
This is the initial release - no migration needed.

### Upgrade Instructions
Install with pip:
```bash
pip install llmhq-promptops
```

For development:
```bash
git clone https://github.com/llmhq-hub/promptops.git
cd llmhq-promptops
pip install -e .
```