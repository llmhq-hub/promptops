# Migrating from v0.4.0 to v0.5.0

v0.5.0 is mostly additive: `promptops history`, `promptops doctor`, a real
unified `test diff` with semver impact, CI templates, and five new examples.

There are four breaking changes. Three fail loudly, so you will know
immediately. **One fails silently**, and it is the reason to read this page
even if the rest looks irrelevant to you.

## TL;DR

| If you… | …then |
|---|---|
| run only the hero flow (`init`, `create`, `blame`, `snapshot`, SDK `get_prompt`) | nothing to do |
| use `{% include %}`, `{% import %}`, `{% from %}` or `{% extends %}` in a template | `snapshot build` now fails; inline the content, or pass `--allow-includes` |
| parse `promptops test diff` stdout in a script | switch to `--json` |
| call `GitVersioning.is_git_repo()` | it can now raise `PromptOpsError` (E018) |
| read `ResolvedPrompt.version` after resolving at a specific SHA | **it now returns a version label, not the SHA you passed** |
| pin the pre-commit hooks | bump `rev:` to `v0.5.0` |
| install from `requirements.txt` | it is gone; use `pip install -e '.[dev]'` |

---

## Breaking changes

### 1. `ResolvedPrompt.version` returns a version label (the silent one)

This is the only change here that does not announce itself. Nothing raises,
the call keeps working, and the field simply contains different data.

```python
resolved = GitResolver(".").resolve("refund-policy", "47d71643d7fe...")

# Before (v0.4.0): echoed the ref you passed in.
resolved.version    # "47d71643d7fe9b4ef6e9391f8bb6d8c8b65150e2"

# After (v0.5.0): the version that was in effect at that commit.
resolved.version    # "v1.2.0"   (or "commit-47d71643" if untagged)
```

**Why:** `promptops blame` printed a 40-character SHA under a field labelled
"version" while `promptops history` reported `v1.2.0` for the same prompt in
the same repository. Two commands disagreed, and the hero command gave the
worse answer.

**What to check.** Anywhere you feed `.version` into something that expects a
commit-ish value:

- a cache key or lookup table keyed by SHA
- an equality check against a SHA you have elsewhere
- a subsequent `resolve(prompt_id, resolved.version)` round-trip
- logging or telemetry a dashboard parses as a commit

**The fix** is `.commit`, which still carries the full SHA and always did:

```python
resolved.commit     # "47d71643d7fe9b4ef6e9391f8bb6d8c8b65150e2"
```

If you want a label for humans, use `.version`. If you want something to feed
back into git, use `.commit`. That split is the whole point of the change.

### 2. `snapshot build` rejects Jinja tags that need a template loader

A build that previously succeeded now fails with `PROMPTOPS_E012` if any
template uses `{% include %}`, `{% import %}`, `{% from %}` or `{% extends %}`.

```text
Error: [PROMPTOPS_E012] Prompt 'bypass' uses a Jinja tag that requires a
template loader: line 6 ({% include %}). PromptOps renders in a sandboxed
environment with no loader, so this cannot render at runtime.
```

**Why:** PromptOps renders inside a `SandboxedEnvironment` constructed without
a loader, so these tags could never resolve. Such a template used to snapshot
silently and fail later, at render time, in production. This converts a
production failure into a build failure.

**The fix** is to inline the included content into the template. If you need
to unblock an unrelated investigation:

```bash
promptops snapshot build --allow-includes
```

The resulting snapshot still fails at render time. The CLI prints an on-screen
warning naming each affected prompt, so the tradeoff is never silent.

Not affected: the words "include" or "import" in ordinary prose, tags inside a
Jinja comment (`{# ... #}`), tags inside a `{% raw %}` block, and supported
control tags like `{% if %}` and `{% for %}`.

### 3. `test diff` output format is replaced

The human-readable output changed wholesale: it previously printed two
500-character truncated blobs, and now prints a real unified diff with an
impact banner.

```bash
# Before: scraping stdout.
promptops test diff my-prompt | grep ...

# After: a stable, parseable contract.
promptops test diff my-prompt --json
```

`--json` emits `{prompt, version1, version2, identical, diff, impact,
changes[]}`. It exists precisely so that output-format changes stop being
breaking changes. Move any script to it.

Exit codes are unchanged by default (`0` success, `1` failure). The new
`--exit-code` flag opts into CI semantics: `0` none/patch, `2` minor, `3`
major. Note this borrows git's *flag* but not git's *numbers*: `git diff`
uses `1` for "differences found", while PromptOps reserves `1` for "the
command failed" because there are three severities to encode.

### 4. `GitVersioning.is_git_repo()` can raise

```python
# Before (v0.4.0): always returned a bool.
if git.is_git_repo():
    ...

# After (v0.5.0): raises PromptOpsError (E018) when git is not installed.
from llmhq_promptops import PromptOpsError
try:
    if git.is_git_repo():
        ...
except PromptOpsError as e:
    assert e.code == "PROMPTOPS_E018"
```

**Why:** it was reporting a missing git *binary* as "not a repository", so
callers went looking for a `.git/` directory that was present all along. The
two conditions need different fixes and now have different answers.

This is worth knowing as a general hazard: `PromptOpsError` subclasses
`ValueError` for v0.4.0 back-compat, so any `except ValueError` that converts
to a boolean rather than re-raising can silently absorb a structured error.
That is exactly the bug this fixed.

---

## Not breaking, but worth knowing

### PromptOps now works without the git binary

Before 0.5.0, `core/git_versioning.py` imported GitPython at module scope, and
GitPython raises during its own `refresh()` when there is no git executable on
`PATH`. So `import llmhq_promptops` failed outright in any image lacking git,
taking the snapshot-only production runtime with it.

The docs conflated two different things. Running without the `.git/`
*directory* worked; running without the git *binary* did not, and nobody
reading "no git needed in production" would draw that distinction. Both now
work.

**If you build production images, this is the upgrade that matters.** A
`python:3.11-slim` base has no git binary, so pin `>=0.5.0`:

```dockerfile
RUN pip install --no-cache-dir 'llmhq-promptops>=0.5.0'
```

GitPython remains a hard dependency, deliberately: making it an extra would
mean `pip install llmhq-promptops` yields a CLI where most commands fail. It
is simply never *executed* on the snapshot path now.

### `init` anchors to the repository root

`promptops init repo` run from a subdirectory previously created
`.promptops/` in the current directory while hooks went to the git root. The
root pre-commit hook then looked for `.promptops/prompts/` relative to itself,
found nothing, and silently versioned nothing. Both now use the repository
root, and `init` announces when it wrote somewhere other than where you ran it.

Nothing moves for existing layouts. If you hit this bug, your prompts are in
the subdirectory where you first ran `init`; move that `.promptops/` tree to
the repository root.

### pre-commit users must bump `rev:`

```yaml
repos:
  - repo: https://github.com/llmhq-hub/promptops
    rev: v0.5.0        # v0.4.0 has no .pre-commit-hooks.yaml and no `doctor`
    hooks:
      - id: promptops-doctor
      - id: promptops-snapshot-build
```

### `requirements.txt` is gone

It had drifted: it omitted GitPython entirely and still pinned a dependency
dropped in v0.4.0, so following it produced an environment where
`import llmhq_promptops` failed. Use `pip install -e '.[dev]'`;
`pyproject.toml` is the single source of truth.

---

## New in v0.5.0

Nothing here requires action, but these are the reasons to upgrade.

| Command | What it answers |
|---|---|
| `promptops history <id>` | every version this prompt has been, and which deploys shipped each one |
| `promptops doctor` | is this setup sane, in one command instead of six manual checks |
| `promptops test diff --json` | what changed, and does it break callers |
| `promptops test diff --exit-code` | gate CI on the semver verdict |

Plus `.pre-commit-hooks.yaml`, a copy-in GitHub Actions workflow that posts
prompt impact on every PR, and five new examples covering Docker, CI, the
hooks lifecycle, error handling, and a FastAPI service.

## Related

- [Error codes](error-codes.md): every `PROMPTOPS_E0XX` with a fix
- [Day 0 playbook](day-0-playbook.md): the incident sequence
- [Production deployment](production-deployment.md): snapshot pipeline and CI
- [Migrating v0.3.x to v0.4.0](migration-v0.3-to-v0.4.md): the previous batch
