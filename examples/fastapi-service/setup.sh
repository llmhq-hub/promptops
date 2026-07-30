#!/usr/bin/env bash
# Create the demo prompt repo this service resolves from.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

mkdir -p .promptops/prompts
cat > .promptops/prompts/greeting.yaml <<'YAML'
metadata:
  id: greeting
  description: Onboarding greeting
  models:
    default: gpt-4-turbo
template: |
  Hello {{ name }}, welcome aboard.
  Your plan is {{ tier }}.
variables:
  name:
    type: string
    required: true
  tier:
    type: string
    required: true
YAML

if [ ! -d .git ]; then
  git init --quiet
  git config user.email "example@promptops.dev"
  git config user.name "PromptOps Example"
  git config commit.gpgsign false
fi
git add .promptops
git commit --quiet -m "feat: greeting prompt" || true
git tag -f prompt-greeting-v1.0.0 >/dev/null

promptops snapshot build --pretty
echo
echo "Ready. Start the service with:  uvicorn main:app --reload"
