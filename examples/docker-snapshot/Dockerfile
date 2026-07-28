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

RUN pip install --no-cache-dir llmhq-promptops

# The ONLY PromptOps artifact copied in. Note there is no .git/, and no
# .promptops/prompts/ either: the snapshot carries the prompt text itself.
COPY snapshot.json /app/.promptops/snapshot.json

COPY app.py /app/app.py

# Proves the negative: if any git directory survived into the image, the
# example is not demonstrating what it claims to.
RUN test ! -d /app/.git || (echo "FAIL: .git leaked into the image" && exit 1)

CMD ["python", "/app/app.py"]
