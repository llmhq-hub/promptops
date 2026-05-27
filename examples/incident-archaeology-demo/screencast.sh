#!/usr/bin/env bash
# screencast.sh — drives the 60-second incident-archaeology demo.
#
# This is the scripted, regenerable companion to the asciinema recording in
# the project README. Anyone with promptops installed can run it and watch
# the hero flow play out in their own terminal.
#
# To record an asciinema:
#
#   asciinema rec --idle-time-limit 2 promptops-blame-demo.cast \
#     --command "./screencast.sh"
#
# Then upload with:
#
#   asciinema upload promptops-blame-demo.cast
#
# Or convert to GIF for embedding in the README:
#
#   agg promptops-blame-demo.cast promptops-blame-demo.gif
#
# The script pauses between commands so a viewer has time to read each step
# before the next one runs. Override the pause with PAUSE=1 for a faster run
# (useful for CI smoke-tests):  PAUSE=1 ./screencast.sh

set -euo pipefail

PAUSE_SECONDS="${PAUSE:-3}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="${DEMO_DIR:-/tmp/promptops-demo}"

c_reset="\033[0m"
c_bold="\033[1m"
c_dim="\033[2m"
c_cyan="\033[36m"
c_green="\033[32m"

print_step() {
  echo ""
  printf "${c_bold}${c_cyan}>>> %s${c_reset}\n" "$1"
  echo ""
}

print_command() {
  printf "${c_dim}\$${c_reset} ${c_green}%s${c_reset}\n" "$1"
}

run() {
  print_command "$1"
  eval "$1"
  sleep "$PAUSE_SECONDS"
}

print_step "Setting up a fresh sample repo at $DEMO_DIR"
"$SOURCE_DIR/setup.sh" > /dev/null
cd "$DEMO_DIR"
sleep "$PAUSE_SECONDS"

print_step "1. What's been deployed?"
run "promptops deploy list"

print_step "2. Production broke at 2026-05-20T10:00:00Z. What was running?"
run "promptops blame --at 2026-05-20T10:00:00Z"

print_step "3. Show me the full text of the prompt that was running"
run "promptops blame --at 2026-05-20T10:00:00Z --prompt intent-classifier"

print_step "4. Build the production-runtime snapshot for the same commit"
run "promptops snapshot build"
run "promptops snapshot inspect"

print_step "Demo complete. Tear down with:  rm -rf $DEMO_DIR"
echo ""
