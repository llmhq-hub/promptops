#!/usr/bin/env bash
# Build the snapshot from a real git repo, then prove it resolves without git.
#
# Two phases, matching how this works in CI:
#   1. BUILD  — in a git checkout, `promptops snapshot build` freezes prompts.
#   2. RUNTIME — a directory with only snapshot.json resolves them.
#
# Run: ./build.sh          (local, no Docker required)
#      ./build.sh --docker (also builds and runs the container)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${TMPDIR:-/tmp}/promptops-docker-example"

rm -rf "$WORK"
mkdir -p "$WORK/.promptops/prompts"

echo "==> Phase 1: build the snapshot from a git repo"

cat > "$WORK/.promptops/prompts/greeting.yaml" <<'YAML'
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

git -C "$WORK" init --quiet
git -C "$WORK" config user.email "example@promptops.dev"
git -C "$WORK" config user.name "PromptOps Example"
git -C "$WORK" config commit.gpgsign false
git -C "$WORK" add .
git -C "$WORK" commit --quiet -m "feat: greeting prompt"
git -C "$WORK" tag "prompt-greeting-v1.0.0"

( cd "$WORK" && promptops snapshot build --pretty )

echo "==> Phase 2: strip git, keep only snapshot.json"

RUNTIME="$WORK/runtime"
mkdir -p "$RUNTIME/.promptops"
cp "$WORK/.promptops/snapshot.json" "$RUNTIME/.promptops/snapshot.json"
cp "$HERE/app.py" "$RUNTIME/app.py"

echo "    runtime contents (note: no .git, no prompts/):"
find "$RUNTIME" -type f | sed "s|$RUNTIME|    .|"

echo "==> Phase 3: resolve with no git present"
( cd "$RUNTIME" && python app.py )

if [ "${1:-}" = "--docker" ]; then
  echo "==> Phase 4: same thing in a container"
  cp "$WORK/.promptops/snapshot.json" "$HERE/snapshot.json"
  docker build -t promptops-snapshot-example "$HERE"
  docker run --rm promptops-snapshot-example
  rm -f "$HERE/snapshot.json"
fi

echo
echo "Done. The runtime directory had no .git/ and no prompt YAML,"
echo "only snapshot.json, and resolution still worked."
