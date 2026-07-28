# Git hooks: install, use, uninstall

Hooks became opt-in in v0.4.0: `promptops init repo` no longer writes to
`.git/hooks/`. That made two questions worth answering concretely: what do the
hooks actually do for you, and how do you turn them off again.

## Run it

```bash
./run.sh    # throwaway repo under $TMPDIR, touches nothing else
```

## What it shows

| Step | Point |
| --- | --- |
| `init repo` | Creates `.promptops/`, leaves `.git/hooks/` untouched |
| `hooks status` | Reports the un-installed state honestly |
| `hooks install` | The deliberate opt-in |
| commit a prompt | Versioning runs |
| `history` | The new version is visible |
| `doctor` | Confirms hooks are live, so you never have to guess |
| `hooks uninstall` | Fully reverses it |

## Why opt-in

Silently writing into someone's `.git/hooks/` on the first command they ever
run is a trust violation, particularly for the architect persona PromptOps
targets. Making it a second, explicit step costs one command and buys the
right to be trusted with the repository.
