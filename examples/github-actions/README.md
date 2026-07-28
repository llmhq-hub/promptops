# GitHub Actions: prompt impact on every PR

Posts a sticky PR comment showing the semver impact of each changed prompt.

This is the daily-use half of PromptOps. `promptops blame --at` is what you
reach for during an incident; this is what you see on an ordinary Tuesday,
before the incident happens.

## Install

```bash
mkdir -p .github/workflows
cp promptops-diff.yml .github/workflows/
git add .github/workflows/promptops-diff.yml
git commit -m "ci: add PromptOps prompt-impact comments"
```

That is the whole setup. The workflow needs no secrets: it uses the
`GITHUB_TOKEN` that Actions provides, with `pull-requests: write` declared in
the workflow itself.

## What you get

On a PR touching `.promptops/prompts/**`:

| Prompt | Impact | Changes |
| --- | --- | --- |
| `user-onboarding` | **MAJOR** | required variable 'account_tier' added |
| `code-review` | **PATCH** | prose only |

> **MAJOR**: the variable signature changed in a way that breaks existing
> callers. Every caller must be updated.

The comment is edited in place on later pushes rather than appended, so a
long-lived PR does not accumulate stale bot noise.

## How impact is decided

Impact comes from the prompt's **variable signature** and declared models,
never from prose:

| Change | Impact |
| --- | --- |
| Required variable added, removed, renamed, or retyped | MAJOR |
| Optional variable promoted to required | MAJOR |
| Declared model removed | MAJOR |
| Optional variable added or removed | MINOR |
| Required variable relaxed to optional | MINOR |
| Model added, or an optional default changed | MINOR |
| Prose only | PATCH |

Prose is deliberately not graded. The variable interface is the only part of a
prompt with a real caller-facing contract, so it is the only part that can be
graded mechanically without guessing at intent. An annotation that guessed
would not be trusted enough to gate on, and an untrusted gate gets disabled.

One consequence worth knowing: adding `{{ tier }}` to a template body reads as
MAJOR even if you never touch the `variables:` block. PromptOps treats
variables referenced in a body as required, so every caller must now supply it.

## Blocking merges on a break

The workflow comments but does not fail by default, so you can adopt it without
disrupting anyone. To make a MAJOR change block the PR, uncomment the final
step in `promptops-diff.yml`.

For your own scripts, use the exit code directly:

```bash
promptops test diff user-onboarding --exit-code
```

| Code | Meaning |
| --- | --- |
| 0 | NONE or PATCH |
| 1 | the command failed |
| 2 | MINOR |
| 3 | MAJOR |

This borrows git's `--exit-code` flag but not git's numbers: `git diff` uses
`1` for "differences found", while PromptOps reserves `1` for failure because
there are three severities to encode. Do not assume parity.

Without `--exit-code` the command always exits 0 on success and prints a note
telling you the flag exists, so a forgotten flag cannot silently pass a
breaking change.

## Also worth adding

`.pre-commit-hooks.yaml` at the root of this repository makes PromptOps usable
from the [pre-commit](https://pre-commit.com) framework, so contributors catch
problems before pushing:

```yaml
repos:
  - repo: https://github.com/llmhq-hub/promptops
    rev: v0.4.0
    hooks:
      - id: promptops-doctor
      - id: promptops-snapshot-build
```
