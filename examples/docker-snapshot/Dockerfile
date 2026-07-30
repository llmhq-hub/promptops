# Production image with NO .git/ directory.
#
# This is the point of the snapshot: your runtime image carries a single
# snapshot.json instead of a git working tree, and PromptOps resolves prompts
# from it. No git binary, no history, no .promptops/prompts/ YAML files.
#
# Build from this directory after running ./build.sh, which produces the
# snapshot from a real git repo.

FROM python:3.11-slim

WORKDIR /app

# Pinned deliberately. Resolving prompts with no git binary present needs
# >=0.5.0; on 0.4.0 and earlier `import llmhq_promptops` fails outright,
# because GitPython used to be imported at module scope and raises when
# there is no git executable. A floating requirement would install the
# broken version and fail at runtime instead of at build time.
RUN pip install --no-cache-dir 'llmhq-promptops>=0.5.0'

# The ONLY PromptOps artifact copied in. Note there is no .git/, and no
# .promptops/prompts/ either: the snapshot carries the prompt text itself.
COPY snapshot.json /app/.promptops/snapshot.json

COPY app.py /app/app.py

# Prove both negatives: no .git/ directory, and no git binary either. If
# either survived into the image, the example is not demonstrating what it
# claims to. python:3.11-slim ships no git, so this documents the fact
# rather than arranging it.
RUN test ! -d /app/.git || (echo "FAIL: .git leaked into the image" && exit 1)
RUN ! command -v git || (echo "FAIL: git binary present; this example proves nothing" && exit 1)

CMD ["python", "/app/app.py"]
