# Docker: production runtime with no `.git/`

Proves the claim PromptOps makes about production: your image ships a single
`snapshot.json` and resolves prompts from it, with no git working tree, no git
binary, and no prompt YAML files present.

## Requires >= 0.5.0

Resolving prompts with **no git binary** present needs 0.5.0 or later. On
0.4.0 and earlier, `import llmhq_promptops` fails in an image like this one:
GitPython was imported at module scope and raises when there is no git
executable, so the snapshot path never got a chance to run. The Dockerfile
pins accordingly, so you get a clear pip error rather than a confusing
runtime crash.

## Run it

```bash
./build.sh            # local, no Docker needed
./build.sh --docker   # also builds and runs the container
```

## What it shows

Three phases, matching how this works in CI:

1. **Build.** In a git checkout, `promptops snapshot build` freezes every
   prompt at HEAD into `.promptops/snapshot.json`.
2. **Strip.** A runtime directory is assembled with *only* `snapshot.json`.
   No `.git/`, no `.promptops/prompts/`.
3. **Resolve.** `app.py` resolves and renders, then asserts both that `.git/`
   is absent and that `ResolvedPrompt.source == "snapshot"`.

Expected output:

```
source:  snapshot
version: v1.0.0
commit:  68da0046...

OK: resolved from snapshot.json with no .git/ present.
```

## The one line that matters

```python
manager = PromptManager(str(repo), resolver=AutoResolver(repo_path=str(repo)))
```

`AutoResolver` picks `SnapshotResolver` when `snapshot.json` exists and
`GitResolver` otherwise, so this file is byte-identical in a dev checkout and
a production image. The `Dockerfile` also asserts both negatives, failing the build if a `.git`
directory or a git binary ever ends up in the image.
