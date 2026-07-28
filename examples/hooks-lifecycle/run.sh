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
metadata:
  id: greeting
  description: Onboarding greeting
template: |
  Hello {{ name }}.
variables:
  name:
    type: string
    required: true
YAML

git add .
git commit -m "feat: add greeting prompt" 2>&1 | tail -5

hr "6. what the tooling knows now"
promptops history greeting || true

hr "7. doctor confirms hooks are live"
promptops doctor | grep -A1 '  hooks$'

hr "8. uninstall: back to a clean .git/hooks"
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
    to guess whether versioning is actually running.
EOF
