# Day 0 Incident Playbook

Your agent did something wrong in production. This is the sequence for finding
out which prompt caused it, in minutes rather than an afternoon.

Read this once before you need it. During an incident, jump to
[The 60-second version](#the-60-second-version).

## The 60-second version

```bash
promptops blame --at "2026-05-20T14:32:00Z" --prompt refund-policy
```

That single command answers "what text was this prompt when the incident
happened". Everything below is context for when the answer is not enough.

## Prerequisite: you need a deploy log

`blame` reads `.promptops/deploys.jsonl`. If nothing writes to it, blame has
nothing to answer from and fails with `PROMPTOPS_E011`.

Check now, not during an incident:

```bash
promptops doctor
```

If the deploy-log check warns, you have two options:

```bash
# Going forward: record deploys in CI
promptops deploy event --env prod

# Retroactively: seed from commits already tagged as deploys
promptops backfill-deploys --from-git-log
```

## Step 1: what was running?

Start from the timestamp of the first bad output you can point at.

```bash
promptops blame --at "2026-05-20T14:32:00Z" --prompt refund-policy
```

```text
Blame: env=prod, at=2026-05-20T14:32:00+00:00

Deploy event:
  timestamp:   2026-05-20T14:20:58+00:00
  commit:      99f3a08eb03c (99f3a08eb03cc73095ceb6a199f4fb91dfb3c3a4)
  deployed_by: ci
  metadata:    (none)

Resolved prompt 'refund-policy' (source=git):
  version: 99f3a08eb03cc73095ceb6a199f4fb91dfb3c3a4
  commit:  99f3a08eb03cc73095ceb6a199f4fb91dfb3c3a4
  text:
    metadata:
      id: refund-policy
      description: Refund decision policy
    template: |
      Approve refunds under {{ threshold }} automatically.
      Escalate anything above to a human reviewer.
```

You now have the exact text that produced the behavior, and the commit it came
from. Drop `--prompt` to see every prompt at that deploy.

Timestamp accepts ISO 8601, a bare date (`2026-05-20`, meaning midnight UTC),
or the literal `now`. Use `--env staging` to blame a different environment;
it defaults to `prod`.

## Step 2: when did it change?

```bash
promptops history refund-policy
```

```text
📜 History for refund-policy
============================================================
  v1.2.0           99f3a08e  2026-05-20  Dev
      fix: escalate large refunds
      └─ deployed to prod at 2026-05-20T14:20:58+00:00 by ci

  v1.1.0           366919f1  2026-05-01  Dev
      feat: refund policy
      └─ deployed to prod at 2026-05-01T09:30:00+00:00 by ci
```

Deploy markers attach to the version that was **live** at that moment, not to
whichever commit the deploy event happens to name. A deploy event records the
repository commit, which usually is not the commit that last touched this
prompt.

If the incident began between two of those deploys, you have your window.

## Step 3: what exactly changed?

```bash
promptops test diff refund-policy --version1 366919f1 --version2 99f3a08e
```

```text
IMPACT: PATCH

--- 366919f1
+++ 99f3a08e
@@ -4,3 +4,4 @@
 template: |
   Approve refunds under {{ threshold }} automatically.
+  Escalate anything above to a human reviewer.
```

The impact line tells you whether the *contract* changed or only the wording.
`PATCH` means no caller-facing variable changed, so the behavior shift came
from the prose itself. `MAJOR` would mean the variable signature changed and
callers may be passing the wrong thing.

## Step 4: get back to safety

PromptOps does not roll back for you: it tells you what to roll back to.

```bash
git revert <commit>            # or check out the prior prompt version
promptops snapshot build       # rebuild the runtime artifact
promptops deploy event --env prod   # record the new deploy
```

Recording the recovery deploy matters. If you skip it, the next person to run
`blame` on this window gets an answer that stops at the bad deploy and never
learns it was fixed.

## When blame cannot answer

| Symptom | Cause | Fix |
| --- | --- | --- |
| `PROMPTOPS_E011` | No deploy events at or before that time | `promptops deploy list` to see what exists; the timestamp may predate your logging, or `--env` may be wrong |
| `PROMPTOPS_E004` | The commit is not resolvable in this checkout | `git fetch --all`; a shallow clone cannot see old commits |
| Warning about skipped lines | `deploys.jsonl` has malformed entries | `promptops doctor` names the line numbers; answers may be incomplete until repaired |
| Answer looks stale in a dev checkout | A `snapshot.json` is present and preferred over git | Blame prefers git when `.git/` exists (since v0.4.0); if you see this, check `promptops doctor`'s resolver line |

## Making the next incident cheaper

Three things, in order of payoff:

1. **Record deploys in CI.** One line in your deploy job. Without it none of
   the above works.
2. **Put impact on every PR.** Copy
   [`examples/github-actions/promptops-diff.yml`](../examples/github-actions/promptops-diff.yml).
   Most incidents are cheaper to prevent at review than to diagnose at 3am.
3. **Run `promptops doctor` in CI.** It catches a stale snapshot or a
   corrupted deploy log before the incident, not during it.

## Related

- [Production deployment guide](production-deployment.md): the snapshot
  pipeline and CI wiring the above assumes
- [Error codes](error-codes.md): every `PROMPTOPS_E0XX` with a fix
- [`examples/incident-archaeology-demo/`](../examples/incident-archaeology-demo/):
  a pre-baked repo to rehearse this on
