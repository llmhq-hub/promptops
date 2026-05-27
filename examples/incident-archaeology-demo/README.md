# Incident archaeology demo

Pre-baked sample repo demonstrating the `promptops blame --at <timestamp>` hero use case.

## What this is

A reproducible 60-second walkthrough of "production broke, which prompt was running when?" — without you needing to wire up your own repo first.

`setup.sh` builds a fresh git repo at `/tmp/promptops-demo` with:

- **3 prompts** (`summarizer`, `intent-classifier`, `refund-resolver`) committed across **5 dates** between 2026-05-15 and 2026-05-23. Each commit changes one prompt subtly — the kind of change that causes behaviour shifts in prod.
- **4 deploy events** recorded in `.promptops/deploys.jsonl`, spanning staging and prod across the timeline.
- A final `[deploy]` commit that records the deploy log itself.

After it runs, every command below answers a meaningful question instead of just "hello world".

## Prerequisites

```bash
pip install llmhq-promptops    # version >= 0.3.0
```

## Run it

```bash
cd examples/incident-archaeology-demo
./setup.sh
cd /tmp/promptops-demo
```

You can also run the scripted 60-second walkthrough end-to-end:

```bash
cd examples/incident-archaeology-demo
./screencast.sh
```

## Try the hero flow

```bash
# What was deployed and when?
promptops deploy list

# "An incident hit prod at 2026-05-20T10:00:00Z. What was running?"
promptops blame --at 2026-05-20T10:00:00Z

# Same question, but show the full text of one specific prompt:
promptops blame --at 2026-05-20T10:00:00Z --prompt intent-classifier
```

The answer for that timestamp is the `v0.2.0` prod deploy at commit `<C3>`, which is exactly the commit where `intent-classifier` got loosened to allow rationale strings. That's the kind of behaviour change `blame` is designed to surface — a prompt's text was edited two days before the incident, and the deploy went out at 08:00.

## Try the production-runtime path

```bash
# In CI, before shipping a Docker image:
promptops snapshot build
promptops snapshot inspect

# Now imagine you ship a Docker image that ONLY contains:
#   .promptops/snapshot.json
#   your app code
# (no .git/ at all)
#
# At runtime, AutoResolver picks the snapshot automatically:
python -c "
from llmhq_promptops import PromptManager, AutoResolver
m = PromptManager(resolver=AutoResolver(repo_path='.'))
print(m.resolve('summarizer').version)
"
```

## Try the migration command

```bash
# This demo's commits are untagged. blame works (via commit-<sha>),
# but if you want real semver tags on history:
promptops migrate tag-history --prompt summarizer --dry-run
promptops migrate tag-history --prompt summarizer

# Now the same blame call reports semver instead of commit-<sha>
promptops blame --at 2026-05-23T15:00:00Z --prompt summarizer
```

## The timeline this demo encodes

```
2026-05-15 09:00 UTC  commit C1  initial: add summarizer + intent-classifier
2026-05-15 18:00 UTC                                            DEPLOY → staging (v0.1.0)
2026-05-17 14:00 UTC  commit C2  add refund-resolver
2026-05-18 09:00 UTC                                            DEPLOY → prod    (v0.1.0)
2026-05-19 16:30 UTC  commit C3  loosen intent-classifier (allow rationale)
2026-05-20 08:00 UTC                                            DEPLOY → prod    (v0.2.0)  ← the change ships
2026-05-21 11:15 UTC  commit C4  tighten refund-resolver tone
2026-05-23 10:00 UTC  commit C5  summarizer default bullets 3 → 5
2026-05-24 15:00 UTC                                            DEPLOY → prod    (v0.3.0)
2026-05-24 15:01 UTC  commit C6  [deploy] record demo deploy events
```

A blame query at `2026-05-20T10:00:00Z` correctly resolves the v0.2.0 prod deploy at C3 — which is when intent-classifier's behaviour subtly shifted.

## Clean up

```bash
rm -rf /tmp/promptops-demo
```

`setup.sh` is idempotent — re-running it blows away `/tmp/promptops-demo` and rebuilds, so you don't have to clean up manually.
