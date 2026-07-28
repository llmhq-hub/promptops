# Production Deployment

How to run PromptOps in production: the snapshot pipeline, a Docker recipe,
the CI gate, and how environment detection actually works.

The core idea in one sentence: **your production image ships a
`snapshot.json`, not a git repository.**

## Why a snapshot

In development, PromptOps resolves prompts from git history: that is what
makes `blame --at` and version tags work. Production containers usually have
no `.git/` at all, and shipping one would mean shipping your entire history
into a runtime image.

`promptops snapshot build` freezes every prompt at a commit into a single JSON
file. `AutoResolver` then picks the snapshot when it exists and git when it
does not, so **the same application code runs unchanged in both**.

```python
from llmhq_promptops import AutoResolver, PromptManager

manager = PromptManager(repo_path, resolver=AutoResolver(repo_path=repo_path))
```

Since v0.3.3 the module-level `get_prompt()` defaults to `AutoResolver` too,
so simple scripts need no wiring. In a long-lived service, construct one
manager at startup and reuse it: see
[`examples/fastapi-service/`](../examples/fastapi-service/).

## The pipeline

Four stages. Only stage 2 is PromptOps-specific.

```text
1. commit prompts        .promptops/prompts/*.yaml, versioned by git
2. build snapshot        promptops snapshot build      -> snapshot.json
3. ship the artifact     COPY snapshot.json into the image
4. record the deploy     promptops deploy event --env prod
```

Stage 4 is the one teams skip, and it is the one that makes incident
archaeology possible later. Skipping it means `blame` has nothing to answer
from. See the [Day 0 playbook](day-0-playbook.md).

## Building the snapshot

```bash
promptops snapshot build              # at HEAD
promptops snapshot build --commit v1.2.3   # pin to a tag
promptops snapshot build --pretty     # readable, larger; good for review diffs
promptops snapshot inspect            # what is actually in it
```

The build **fails** if any template uses a Jinja tag that needs a template
loader:

```text
Error: [PROMPTOPS_E012] Prompt 'greeting' uses a Jinja tag that requires a
template loader: line 7 ({% include %}). PromptOps renders in a sandboxed
environment with no loader, so this cannot render at runtime.
```

This is deliberate. Those tags could never work at runtime, so a snapshot
containing one is guaranteed-broken output. Failing your build is much cheaper
than failing a user's request. `--allow-includes` exists as an escape hatch but
produces a snapshot that still fails at render time.

Nothing is written when the check fails, so a rejected build leaves no stale
snapshot behind for a later stage to pick up.

## Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir llmhq-promptops

# The only PromptOps artifact. No .git/, no .promptops/prompts/.
COPY snapshot.json /app/.promptops/snapshot.json
COPY app.py /app/app.py

# Fail the build if a git directory ever leaks in.
RUN test ! -d /app/.git || (echo "FAIL: .git leaked into the image" && exit 1)

CMD ["python", "/app/app.py"]
```

A complete, runnable version including the build script is at
[`examples/docker-snapshot/`](../examples/docker-snapshot/). It asserts both
that `.git/` is absent and that `ResolvedPrompt.source == "snapshot"`, so it
proves the claim rather than asserting it.

**Build the snapshot outside the image.** Stage 2 needs git; the image must
not have it. Run `promptops snapshot build` in CI, then `COPY` the result.

## CI

### Gate on prompt changes

Copy [`examples/github-actions/promptops-diff.yml`](../examples/github-actions/promptops-diff.yml)
into `.github/workflows/`. It comments the semver impact of every changed
prompt on the PR.

To fail the build on a breaking change:

```bash
promptops test diff "$PROMPT_ID" --exit-code
```

| Code | Meaning |
| --- | --- |
| 0 | NONE or PATCH |
| 1 | the command failed |
| 2 | MINOR |
| 3 | MAJOR |

This borrows git's `--exit-code` flag but not git's numbers: `git diff` uses
`1` for "differences found", while PromptOps reserves `1` for failure because
there are three severities to encode.

Forgetting the flag cannot silently pass a breaking change: without it the
command exits 0 but prints `note: exiting 0, pass --exit-code to make this
major fail CI`.

### Check health

```bash
promptops doctor
```

Exits 0 when every check is OK or WARN, 1 on any FAIL. Warnings are for states
you may have chosen deliberately (hooks are opt-in; a repo can legitimately
have no snapshot yet), so this is safe to run in CI without false alarms.

### A complete deploy job

```yaml
- name: Build snapshot
  run: promptops snapshot build

- name: Verify health
  run: promptops doctor

- name: Build and push image
  run: docker build -t myapp:${{ github.sha }} . && docker push myapp:${{ github.sha }}

- name: Record the deploy
  run: |
    promptops deploy event --env prod --commit "${{ github.sha }}" \
      --by "${{ github.actor }}" -m "run=${{ github.run_id }}"
    git add .promptops/deploys.jsonl
    git commit -m "[deploy] prod ${{ github.sha }}"
    git push
```

The `[deploy]` commit prefix matters: the pre-commit hook detects
deploys-only commits and skips version bumping, so recording a deploy never
corrupts prompt versions.

## Environment detection

`AutoResolver` chooses like this:

| Condition | Backend |
| --- | --- |
| `snapshot.json` exists | `SnapshotResolver` |
| Otherwise, `.git/` exists | `GitResolver` |
| Neither | Raises `PROMPTOPS_E009` |

Snapshot wins whenever present. That is the right default for production and
occasionally surprising in development: build a snapshot in your working tree
and prompt resolution freezes at that snapshot until you delete it.

Two things make this visible rather than mysterious:

```bash
promptops doctor        # names the chosen backend and why
```

and `AutoResolver` logs one INFO line at construction naming the backend it
picked. When resolution looks wrong, that line is the first thing to check.

`promptops blame` deliberately prefers git when `.git/` is present, because
archaeology inherently wants history rather than a frozen point.

## Operational checklist

Before your first production deploy:

- [ ] `promptops snapshot build` runs in CI, before the image build
- [ ] The image contains `snapshot.json` and no `.git/`
- [ ] `promptops deploy event` runs on every deploy, to the right `--env`
- [ ] `deploys.jsonl` is committed and pushed, so it survives
- [ ] `promptops doctor` passes in CI
- [ ] Someone has run through the [Day 0 playbook](day-0-playbook.md) once, on
      the demo repo, before there is a real incident

## Related

- [Day 0 Incident Playbook](day-0-playbook.md)
- [Migrating from hardcoded prompts](migration-from-hardcoded-prompts.md)
- [Error codes](error-codes.md)
