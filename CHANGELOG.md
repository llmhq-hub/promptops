# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-07-31

The retention-wedge batch: the daily-use loop (`history`, `doctor`, a real
`test diff`), CI templates, five new examples, three guides, and `E012`
enforced at build time.

Four breaking changes, each tagged **[BREAKING]** below. See
[`docs/migration-v0.4-to-v0.5.md`](docs/migration-v0.4-to-v0.5.md) for the
upgrade guide. Most users are unaffected; the one that fails *silently* is
`ResolvedPrompt.version`, so read that section even if the others look
irrelevant.

### Added

- **Three documentation guides** (TODO-S1, S2, S6): [`docs/day-0-playbook.md`](docs/day-0-playbook.md) walks the `blame` to `history` to `diff` sequence for finding which prompt caused a production incident, including what to do when blame cannot answer; [`docs/production-deployment.md`](docs/production-deployment.md) covers the snapshot pipeline, a Docker recipe that fails the build if `.git/` leaks in, the CI gate, and how `AutoResolver` actually chooses a backend; [`docs/migration-from-hardcoded-prompts.md`](docs/migration-from-hardcoded-prompts.md) moves an existing codebase off string literals one prompt at a time. Every command in all three runs as written against the built CLI (12 distinct commands, executed in clean repositories), the Day 0 playbook's output blocks are byte-exact CLI output verified by script rather than transcribed, and all 32 relative links were checked to resolve.
- README gains a Guides section indexing all five docs, and the CLI table now lists `promptops history` and `promptops doctor`.
- **CI templates and five new examples.** `.pre-commit-hooks.yaml` at the repository root makes PromptOps consumable from the [pre-commit](https://pre-commit.com) framework (`promptops-doctor`, `promptops-snapshot-build`), for teams already standardized on it rather than on PromptOps' own git hooks. `examples/github-actions/promptops-diff.yml` is a copy-in workflow that posts a single sticky PR comment with the semver impact of every changed prompt, edited in place on later pushes rather than appended. It ships as an example rather than an active workflow because this repository has no `.promptops/prompts/` of its own and it would never fire here.
- `examples/` grows from 2 to 7 (TODO-S7): `docker-snapshot/` (production runtime with no `.git/`, asserting `ResolvedPrompt.source == "snapshot"`), `github-actions/`, `hooks-lifecycle/` (install, use, uninstall, newly relevant since hooks became opt-in in v0.4.0), `error-handling/` (catching `PromptOpsError` and branching on `.code`), and `fastapi-service/` (one manager at startup, `AutoResolver`, error codes mapped onto HTTP status). All but `fastapi-service/` run with only `llmhq-promptops` installed.
- **`promptops history <prompt-id>`** (TODO-S3): every version a prompt has been, newest first, with the deploys that actually shipped each one. A deploy event records the *repository* commit, not the commit that last touched the prompt, so each deploy is attributed to the newest prompt version committed at or before it: the version that was genuinely live at that moment, matching `promptops blame --at` semantics. A deploy predating every version of a prompt is reported against none of them rather than pinned to the oldest. Flags: `--env`, `--limit` (default 20), `--json`.
- **`promptops doctor`** (TODO-S4): six checks in one command, covering `.promptops/` structure and config parse, hook installation, snapshot freshness (`generated_from_commit` against HEAD), deploy-log health including the malformed-line count from `DeployLogRead.skipped`, prompts with no committed version, and which backend `AutoResolver` will pick here. Exits 0 when every check is OK or WARN and 1 when any fails: WARN is reserved for states you may have chosen deliberately (hooks have been opt-in since v0.4.0, a repo can legitimately have no snapshot yet) so warnings never fail CI. Flags: `--json`. Backed by the new `core/health.py`.
- **`promptops test diff` now reports semver impact.** New `core/impact.py` grades a prompt change from its *variable signature* and declared models: MAJOR when a required variable is added, removed, renamed, or retyped, when an optional variable is promoted to required, or when a declared model is dropped; MINOR when an optional variable is added or removed, a required one is relaxed to optional, a model is added, or an optional variable's default changes; PATCH when only prose moved; NONE when nothing did. Prose is deliberately never graded: the variable interface is the only part of a prompt with a caller-facing contract, and a rule that guessed at intent would produce annotations nobody trusts.
- `promptops test diff --exit-code` gates CI on that verdict: `0` none/patch, `2` minor, `3` major. This borrows git's `--exit-code` *flag* but not its *numbers*: `git diff --exit-code` returns `1` for "differences found", while PromptOps reserves `1` for "the command failed" because there are three severities to encode. Do not assume exact git parity.
- Without `--exit-code` the command still always exits `0` on success, so existing usage is unaffected. To stop a hand-written CI step from silently passing a breaking change, the command prints `note: exiting 0, pass --exit-code to make this major fail CI` whenever impact is MINOR or MAJOR and the flag was omitted.
- `promptops test diff --json` emits `{prompt, version1, version2, identical, diff, impact, changes[]}` for tooling and PR-comment integrations.
- 39 new tests across `tests/test_impact.py` and `tests/test_diff_cli.py`.
- **`PROMPTOPS_E012` is now enforced at build time. [BREAKING]** A `promptops snapshot build` that previously succeeded now fails if any template uses a loader-requiring Jinja tag. The resulting snapshot was already guaranteed-broken at render time, so this converts a production failure into a build failure, but it is a behavior change for anyone whose build currently passes. `--allow-includes` restores the old outcome. `promptops snapshot build` scans every prompt for Jinja tags that require a template loader (`{% include %}`, `{% import %}`, `{% from %}`, `{% extends %}`) and refuses to write a snapshot containing one. PromptOps renders in a `SandboxedEnvironment` constructed without a loader, so these tags could never resolve at runtime: previously such a template snapshotted silently and only failed later, at render time, in production. The error names the prompt id and every offending line number. Nothing is written when the check fails, so a rejected build leaves no partial or stale snapshot behind.
- `promptops snapshot build --allow-includes` downgrades the check to a warning and builds anyway, for unblocking an unrelated investigation. The resulting snapshot still fails at render time, and the CLI prints an on-screen warning naming each affected prompt so the tradeoff is never silent. `write_snapshot()` gains a matching `allow_includes=False` keyword argument.
- New public helper `find_unsupported_includes(text)` in `core/snapshot.py`, returning `(line_number, keyword)` pairs. Tags appearing in ordinary prose ("please include the account tier") and tags inside a Jinja comment (`{# {% include "x" %} #}`) are not flagged; supported control tags such as `{% if %}` and `{% for %}` are unaffected.
- 19 new tests in `tests/test_snapshot_includes.py`.

### Changed

- **`promptops test diff` prints a real unified diff. [BREAKING for anyone parsing its stdout]** It previously printed two 500-character truncated content blobs, which could not be reviewed. Output is now `difflib.unified_diff` with colour applied only when stdout is a TTY and `NO_COLOR` is unset. The human-readable format is replaced wholesale, so any script scraping it must move to `--json`, which exists precisely so that output format changes stop being breaking changes.
- `docs/error-codes.md`: the E012 entry no longer describes a reserved, unimplemented code. It documents the real check, the fix, and the escape hatch.
- `GitVersioning.get_prompt_versions` no longer swallows genuine git failures silently. It still returns `[]` for a prompt with no commits, which is correct and load-bearing (a newly created, uncommitted prompt legitimately has no history, and `get_latest_version` / `list_prompt_statuses` rely on it), but a real failure is now logged with the prompt id and exception type instead of being indistinguishable from "no history yet". The public contract is unchanged, so the three internal callers are unaffected.
- **PromptOps now works without the git *binary* installed, which the snapshot-only production runtime always claimed.** `core/git_versioning.py` imported GitPython at module scope, and GitPython runs a `refresh()` at import time that raises when there is no git executable on `PATH`. So `import llmhq_promptops` failed outright, taking the snapshot runtime with it. This mattered because that runtime is the headline v0.3.0 feature: the README tells you to ship `snapshot.json` in a Docker image, and `python:3.11-slim` has no git binary. The docs conflated two different things, since running without the `.git/` *directory* worked while running without the git *binary* did not, and nobody reading "no git needed in production" would draw that distinction. GitPython is now imported lazily at the single point that needs a repository, so importing the package and resolving from a snapshot never touch it. Verified by building an actual container with no git binary and resolving a prompt from a snapshot inside it.
- New `PROMPTOPS_E018` (git binary missing), distinct from `E005` (`.git/` directory absent): the repository may be perfectly fine and it is the tool that is missing, so the two need different fixes. Its hint points production users at the snapshot path rather than at installing git. GitPython's own `$GIT_PYTHON_REFRESH` advice is no longer leaked to users.
- **[BREAKING]** `GitVersioning.is_git_repo()` can now **raise** `PromptOpsError` (E018) where it previously always returned a bool. It is a public method on a public class, so a caller doing `if git.is_git_repo():` with no exception handling will now propagate on a machine with no git binary. That is the intended outcome (the previous answer was actively wrong), but it is a signature change in practice and callers that must not raise should catch `PromptOpsError`. It no longer reports a missing git binary as "not a repository". Because `PromptOpsError` subclasses `ValueError` (the v0.4.0 back-compat decision), its bare `except ValueError` was swallowing E018 and sending callers to look for a `.git/` that was present all along. Worth noting as a general hazard of that subclassing choice: any `except ValueError` that converts to a boolean rather than re-raising can silently absorb a structured error.
- Module-level GitPython imports removed from `cli/commands/backfill_deploys.py` and `cli/commands/migrate.py` too, so `promptops --help` no longer requires a git binary.
- 7 new tests in `tests/test_no_git_binary.py`, run as real subprocesses with a stripped `PATH`, which is the only honest way to reproduce an import-time failure in a dependency.
- **`promptops init repo` now anchors `.promptops/` to the repository root.** It previously created the directory tree relative to the CWD while `_install_hooks` walked up to the git root, so running `init` from a subdirectory left prompts in `services/api/.promptops/` and hooks in the root `.git/hooks/`. The root pre-commit hook then looked for `.promptops/prompts/` relative to itself, found nothing, and silently versioned nothing: hooks installed, prompts created, and automatic versioning quietly never firing. Both now use a shared `_repo_root()` helper, and `init` prints where it wrote whenever that is not the current directory, so writing outside the CWD is never silent.
- **`promptops history --limit` says what it hid.** It truncated with no indication, which reads as "this is the whole history" when it is not. Now prints `Showing 1 of 3 versions. Pass --limit 3 to see them all.` when anything was cut, and nothing when it was not. `--json` gains `shown` and `total`.
- **`promptops blame`'s unresolved-prompt notes keep their width.** The reason line rendered `str(exc)`, spending 18 of its 120 display columns on the `[PROMPTOPS_E003] ` prefix. It now prints the code compactly as `[E003]` and gives the message its own 120 columns.
- `_is_git_repo` catches `FileNotFoundError`/`OSError` as well as `CalledProcessError`, so an absent git binary yields `False` rather than propagating.
- **`promptops blame` reports a version instead of a raw commit SHA. [BREAKING for SDK callers]** `ResolvedPrompt.version` now carries a version label rather than echoing the ref that was passed in, so `GitResolver.resolve(prompt_id, "<sha>").version` returns `v1.2.0` where it previously returned `<sha>`. This is the one break in this release that fails **silently**: nothing raises, the call keeps working, and the field simply holds different data. Anyone feeding that value back into a lookup, a cache key, or a comparison must check it. `ResolvedPrompt.commit` still carries the SHA and is the right field for that use. It previously printed `version: 30e4326ac8aa2ee187b9d850659fa8d4dca392b4` under a field labelled "version", while `promptops history` reported `v1.0.0` for the same prompt in the same repository. Two commands disagreed, and the hero command gave the worse answer. New `GitVersioning.version_at_commit(prompt_id, commit_sha)` answers "which version was in effect at this commit" and `GitResolver` uses it whenever it resolves at a specific ref. Note this is deliberately *not* the exact inverse of `commit_for_version`: a deploy commit usually did not touch the prompt being blamed, so "which version is tagged at this commit" would answer nothing for almost every real query. It walks back to the newest prompt-modifying commit that is an ancestor of the target. Untagged prompts get the same `commit-<sha8>` label `history` already shows, so the two commands now always agree. Closes C3 from the v0.4.0 release-readiness audit. 13 new tests in `tests/test_version_at_commit.py`.

### Fixed (pre-release review)

- **The E012 scan missed six of the cases it exists to catch, and rejected a seventh it should have allowed.** Probing every input against a real loaderless `SandboxedEnvironment`, rather than against the pattern itself, is what surfaced them. The pattern accepted `{%-` but not `{%+`, Jinja's other whitespace-control form, so `{%+ include "x" %}` passed straight through; and the scan iterated `splitlines()`, so its `\s*` had no newline left to cross, making every multi-line form of `include`/`import`/`from`/`extends` invisible. It now scans the whole string and derives the line number from the match offset, reporting the line each tag opens on. Separately, `{% raw %}` makes its body literal text, so an include inside one can never need a loader: flagging it was a false positive that blocked a build which succeeded before E012 existed. Raw blocks are now blanked like comments, and a real include following a raw block is still caught.
- **`promptops doctor` failed on the snapshot-only container this release adds support for.** `get_prompt_versions` sat outside the versions check's `try`, so in an image with prompts on disk and no git binary its E018 escaped to the generic handler, which reported FAIL and told the user they had found a PromptOps bug. `doctor` exited 1 on a perfectly healthy container. E018 is now caught and reported as a WARN naming the snapshot runtime as the expected reason.
- **`promptops doctor` claimed snapshot freshness it never verified.** `_head_sha` returns `None` whenever HEAD is unknowable (no git binary, no `.git/`, a repo with no commits), the staleness comparison is guarded on it and so silently did not run, and the OK branch then reported "snapshot.json is current, at HEAD" regardless. It now reports the commit the snapshot was built from and states plainly that it cannot compare against HEAD.
- **Every documented install now resolves to a version that works.** Six were wrong. Both pre-commit snippets pinned `rev: v0.4.0`, a tag at which neither `.pre-commit-hooks.yaml` nor `promptops doctor` exists. The production-deployment guide's Dockerfile was worse: `FROM python:3.11-slim` plus an unpinned install, which is exactly the image where 0.4.0's module-scope GitPython import fails, so the documented production deployment could not start. The GitHub Action, `examples/README.md`, and `fastapi-service/requirements.txt` are pinned to `>=0.5.0` for the same class of reason.
- **The Day 0 playbook shipped the raw-SHA bug this release fixes.** Its Step 1 output block showed `version: 99f3a08e...`, the pre-fix behavior, while Step 2 of the same guide showed `v1.2.0` for that same commit. Step 3 was wrong too: it omitted the command's header line and claimed a hunk header the CLI does not emit. The guides were written before the blame, `init` and git-binary fixes landed and were never re-run. All three blocks are now real output from a repository built to match the guide's narrative.
- **The GitHub Actions template could have its step outputs forged by prompt content.** The `$GITHUB_OUTPUT` heredoc used a fixed delimiter, and the table it wraps is built from prompt variable names, which are free-form YAML and may contain newlines. A variable named `"pwned\nPROMPTOPS_EOF\nworst=0"` closes the heredoc early and sets `worst=0`, which is the value the optional "Fail on MAJOR impact" gate reads, so a crafted prompt could silence the one protective control the template offers. Closed from both sides: a random delimiter per run, and whitespace collapsing plus pipe escaping in the extracted details.
- **The Actions template's fork limitation is now documented.** It triggers on `pull_request`, and GitHub grants a forked PR a read-only `GITHUB_TOKEN` regardless of the `permissions:` block, so the comment step fails with a 403 on every external contributor's PR. Nothing said so. Both the workflow and its README now explain it, and why `pull_request_target` is not a free upgrade.
- **Deleted `requirements.txt`.** It omitted GitPython entirely and still pinned `typing_extensions`, dropped as a dependency in v0.4.0, so `pip install -r requirements.txt` produced an environment where `import llmhq_promptops` failed. `CONTRIBUTING.md` pointed at it and now points at `pip install -e '.[dev]'`. `pyproject.toml` is the single source of truth.
- The registry/documentation sync check skips when `docs/error-codes.md` is absent instead of failing. The sdist ships `tests/` but not `docs/`, which made the sdist's own test suite unpassable for a reason that says nothing about the code under test.

## [0.4.0] - 2026-06-13

The breaking-change batch. All six lanes (A–F) landed, plus a full pre-release review pass (product-bug, security, and docs-alignment fixes). See [`docs/migration-v0.3-to-v0.4.md`](docs/migration-v0.3-to-v0.4.md) for the upgrade guide covering every breaking change below.

### Added (Lane B — M9: Tier 2 error system)
- New `core/errors.py` with `PromptOpsError(code, message, hint, doc_url)`. Subclasses `ValueError`, so every pre-v0.4.0 `except ValueError` handler and `pytest.raises(ValueError, match=...)` assertion keeps working unchanged. `str(e)` renders `[PROMPTOPS_E0XX] message` + `Hint:` + `Docs:` lines; `to_dict()` gives a JSON-friendly shape for structured logging. **[BREAKING for exact-string consumers]** every upgraded error's message text now carries the `[PROMPTOPS_E0XX]` prefix and trailing `Hint:`/`Docs:` lines. `except ValueError` and substring/`match=` checks are unaffected; downstream code that compares error messages by *exact equality* or parses them by fixed offset must update.
- 17-code registry (`PROMPTOPS_E001`–`E017`) documented in the new `docs/error-codes.md`. Each code has a stable meaning, a "when you'll see it" section, and a fix. E012 is reserved for the planned Jinja2-include build scan.
- 20 raise sites upgraded across `prompt_manager.py`, `core/resolver.py`, `core/snapshot.py`, `core/validation.py`, `core/deploys.py`, and the `blame` CLI (which now surfaces `PROMPTOPS_E011` with the backfill hint on an empty deploy log — the empty-state spec from the Phase 1.5a eng review).
- `PromptOpsError` exported from the package root: `from llmhq_promptops import PromptOpsError`.
- 26 new tests in `tests/test_errors.py`, including a registry-sync layer that fails if `docs/error-codes.md` and `core/errors.py` ever drift (every constant documented, every documented code defined, no duplicate values).

### Changed (Lane A — D9: hooks become opt-in) **[BREAKING]**
- `promptops init repo` no longer installs git hooks by default. It creates the `.promptops/` directory tree + a default `config.yaml` and never touches `.git/hooks/` unless `--with-hooks` is passed. Enabling automatic versioning is now a deliberate second step: `promptops hooks install`. Rationale: `init` is the first command every new user runs; silently writing into `.git/hooks/` on first contact is a trust violation for exactly the architect persona the tool targets. The README has documented this two-step model since v0.3.1 — the code now matches.
- `promptops init repo` is now idempotent on config: re-running it never clobbers an existing `.promptops/config.yaml`.
- `--with-hooks` keeps the old behavior available explicitly (interactive config questions included); `--no-hooks` remains accepted as the now-redundant opt-out spelling.
- 8 new tests in `tests/test_init_cli.py` pin the contract: default init leaves `.git/hooks/` untouched, points at `promptops hooks install`, preserves user config on re-run; `--with-hooks --non-interactive` installs both hooks.

### Changed (Lane C — deploy log performance + integrity) **[BREAKING: iteration order + find_at tie-break]**
- `DeployLog` reads are now cached per `(mtime_ns, size)` of the underlying file and `find_at` binary-searches a lazily-built per-env timestamp index — O(log n) per query instead of a full-file scan + re-parse on every call. A `blame` against a years-old log costs one parse, not one per query.
- New `DeployLog.read()` → `DeployLogRead(events, skipped_lines)` public API. Malformed lines are still skipped (a corrupted line must not kill the audit log) but never silently: the count and 1-based line numbers are reported, and `promptops blame` now prints a warning naming the affected lines before showing its answer — closing the worst silent-failure mode in the hero command.
- `DeployEvent` serialized-size cap (`MAX_EVENT_BYTES`, 4000) is enforced on the **append path** (`DeployLog.append`), where the POSIX `O_APPEND`-under-`PIPE_BUF` atomicity guarantee actually lives — not at construction. A `DeployEvent` is a valid value object at any size; only appending one relies on atomicity. This means a valid pre-cap event already on disk still parses on read instead of being misreported as malformed. Oversized lines on read are skipped-and-counted (they can't have been written atomically), never crash the read.
- **[BREAKING]** `DeployLog.iter_events()` / `all_events()` / `events_for_env()` now yield events in **timestamp order** (was file order). Identical for normally-appended logs; the documented contract for backfilled/merged ones. Any consumer that assumed strict file order must adjust (none in this codebase do — all are order-independent).
- **[BREAKING]** `find_at` tie-break on equal timestamps now returns the **last** file-order event (was the first), matching append-only "latest wins" semantics.
- `DeployEvent.commit` is now validated as a 7–64 char hex git SHA at construction (security: deploy commits flow into blame's resolver). Real git SHAs always pass; non-hex placeholders no longer construct.
- Read-path safety: a `(FileNotFoundError)` between `exists()`/`stat()`/`open()` no longer leaks a raw traceback; a deleted/rotated log invalidates the cache (no more ghost answers from `find_at`); a 50 MB whole-log ceiling (`MAX_DEPLOY_LOG_BYTES`) blocks a runaway/poisoned `deploys.jsonl` from OOM-ing CI; the per-env index build is thread-race-safe (returns a local, never `KeyError`s under concurrent `read()`).
- 24 new tests across `tests/test_deploys.py` + `tests/test_blame_cli.py`: size caps (event + whole-log), commit-SHA validation, skip accounting, cache hit/invalidation across appends and **after deletion**, out-of-order (backfilled) logs, 1000-event scale sanity, and blame-CLI warning + git-preference behavior.

### Changed (Lane D — resolver polish)
- `GitVersioning.commit_for_version(prompt_id, version)` is now public API (promoted from `_resolve_version_to_commit`, which remains as a deprecated alias). `GitResolver` no longer reaches into a private method — the M5c fallback behavior is a documented contract now.
- `AutoResolver` logs one INFO line at construction naming the chosen backend — `snapshot mode (path, built <ts> from commit <sha>)` or `git mode (path)`. When the resolver picks the "wrong" backend (stale snapshot in dev, unexpected git fallback), this line is the first thing that explains why. Closes the S5/D12 startup-log gap from the DX review.
- 2 new tests assert both log lines via `caplog`.

### Changed (Lane E — PromptManager correctness) **[BREAKING]**
- Render/parse error handling narrowed (was `except Exception`): rendering catches only Jinja2's `TemplateError` family + the template's own `ValueError`; parsing catches YAML/schema/shape errors. A bug in a user-passed object (e.g. a broken `__str__`) now propagates with its real type and traceback instead of masquerading as a prompt error.
- `get_prompt_diff` raises `PromptOpsError` (E003, naming the missing version) instead of returning an `{"error": ...}` dict. Callers no longer need to remember to check for the key; both CLI consumers updated.
- Working-tree versions (`None`, `unstaged`, `working-dir`, `staged`) bypass the template cache when the resolver reads mutable state — editing a prompt on disk is now visible on the very next `get_prompt()` call in dev, no `refresh()` needed. Resolvers declare cache-safety via a new `reads_working_tree` attribute (`GitResolver`: True, `SnapshotResolver`: False, `AutoResolver`: delegates), so frozen snapshot-backed production keeps caching everything. **Perf note:** in git mode this makes each no-version `get_prompt('id')` re-read the working tree (~2 ms incl. one `git show`) instead of hitting the cache (~0.3 µs). That's the right trade for dev freshness, but don't run hot loops (e.g. a 100k-iteration eval) against a git-mode checkout — build a snapshot (`reads_working_tree=False` keeps full caching) or pin an immutable version.
- 8 new tests in `tests/test_prompt_manager_v040.py`.

### Changed (Lane F — housekeeping) **[BREAKING]**
- `requires-python` bumped to `>=3.10`; Python 3.8/3.9 classifiers dropped. Both versions are past end-of-life; 3.10 is the new floor.
- `TECHNICAL_PLAN.md` (391 lines, written mid-2025, pre-Phase-1.5) replaced with a short redirect to README/CHANGELOG/WORKFLOWS — a stale plan actively misleads evaluating architects.
- New TTIA budget regression test: `blame --at` over 100 prompt commits + 200 deploy events must answer well inside the documented 30-second budget (asserted at 10s for CI headroom) — catches accidental quadratic blowups in the deploy-log or resolver path.
- All 14 `PytestReturnNotNoneWarning` warnings eliminated. The legacy script-style tests (`test_sdk.py`, `test_versioning.py`, `test_git_hooks.py`, `test_langchain.py`) returned booleans that pytest silently counted as passing — including the `False` ones. They now assert through thin wrappers and **skip honestly** (with a reason) when their precondition is missing: an initialized `.promptops/` workspace, or the not-yet-shipped LangChain adapter. Test counts now tell the truth: 272 passed, 14 skipped, 0 warnings.

### Fixed (pre-release review pass — product bugs)
- **`promptops blame` no longer breaks after `promptops snapshot build`.** blame is incident archaeology — it resolves prompts at *arbitrary historical deploy commits*. A snapshot is frozen at one build commit, so `AutoResolver`'s default snapshot-preference made blame fail with `PROMPTOPS_E004` at every other commit once a snapshot existed in the repo. blame now prefers git whenever `.git/` is present; the snapshot is used only in a snapshot-only runtime.
- **`DeployLog.find_at` no longer returns ghost events after the log is deleted/rotated** in a long-lived process. The absent-file state is now cached under a sentinel that invalidates the prior read and its per-env index. (Reproduced: `all_events()` said empty while `find_at()` still answered from the deleted file.)
- **`promptops render prompt` handles both prompt schemas.** It previously read `prompt_data["prompt"]["template"]` (legacy `prompt:` layout only) and crashed with a raw `KeyError` on the `metadata:` layout the README documents. It now routes through `PromptTemplate`, which parses both and renders in the sandbox.

### Changed (pre-release review pass — CLI ergonomics) **[BREAKING: `create prompt` signature]**
- **`promptops create prompt <id>` now takes the id as a positional argument** and `--description` / `--model` / `--template-file` are all optional. With no `--template-file` it scaffolds a renderable starter template (auto-detecting variables), so the README's `promptops create prompt user-onboarding` works as written. A `--force` flag guards overwrites. *Migration:* replace `create prompt --prompt-id X --description ... --template-file ...` with `create prompt X [--description ...] [--template-file ...]`.
- Removed two dead duplicate command definitions (`status`, `diff`) in `cli/commands/test.py` — the earlier copies were shadowed by later registrations and never ran.

### Security (pre-release review pass)
- Read-side size ceilings added to `snapshot.json` (`MAX_SNAPSHOT_BYTES`, 25 MB) and `deploys.jsonl` (`MAX_DEPLOY_LOG_BYTES`, 50 MB). Both files are committed to the repo and thus appendable by any PR contributor; the caps mirror the existing 1 MB single-prompt cap and prevent an oversized/poisoned file from OOM-ing the production runtime or CI.
- `SnapshotResolver` now catches `RecursionError` (deeply-nested JSON) and re-raises as a clean `PROMPTOPS_E007` instead of escaping as a raw traceback.
- `DeployEvent.commit` is validated as a git SHA (see Lane C) — closes the unvalidated-commit → blame-resolver path.
- `GitPython` floor bumped `>=3.1.0` → `>=3.1.41` (the `>=3.1.0` floor predated the fixes for CVE-2022-24439 / CVE-2023-40267 / CVE-2023-41040; a fresh install could resolve a vulnerable version).
- `git tag -l` existence checks in `hooks/post_commit.py` now pass `--` so a crafted tag name can't inject a git option.

### Fixed (pre-release review pass — docs ↔ code alignment)
- Error hints no longer name nonexistent commands. `promptops list versions <id>` → `promptops test status`; `promptops test prompt <id>` → `promptops test runtest --prompt <id>`. Fixed at every raise site and in `docs/error-codes.md`.
- README: Python floor corrected to **3.10+** (was "3.8+", contradicting `pyproject`); dead `typing_extensions` dependency removed; Quick Start Path B commands corrected (`create prompt <id>`, `blame --at now`, `test runtest --prompt`); Key Features + Automated Versioning sections now state hooks are opt-in; prompt-schema example fixed (`models:` nested under `metadata:`, both schema forms shown).
- `pyproject` description rewritten around the hero positioning ("Git blame for prompts…"); keywords expanded (incident-archaeology, observability, llmops); Python 3.13 classifier added.
- `WORKFLOWS.md` rewritten against the current CLI (adds the entire v0.3.0+ hero surface — deploy/snapshot/blame/backfill/migrate — fixes the broken `create`/`runtest` invocations, documents hooks-opt-in, and replaces the known-broken copy-script deploy instructions).
- Demo README's migration section corrected: tag-history creates named version tags for direct lookup; blame still answers by deploy commit (there is no sha→tag rewrite of blame output).

## [0.3.3] - 2026-06-09

Hotfix release. Two changes that close a contradiction between the v0.3.0 marketing claim ("Production runtime without `.git/`") and what the convenience entry points actually did. No new features; no breaking changes for existing dev workflows.

### Fixed

- **Module-level `get_prompt()` / `get_prompt_manager()` now default to `AutoResolver`.** Before v0.3.3, `from llmhq_promptops import get_prompt` always constructed a `PromptManager` with no `resolver=` argument, which fell back to `GitResolver` and raised `ValueError("GitResolver requires a git repository")` in any production container that shipped only `.promptops/snapshot.json` (no `.git/`). The recommended one-liner from the README — `PromptManager(resolver=AutoResolver())` — worked, but the convenience helpers everyone discovers first did not. The fix wires `AutoResolver(repo_path=...)` into the default manager so the same import works in dev (uses git) and prod (uses snapshot). See [`prompt_manager.py:335-345`](src/llmhq_promptops/prompt_manager.py#L335-L345).

- **`PromptManager._validate_setup` no longer hard-requires `.promptops/prompts/`.** A real production Docker image ships only `snapshot.json`, not the YAML source tree. The previous check raised on init in that exact case. Now the validation accepts either `.promptops/prompts/` (dev) or `.promptops/snapshot.json` (prod) — at least one must be present. The error message lists both initialization paths when neither is found. See [`prompt_manager.py:54-77`](src/llmhq_promptops/prompt_manager.py#L54-L77).

### Tests

- New regression class `TestModuleLevelGetPromptInProduction` in `tests/test_auto_resolver.py` exercising the realistic Docker layout (`snapshot.json` only, no `.git/`, no `prompts/`). Three tests pin: `get_prompt` returns rendered output, `get_prompt_manager` returns an `AutoResolver`-backed manager in `snapshot` mode, and `get_template` works through the same path.

- New file `tests/test_package_metadata.py`. Asserts `llmhq_promptops.__version__ == importlib.metadata.version("llmhq-promptops")` so the v0.1.0→0.2.0 `__version__` desync class of bugs (called out in the v0.3.0 release notes) cannot recur silently. Also asserts the public API surface in `__all__` stays exported and importable.

### Not in this release (intentionally deferred to v0.4.0)

- The full set of P2 cleanup items surfaced alongside this hotfix (narrow render exceptions, deploy-log perf cache, deploy-event size validation, `AutoResolver` startup log line, stale `TECHNICAL_PLAN.md` removal, return-not-None pytest warnings). Batched with the existing v0.4.0 queue (D9 hooks-opt-in flip, M9 Tier 2 error codes, Python 3.8/3.9 deprecation) so the breaking-change envelope is opened exactly once.

## [0.3.2] - 2026-05-27

Pure PyPI-polish patch. No code changes, no behavior changes — just signals downstream tooling reads off PyPI metadata.

### Added
- `src/llmhq_promptops/py.typed` (PEP 561 marker). Downstream type-checkers (mypy, pyright, basedpyright) now trust the type hints we already ship throughout the public API. The marker is included in the wheel via a new `[tool.setuptools.package-data]` block in `pyproject.toml`.
- `Typing :: Typed` classifier. The companion PyPI signal to the marker — surfaced on the project page next to the existing classifiers.

### Changed
- `Development Status` classifier bumped from `4 - Beta` to `5 - Production/Stable`. Two stable releases (v0.3.0, v0.3.1), 210 tests, a documented production runtime path (`AutoResolver` + snapshot), and an incident-archaeology hero flow shipped — the package is past Beta in practice. The PyPI badge now reflects that.
- Classifier set expanded for PyPI discoverability. **Added** `Environment :: Console` (we're primarily a CLI), `Intended Audience :: System Administrators` (the incident-archaeology + deploy-event surface is ops territory), `Topic :: Software Development :: Build Tools` (`promptops snapshot build` literally is a build tool), `Topic :: Software Development :: Quality Assurance` (the test + eval surface), `Topic :: System :: Logging` (`.promptops/deploys.jsonl` is structured audit logging). **Removed** `Topic :: Text Processing :: Linguistic` — we manage prompt files as artifacts, not text-processing.

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