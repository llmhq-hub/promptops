# PromptOps Error Codes

Every user-facing PromptOps error carries a stable `PROMPTOPS_E0XX` code, a
message with concrete values, a hint naming the next action, and a link back
to this page. Codes never change meaning and are never renumbered; new codes
append.

Catching errors in code:

```python
from llmhq_promptops import PromptOpsError, get_prompt

try:
    prompt = get_prompt("user-onboarding:v1.2.0")
except PromptOpsError as e:
    print(e.code)      # "PROMPTOPS_E003"
    print(e.message)   # what went wrong
    print(e.hint)      # what to do next
    print(e.to_dict()) # JSON-friendly shape for structured logging
```

`PromptOpsError` subclasses `ValueError`, so existing `except ValueError`
handlers keep working unchanged.

---

## PROMPTOPS_E001

**Not initialized.** The `.promptops/` directory does not exist at the
target path.

- **When you'll see it:** constructing `PromptManager` (or calling
  `get_prompt`) in a directory that was never set up for PromptOps.
- **Fix:** run `promptops init repo` in the repository root.

## PROMPTOPS_E002

**No prompt source.** `.promptops/` exists but contains neither a
`prompts/` directory (dev source) nor a `snapshot.json` (production
artifact).

- **When you'll see it:** a partially-copied `.promptops/` directory, or a
  production image that stripped `prompts/` without baking a snapshot.
- **Fix:** in dev, run `promptops init repo`. In prod, run
  `promptops snapshot build` at CI time and ship the resulting
  `snapshot.json` inside the image.

## PROMPTOPS_E003

**Prompt not found.** The prompt id is unknown to the active resolver
(git history or snapshot). The message lists the prompts that *are*
available.

- **When you'll see it:** misspelled prompt id; a prompt that exists in the
  working tree but was never committed (git resolver, version omitted); a
  snapshot built before the prompt existed.
- **Fix:** check the spelling against the listed available prompts. For
  uncommitted prompts use version `:unstaged`. For snapshots, rebuild with
  `promptops snapshot build`.

## PROMPTOPS_E004

**Version not found.** The prompt exists, but not at the requested version
in this source. Snapshots are frozen at one version per prompt; git-only
version keywords (`unstaged`, `working-dir`, `staged`) can never resolve
from a snapshot.

- **When you'll see it:** asking a snapshot for a version other than the one
  pinned at build time, or for a working-tree keyword.
- **Fix:** rebuild the snapshot at the desired commit
  (`promptops snapshot build --commit <ref>`), or resolve through git where
  any committed version is reachable.

## PROMPTOPS_E005

**Git required.** The operation needs a `.git/` directory and the target
path doesn't have one.

- **When you'll see it:** `GitResolver` (or `AutoResolver(prefer='git')`)
  pointed at a non-repo; `promptops snapshot build` outside a repo
  (snapshots are built FROM git).
- **Fix:** run inside a git repository, or use snapshot-based resolution in
  environments without `.git/`.

## PROMPTOPS_E006

**Snapshot missing.** Snapshot-based resolution was requested but
`.promptops/snapshot.json` does not exist.

- **When you'll see it:** `SnapshotResolver` or
  `AutoResolver(prefer='snapshot')` in an image that never baked a snapshot.
- **Fix:** run `promptops snapshot build` at CI/build time and ship the
  file in the image.

## PROMPTOPS_E007

**Snapshot invalid.** `snapshot.json` exists but is not readable as a
snapshot: broken JSON, not a JSON object, or missing the `prompts` key.

- **When you'll see it:** hand-edited or truncated snapshot files,
  interrupted writes by external tools (PromptOps itself writes atomically).
- **Fix:** rebuild with `promptops snapshot build`. Don't hand-edit
  snapshots; they are generated artifacts.

## PROMPTOPS_E008

**Snapshot schema mismatch.** The snapshot's `schema_version` doesn't match
what this version of PromptOps expects.

- **When you'll see it:** a snapshot built by a newer/older promptops than
  the one resolving it.
- **Fix:** rebuild the snapshot with the same promptops version that runs in
  production, or upgrade the runtime package.

## PROMPTOPS_E009

**Resolver unavailable.** `AutoResolver` found neither a snapshot nor a git
repository at the target path.

- **When you'll see it:** running in a bare directory: no `.git/`, no
  `.promptops/snapshot.json`.
- **Fix:** in dev, run inside the git repo. In prod, ship
  `.promptops/snapshot.json` in the image (`promptops snapshot build` at CI
  time).

## PROMPTOPS_E010

**Invalid prompt id.** The prompt id fails validation: it must match
`[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}` (alphanumeric, hyphens, underscores;
starts with an alphanumeric; max 128 chars).

- **When you'll see it:** ids containing slashes, dots, spaces, or path
  traversal attempts. This validation is part of the v0.2.0 security
  hardening.
- **Fix:** rename the prompt id to use only the allowed characters.

## PROMPTOPS_E011

**No deploy events.** `promptops blame` (and other deploy-log consumers)
need at least one recorded deploy event, and either the log doesn't exist
or nothing matches the query.

- **When you'll see it:** running `blame --at <ts>` before any deploy was
  recorded; a timestamp predating the first deploy; a wrong `--env` name.
- **Fix:** record deploys in CI with `promptops deploy event`; seed history
  retroactively with `promptops backfill-deploys --from-git-log`; check
  what's recorded with `promptops deploy list`.

## PROMPTOPS_E012

**Template include unsupported.** PromptOps renders templates in a Jinja2
`SandboxedEnvironment` constructed without a file loader, so the four tags
that need one can never resolve at runtime: `{% include %}`, `{% import %}`,
`{% from %}`, and `{% extends %}`.

`promptops snapshot build` scans every prompt for these tags and refuses to
write a snapshot that contains one. Catching it at build time is the whole
point: a snapshot with an include is guaranteed-broken output, and failing in
CI is far cheaper than failing at render time in production.

- **When you'll see it:** running `promptops snapshot build` against a prompt
  whose template pulls in another file. The message names the prompt id and
  every offending line number.
- **Fix:** inline the included content directly into the template. PromptOps
  prompts are self-contained by design; composition happens in your
  application code, not in the template.
- **Escape hatch:** `promptops snapshot build --allow-includes` downgrades the
  error to a warning and builds anyway. The resulting snapshot will still fail
  at render time, so use this only to unblock an unrelated investigation.

Tags in ordinary prose ("please include the account tier") and tags inside a
Jinja comment (`{# {% include "x" %} #}`) are not flagged. Supported control
tags like `{% if %}` and `{% for %}` are unaffected.

## PROMPTOPS_E013

**Invalid version spec.** The version string fails validation: it must be a
semantic version (`v1.2.3`, optionally with a pre-release suffix) or one of
the keywords `unstaged`, `working-dir`, `staged`, `working`, `latest`,
`head`.

- **When you'll see it:** typos like `1.2` or `version-3`, or git SHAs
  passed where a validated version is required.
- **Fix:** see each prompt's latest version with `promptops test status`,
  or use a working-tree ref like `:unstaged` / `:working`.

## PROMPTOPS_E014

**Render failed.** The prompt resolved and parsed, but Jinja2 rendering
raised: missing required variables, template syntax errors, or sandbox
violations.

- **When you'll see it:** calling `get_prompt(...)` without a variable the
  template requires, or after editing a template into invalid Jinja2.
- **Fix:** pass all required variables (see
  `PromptManager.validate_prompt`), and validate templates locally with
  `promptops test runtest --prompt <id>`.

## PROMPTOPS_E015

**Parse failed.** The prompt content was retrieved but isn't valid prompt
YAML: malformed YAML syntax or missing required keys (`prompt.id`,
`prompt.template`).

- **When you'll see it:** hand-edited YAML with indentation errors, or files
  under `.promptops/prompts/` that aren't prompt definitions.
- **Fix:** validate the YAML structure against the schema in the README.

## PROMPTOPS_E016

**Invalid deploy event.** A `DeployEvent` failed field validation:
timezone-naive timestamp, empty `env`, or empty `commit`.

- **When you'll see it:** constructing events programmatically with
  `datetime.utcnow()` (naive) instead of `datetime.now(timezone.utc)`, or
  CI steps passing empty strings.
- **Fix:** the hint on each variant names the exact field and fix.

## PROMPTOPS_E017

**Naive timestamp.** A query API (`DeployLog.find_at`) was given a
timezone-naive datetime. Deploy timestamps are timezone-aware UTC;
comparing them against naive datetimes would silently produce wrong
answers, so the API refuses.

- **When you'll see it:** SDK calls passing `datetime(2026, 5, 20, 14, 0)`
  without a tzinfo.
- **Fix:** attach a timezone: `datetime(2026, 5, 20, 14, 0,
  tzinfo=timezone.utc)`. The CLI parses bare dates as UTC midnight
  automatically.

## PROMPTOPS_E018

**Git binary missing.** The operation needs the `git` executable and none was
found on `PATH`. This is distinct from `E005`, which means the `.git/`
directory is absent: here the repository may be perfectly fine and it is the
tool that is missing.

- **When you'll see it:** running a git-backed command in a container or CI
  image that never installed git; a stripped `PATH`.
- **Fix, on a development machine:** install git (`apt-get install git`,
  `brew install git`).
- **Fix, in production:** you do not need git at all. Build a snapshot in CI
  with `promptops snapshot build` and ship `.promptops/snapshot.json` in the
  image. `AutoResolver` reads it with no git binary and no `.git/` directory
  present, which is the whole point of the snapshot. See
  [production deployment](production-deployment.md).

Note that importing `llmhq_promptops` and resolving from a snapshot never
require git. GitPython is imported lazily, at the single point that actually
needs a repository, so a snapshot-only runtime never touches it.
