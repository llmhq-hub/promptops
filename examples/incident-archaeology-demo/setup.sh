#!/usr/bin/env bash
# setup.sh — build a tmp git repo with pre-baked promptops history.
#
# Output: a directory at $DEMO_DIR (default /tmp/promptops-demo) that contains:
#   - .git/                             a real git repo with 6 commits over 10 days
#   - .promptops/prompts/*.yaml         3 prompts that evolve over those commits
#   - .promptops/deploys.jsonl          4 deploy events (staging + prod, across the timeline)
#
# After this runs you can demonstrate the v0.3.0 hero use case:
#   cd $DEMO_DIR
#   promptops deploy list
#   promptops blame --at 2026-05-20T10:00:00Z
#
# Re-runnable: the script blows away $DEMO_DIR if it exists, so it's safe to run repeatedly.

set -euo pipefail

DEMO_DIR="${DEMO_DIR:-/tmp/promptops-demo}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Setting up incident-archaeology demo at $DEMO_DIR"

if ! command -v promptops >/dev/null 2>&1; then
  echo "ERROR: 'promptops' CLI not found on PATH."
  echo "       Install it first: pip install llmhq-promptops"
  exit 1
fi

if [ -d "$DEMO_DIR" ]; then
  echo "==> Removing existing $DEMO_DIR"
  rm -rf "$DEMO_DIR"
fi

mkdir -p "$DEMO_DIR/.promptops/prompts"
cd "$DEMO_DIR"

git init --quiet
git config user.email "demo@promptops.dev"
git config user.name "PromptOps Demo"
git config commit.gpgsign false

# Helper: commit with an explicit author + committer date.
# Using GIT_AUTHOR_DATE and GIT_COMMITTER_DATE lets us back-date history so the
# demo timeline is deterministic regardless of when setup.sh actually runs.
commit_at() {
  local iso_date="$1"
  local message="$2"
  GIT_AUTHOR_DATE="$iso_date" GIT_COMMITTER_DATE="$iso_date" \
    git commit --quiet --date="$iso_date" -m "$message"
}

# Helper: record a deploy event with a back-dated timestamp by writing the
# JSONL line directly. We mirror the format DeployLog.append uses.
record_deploy() {
  local iso_ts="$1"
  local env="$2"
  local commit_sha="$3"
  local who="$4"
  local extra="$5"   # optional metadata, JSON object body without braces

  local metadata="{}"
  if [ -n "$extra" ]; then
    metadata="{${extra}}"
  fi

  printf '{"timestamp":"%s","env":"%s","commit":"%s","deployed_by":"%s","metadata":%s}\n' \
    "$iso_ts" "$env" "$commit_sha" "$who" "$metadata" \
    >> .promptops/deploys.jsonl
}

# ── Commit 1: 2026-05-15 — initial prompts ─────────────────────────
cp "$SOURCE_DIR/prompts/summarizer.yaml"        .promptops/prompts/summarizer.yaml
cp "$SOURCE_DIR/prompts/intent-classifier.yaml" .promptops/prompts/intent-classifier.yaml
git add .promptops/
commit_at "2026-05-15T09:00:00Z" "initial: add summarizer + intent-classifier"
C1=$(git rev-parse HEAD)

# ── Commit 2: 2026-05-17 — add refund-resolver ─────────────────────
cp "$SOURCE_DIR/prompts/refund-resolver.yaml"   .promptops/prompts/refund-resolver.yaml
git add .promptops/
commit_at "2026-05-17T14:00:00Z" "add refund-resolver prompt for support flow"
C2=$(git rev-parse HEAD)

# ── Commit 3: 2026-05-19 — soften intent-classifier ────────────────
# A subtle wording change. This is the kind of change that causes a behavior
# shift in prod — the prompt's text shifted, and now responses are different.
sed -i.bak 's/Respond with just the label, nothing else./Respond with the label. You may also include a one-sentence rationale./' \
  .promptops/prompts/intent-classifier.yaml
rm .promptops/prompts/intent-classifier.yaml.bak
git add .promptops/
commit_at "2026-05-19T16:30:00Z" "loosen intent-classifier to allow rationale"
C3=$(git rev-parse HEAD)

# ── Commit 4: 2026-05-21 — refund-resolver tone change ─────────────
sed -i.bak 's/Draft a polite reply that:/Draft a firm but fair reply that:/' \
  .promptops/prompts/refund-resolver.yaml
rm .promptops/prompts/refund-resolver.yaml.bak
git add .promptops/
commit_at "2026-05-21T11:15:00Z" "tighten refund-resolver tone"
C4=$(git rev-parse HEAD)

# ── Commit 5: 2026-05-23 — summarizer bullet count ─────────────────
sed -i.bak 's/default: 3$/default: 5/' .promptops/prompts/summarizer.yaml
rm .promptops/prompts/summarizer.yaml.bak
git add .promptops/
commit_at "2026-05-23T10:00:00Z" "summarizer: default bullets 3 -> 5"
C5=$(git rev-parse HEAD)

# ── Deploy log: 4 events across the timeline ───────────────────────
# Each deploy points to one of the commits above. The blame command will use
# these timestamps + the commit pinning to resolve "what was running at T".

record_deploy "2026-05-15T18:00:00Z" "staging" "$C1" "demo-ci" '"release":"v0.1.0"'
record_deploy "2026-05-18T09:00:00Z" "prod"    "$C2" "demo-ci" '"release":"v0.1.0","ticket":"SUPPORT-12"'
record_deploy "2026-05-20T08:00:00Z" "prod"    "$C3" "demo-ci" '"release":"v0.2.0"'
record_deploy "2026-05-24T15:00:00Z" "prod"    "$C5" "demo-ci" '"release":"v0.3.0","note":"5-bullet summarizer"'

git add .promptops/deploys.jsonl
commit_at "2026-05-24T15:01:00Z" "[deploy] record demo deploy events"

echo ""
echo "==> Done. Demo repo ready at $DEMO_DIR"
echo ""
echo "Try these commands (cd $DEMO_DIR first):"
echo ""
echo "  promptops deploy list"
echo "  promptops blame --at 2026-05-20T10:00:00Z          # 2 hours after the v0.2.0 deploy"
echo "  promptops blame --at 2026-05-20T10:00:00Z --prompt intent-classifier"
echo "  promptops snapshot build && promptops snapshot inspect"
echo ""
echo "Or run the scripted screencast:"
echo "  cd $SOURCE_DIR && ./screencast.sh"
