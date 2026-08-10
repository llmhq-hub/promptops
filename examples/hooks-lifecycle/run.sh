#!/usr/bin/env bash
# The full git-hook lifecycle: install, use, inspect, uninstall.
#
# This example became necessary in v0.4.0, when `promptops init repo` stopped
# installing hooks by default. Hooks are now a deliberate second step, so the
# question "what do they actually do for me, and how do I turn them off" needs
# a concrete answer.
#
# Run: ./run.sh    (creates a throwaway repo under $TMPDIR, touches nothing else)

set -euo pipefail

WORK="${TMPDIR:-/tmp}/promptops-hooks-example"
rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

hr() { printf '\n%s\n%s\n' "$1" "$(printf '=%.0s' $(seq 1 60))"; }

hr "1. init: creates .promptops/, does NOT touch .git/hooks"

git init --quiet
git config user.email "example@promptops.dev"
git config user.name "PromptOps Example"
git config commit.gpgsign false

promptops init repo

echo
echo "hooks directory after init:"
ls -A .git/hooks 2>/dev/null | grep -v '\.sample$' || echo "  (no active hooks: this is the v0.4.0 default)"

hr "2. hooks status: before installing"
promptops hooks status || true

hr "3. hooks install: opt in deliberately"
promptops hooks install

echo
echo "hooks directory after install:"
ls -A .git/hooks | grep -v '\.sample$'

hr "4. hooks status: after installing"
promptops hooks status || true

hr "5. commit a prompt and watch versioning happen"

mkdir -p .promptops/prompts
cat > .promptops/prompts/greeting.yaml <<'YAML'
# Owned by the onboarding team. The comment survives the version bump.
metadata:
  id: greeting
  version: v1.0.0
  description: Onboarding greeting
template: |
  Hello {{ name }}.
variables:
  name:
    type: string
    required: true
YAML

git add .
# No `| tail`: the hook's output IS the demonstration, and truncating it was
# how this example managed to look fine while the hooks were broken.
git commit -m "feat: add greeting prompt"

echo
echo "the committed file, unchanged apart from the version line:"
git show HEAD:.promptops/prompts/greeting.yaml

hr "6. a breaking change bumps the major version"

cat > .promptops/prompts/greeting.yaml <<'YAML'
# Owned by the onboarding team. The comment survives the version bump.
metadata:
  id: greeting
  version: v1.0.0
  description: Onboarding greeting
template: |
  Hello {{ name }}, you are on the {{ tier }} plan.
variables:
  name:
    type: string
    required: true
  tier:
    type: string
    required: true
YAML

echo "what 'promptops test diff' says about it:"
# Defaults compare the committed version against the working directory, which
# is exactly the edit sitting here unstaged.
promptops test diff greeting | grep -i '^IMPACT'

echo
echo "and what the hook does with it (the same grader, so the same verdict):"
git add .
git commit -m "feat: add required tier variable"

hr "7. what the tooling knows now"
promptops history greeting

hr "8. doctor confirms hooks are live"
promptops doctor | grep -A1 '  hooks$'

hr "9. uninstall: back to a clean .git/hooks"
promptops hooks uninstall

echo
echo "hooks directory after uninstall:"
ls -A .git/hooks 2>/dev/null | grep -v '\.sample$' || echo "  (clean)"

hr "Done"
cat <<'EOF'
Takeaways:

  - `init repo` never writes to .git/hooks. Since v0.4.0 that is opt-in,
    because silently modifying someone's git hooks on first contact is a
    trust violation.
  - `hooks install` is the deliberate second step.
  - `hooks uninstall` fully reverses it, restoring any hook it displaced.
  - `promptops doctor` tells you which state you are in, so you never have
    to guess whether versioning is actually running. It also checks the
    hooks can actually import PromptOps, since a hook installed under one
    interpreter and run under another fails on every commit.
  - The hook rewrites the version line and nothing else: comments and
    block formatting survive.
  - The version bump and `promptops test diff` are the same grader, so a
    change graded MAJOR in review is versioned MAJOR on commit.
EOF
