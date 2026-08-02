# Migrating from v0.5.0 to v0.6.0

v0.6.0 is a repair release. The git hooks, the feature the README leads with,
have not worked since **v0.2.0**. Installing them and editing a prompt blocked
the commit outright, and every release from 0.2.0 through 0.5.0 shipped that
way.

If you never ran `promptops hooks install`, almost none of this affects you:
read [Breaking change 4](#4-promptops-init-repo-no-longer-turns-on-commit-reports)
and move on.

If you did run it, and versioning has silently never fired for you, that is why.

## The short version

| If you | Do |
|---|---|
| use the git hooks | Nothing. They work now. Read [1](#1-version-numbers-from-the-hook-have-changed) so the new numbers are not a surprise |
| have `<prompt-id>-v1.2.3` tags | Nothing breaks, but nothing reads them either. See [2](#2-tags-use-the-format-the-rest-of-the-tool-reads) |
| import `SemanticVersionDetector` | Move to `core.impact`. See [3](#3-semanticversiondetector-is-deprecated) |
| rely on commit reports | Set `generate_reports: true`. See [4](#4-promptops-init-repo-no-longer-turns-on-commit-reports) |
| pin the pre-commit hooks | Bump `rev:` to `v0.6.0` |

Nothing here requires a change to your prompts.

---

## 1. Version numbers from the hook have changed

The pre-commit hook now grades a change with `core/impact.py`, the same engine
behind `promptops test diff`. Three cases move:

| Change to a prompt | v0.5.0 | v0.6.0 |
|---|---|---|
| Add a **required** variable | MINOR (1.2.0 to 1.3.0) | **MAJOR** (1.2.0 to 2.0.0) |
| Change a variable's `type` | PATCH (1.2.0 to 1.2.1) | **MAJOR** (1.2.0 to 2.0.0) |
| Edit only `metadata` (description, tags) | PATCH (1.2.0 to 1.2.1) | **no bump** |

**Why.** Adding a required variable makes every existing call fail validation.
Changing a variable's type silently changes what a passing call means. Both
break callers, and grading them below MAJOR tells a reviewer a breaking change
is safe, which is worse than not grading at all.

The deeper reason is consistency. `promptops test diff` has graded both as
MAJOR since v0.5.0, so a repository running the hooks alongside the
`test diff --exit-code` CI gate got its pull request blocked as breaking while
the hook stamped a non-breaking version onto the same commit. Version numbers
are only useful if they mean one thing.

The metadata case is the opposite problem. A typo fix in a description is not a
contract change, and minting a version for it produces churn that teaches people
to ignore version numbers.

**What to do.** Nothing. Existing tags are untouched. The next bump on an
affected change will jump further than it used to. Since the hooks have been
broken since v0.2.0, very few repositories hold numbers this grader produced.

### A new prompt now keeps its declared version

Writing `version: v1.0.0` and committing gives you `v1.0.0`. It previously gave
you `v1.1.0`, because the old grader compared the new prompt against an empty
document, read every variable as an addition, and graded MINOR. There is nothing
for a first commit to be backward incompatible with.

## 2. Tags use the format the rest of the tool reads

The post-commit hook tagged commits `<prompt-id>-v1.2.3`. The SDK reads two
formats, `prompt-<id>-v1.2.3` (what `promptops migrate tag-history` writes) and
legacy global `v1.2.3`. The hook's matched neither, so `history`, `blame` and
version resolution ignored every tag it ever created:

```bash
$ git tag -l
refund-v1.1.0
$ promptops history refund
  commit-fc061b8f          # the tag is right there and nothing can see it
```

It now writes `prompt-<id>-v<version>`.

**What to do.** Old `<id>-v1.2.3` tags are harmless; they were already invisible.
To make historical versions visible, run:

```bash
promptops migrate tag-history --dry-run   # inspect first
promptops migrate tag-history
```

That writes the readable format across your existing history. To list the
unreadable ones:

```bash
git tag -l | grep -E -- '-v[0-9]+\.[0-9]+\.[0-9]+$' | grep -v '^prompt-'
```

The second `grep -v` is not optional. `prompt-greeting-v1.0.0` matches the first
pattern too, so without it you would delete the new tags this release just
started writing.

**Read that list.** When it contains only tags you want gone, and not a moment
before:

```bash
git tag -l | grep -E -- '-v[0-9]+\.[0-9]+\.[0-9]+$' | grep -v '^prompt-' \
  | xargs -r git tag -d
```

## 3. `SemanticVersionDetector` is deprecated

`llmhq_promptops.core.version_detector.SemanticVersionDetector` emits a
`DeprecationWarning` and will be removed in 0.7.0. Its grading now delegates to
`core.impact`, so it cannot disagree with the rest of the tool while it lives.

```python
# Before
from llmhq_promptops.core.version_detector import SemanticVersionDetector
change = SemanticVersionDetector().analyze_prompt_changes(old, new, "v1.2.0")

# After
from llmhq_promptops.core.impact import next_version
version, report = next_version("v1.2.0", old, new)
print(report.impact.value)          # none | patch | minor | major
for c in report.changes:
    print(c.detail)
```

`VersionChange.file_changes` now carries `ImpactReport.to_dict()` rather than
the old `metadata_changes` / `template_changes` / `variable_changes` /
`model_changes` / `breaking_changes` / `new_features` keys. Those described the
old grader's internals, which no longer exist. `ChangeType` gains a `NONE`
member.

## 4. `promptops init repo` no longer turns on commit reports

`generate_reports` now defaults to False, in the hook and in the config that
`init` writes.

**Why.** The post-commit hook wrote markdown files into `.promptops/reports/`
after every commit **and ran `git add` on them**, so your next commit silently
carried files you never staged:

```
$ git commit -m "feat: add prompt"     # succeeds
$ git status --short
A  .promptops/reports/2026-08/commit-fc061b8-version-changes.md
A  .promptops/reports/index.md
```

The `git add` is gone in every configuration. Writing files into someone's
repository after every commit is opt-in.

**What to do.** If you want reports, put this in `.promptops/config.yaml`:

```yaml
generate_reports: true
```

They will be written and left untracked. Committing them is your decision. An
existing config with `generate_reports: true` keeps working.

## 5. A prompt with broken Jinja is blocked at commit time

`pre_commit._validate_prompt_syntax` claimed to validate syntax but only
constructed a `PromptTemplate`, and `PromptTemplate.template` is a lazy
property, so the Jinja source was never compiled. An unclosed `{% if %}` reached
production and failed at render time.

It now compiles the template, so commits that previously succeeded can fail.
This follows the precedent E012 set in v0.5.0: a build failure beats a
production failure.

**What to do.** Fix the template. `promptops test runtest --prompt <id>` tells
you what is wrong.

---

## Things that stopped being wrong

No action needed for any of these; listed so you can recognise behaviour you may
have worked around.

- **Committing a prompt works at all.** `git show --` treats everything after
  the separator as a pathspec, so `git show -- HEAD:path` stopped naming a
  revision and git exited 0 with empty output. That empty string reached
  `yaml.safe_load`, which returned `None`, and `"metadata" in None` raised
  `TypeError`, which the hook caught and turned into a blocked commit.
- **Deleting a prompt works.** A staged deletion has no staged content, so the
  hook reported "Could not read staged content" and blocked.
- **The first commit in a repository is versioned.** `git diff-tree HEAD` has no
  parent on a root commit, so it printed nothing and exited 0, and that silence
  read as "no prompts changed".
- **Your comments survive.** The version bump round-tripped the whole document
  through `yaml.safe_load` and `yaml.dump`, which deleted every comment and
  reserialized `template: |` blocks into quoted strings. The rewrite is now a
  targeted line edit: exactly one line changes.
- **The post-commit check can pass.** It rendered with `{}`, so any prompt with
  a required variable failed by construction with `PROMPTOPS_E014`, on every
  commit.
- **`promptops doctor` can tell.** It reported "hooks installed" while they were
  dead, because it checked the files existed and never that they could run. It
  now runs the hook's shebang interpreter against `import llmhq_promptops` and
  fails when that cannot work, which catches the common case of hooks installed
  inside a venv and commits made outside it.

## Verifying the upgrade

```bash
pip install --no-cache-dir --upgrade llmhq-promptops
promptops --version        # promptops 0.6.0  (new in 0.6.0)
promptops doctor           # the hooks check now proves they can run
```

Then, in a scratch repository:

```bash
git init demo && cd demo
promptops init repo
promptops hooks install
mkdir -p .promptops/prompts
cat > .promptops/prompts/greeting.yaml <<'YAML'
# this comment should still be here afterwards
metadata:
  id: greeting
  version: v1.0.0
template: |
  Hello {{ name }}.
variables:
  name:
    type: string
    required: true
YAML
git add . && git commit -m "feat: greeting"
git tag -l                 # prompt-greeting-v1.0.0
promptops history greeting # v1.0.0, not commit-<sha>
git show HEAD:.promptops/prompts/greeting.yaml   # comment intact
```

`examples/hooks-lifecycle/run.sh` runs this end to end, including a MAJOR bump
and `promptops hooks uninstall`.
