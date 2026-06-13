# Migrating from v0.3.x to v0.4.0

v0.4.0 is the breaking-change batch. Most users are unaffected — the
breaks are narrow and each has a one-line fix. This guide lists every
externally visible change that could require action.

## TL;DR

| If you… | …then |
|---|---|
| run only the hero flow (`init`, `create`, `blame`, `snapshot`, SDK `get_prompt`) | nothing to do beyond reading the `create` change below |
| rely on `promptops init repo` installing git hooks | run `promptops hooks install` (now a separate step) |
| script `promptops create prompt --prompt-id X …` | switch to positional `promptops create prompt X …` |
| call `get_prompt_diff()` and check `result["error"]` | catch `PromptOpsError` instead |
| parse error message strings by exact text/offset | match on `e.code` (e.g. `"PROMPTOPS_E011"`) instead |
| run on Python 3.8 / 3.9 | upgrade to Python 3.10+ |
| iterate `DeployLog` events assuming file order | they're now timestamp-ordered |

---

## Breaking changes

### 1. Git hooks are opt-in (`init` no longer installs them)

`promptops init repo` now creates the `.promptops/` tree and a default
`config.yaml` only. It never writes into `.git/hooks/`.

```bash
# Before (v0.3.x): init installed hooks automatically.
promptops init repo

# After (v0.4.0): hooks are a deliberate second step.
promptops init repo
promptops hooks install        # enable auto-versioning on commit
```

`promptops init repo --with-hooks` restores the old one-step behavior
explicitly. `--no-hooks` is still accepted (now the default).

### 2. `create prompt` takes a positional id and scaffolds a template

```bash
# Before (v0.3.x): all-options form, required a pre-existing template file.
promptops create prompt --prompt-id user-onboarding \
  --description "..." --template-file tpl.j2

# After (v0.4.0): positional id; template optional (scaffolds a starter).
promptops create prompt user-onboarding
promptops create prompt user-onboarding --template-file tpl.j2   # still supported
```

With no `--template-file`, a renderable starter template is written and
its variables are auto-detected. `--force` overwrites an existing file.

### 3. `get_prompt_diff()` raises instead of returning an error dict

```python
# Before (v0.3.x):
diff = manager.get_prompt_diff("p", "working", "v9.9.9")
if "error" in diff:
    ...

# After (v0.4.0):
from llmhq_promptops import PromptOpsError
try:
    diff = manager.get_prompt_diff("p", "working", "v9.9.9")
except PromptOpsError as e:
    assert e.code == "PROMPTOPS_E003"
```

A successful diff returns the same dict as before (minus the `"error"` key,
which no longer appears).

### 4. Error messages carry a code prefix

Every upgraded error now renders as:

```
[PROMPTOPS_E0XX] <message>
Hint: <next action>
Docs: https://github.com/llmhq-hub/promptops/blob/main/docs/error-codes.md#promptops_e0xx
```

`PromptOpsError` subclasses `ValueError`, so `except ValueError` and
substring/`match=` checks keep working. Only **exact-string** comparisons
or fixed-offset parsing of error text need updating — switch to `e.code`.

### 5. `DeployLog` iteration is timestamp-ordered; `find_at` tie-break flipped

- `iter_events()` / `all_events()` / `events_for_env()` yield events in
  **timestamp order** (was file order). Normally-appended logs are
  unchanged; backfilled/merged logs are now correctly ordered.
- `find_at` returns the **last** file-order event among equal timestamps
  (was the first), matching "latest deploy wins" semantics.

Most callers are order-independent and need no change.

### 6. `DeployEvent.commit` must be a git SHA

Constructing a `DeployEvent` with a non-hex or <7-char `commit` now raises
`PROMPTOPS_E016`. Real git SHAs always pass; this only affects code that
passed placeholder strings.

### 7. Python 3.10+ required

`requires-python` is now `>=3.10`. Python 3.8 / 3.9 (both end-of-life) are
no longer supported. The unused `typing_extensions` dependency was dropped.

---

## Non-breaking improvements worth knowing

- **`blame` works after `snapshot build`.** It now prefers git history when
  `.git/` is present, so building a snapshot no longer breaks historical
  blame queries.
- **Error codes everywhere.** See [`error-codes.md`](error-codes.md) for the
  full `PROMPTOPS_E001`–`E017` registry. Catch programmatically via `e.code`.
- **Dev-mode freshness.** Editing a prompt on disk is visible on the next
  `get_prompt('id')` call without `manager.refresh()`. Trade-off: in git
  mode each no-version call re-reads the working tree (~2 ms). For hot
  loops, build a snapshot or pin an immutable version.
- **Read-side safety caps** on `snapshot.json` and `deploys.jsonl` guard
  against oversized/poisoned files; a deleted log no longer returns ghost
  answers.
