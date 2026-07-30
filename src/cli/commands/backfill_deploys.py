# cli/commands/backfill_deploys.py
"""``promptops backfill-deploys --from-git-log`` (Phase 1.5a M5b).

Escape hatch for repos that adopt promptops mid-stream. Walks git history,
finds commits matching a pattern (default ``[deploy]`` prefix), and writes
one ``DeployEvent`` per matching commit into ``.promptops/deploys.jsonl``.

Idempotent: events that already exist for the same ``(commit, env)`` are
skipped. Safe to run repeatedly as the team imports more history.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
# GitPython is imported lazily inside the command: importing it at module
# scope makes `promptops --help` require a git binary. See
# core/git_versioning.py:repo for the full reasoning.

from llmhq_promptops.core.deploys import DeployEvent, DeployLog


app = typer.Typer()


_DEFAULT_PATTERN = r"^\[deploy\]"


@app.callback(invoke_without_command=True)
def backfill_deploys(
    from_git_log: bool = typer.Option(
        False,
        "--from-git-log",
        help="Scan git log for deploy-shaped commits (required — selects source).",
    ),
    env: str = typer.Option(
        "prod",
        "--env",
        "-e",
        help="Environment to record under. Default 'prod'.",
    ),
    pattern: str = typer.Option(
        _DEFAULT_PATTERN,
        "--pattern",
        help=(
            "Regex matched against commit messages (re.search). Default "
            f"{_DEFAULT_PATTERN!r}. Use '.*' to backfill every commit "
            "(not usually what you want)."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show planned events without writing. Run this first.",
    ),
):
    """Backfill ``.promptops/deploys.jsonl`` from existing git history.

    Walks the current branch's commit log oldest-first. For each commit whose
    message matches ``--pattern``, creates a ``DeployEvent`` with:

      timestamp   = commit's authored time (UTC)
      env         = --env value
      commit      = full SHA
      deployed_by = commit author name
      metadata    = {"backfilled": "true", "source": "git-log"}

    The metadata flag lets downstream analysis tell backfilled events apart
    from real-time ones recorded by ``promptops deploy event``.

    The operation is idempotent: events that already exist for the same
    (commit, env) are skipped, so repeated runs are safe.

    Example:

      promptops backfill-deploys --from-git-log --dry-run
      promptops backfill-deploys --from-git-log
      promptops backfill-deploys --from-git-log --env staging --pattern '^release:'
    """
    if not from_git_log:
        typer.echo(
            "Error: --from-git-log is required (it's the only supported "
            "source today). Pass it explicitly to opt in.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        typer.echo(f"Error: --pattern {pattern!r} is not a valid regex: {exc}", err=True)
        raise typer.Exit(1)

    repo_path = Path.cwd()
    try:
        from git import InvalidGitRepositoryError, Repo

        repo = Repo(str(repo_path))
    except InvalidGitRepositoryError:
        typer.echo(
            f"Error: {repo_path} is not a git repository. Backfilling "
            f"requires git history to scan.",
            err=True,
        )
        raise typer.Exit(1)

    log = DeployLog(str(repo_path))
    # Existing (commit, env) pairs guard against duplicate entries. Loaded
    # once up-front so re-running the command is O(commits + existing).
    existing = {(e.commit, e.env) for e in log.iter_events()}

    if dry_run:
        typer.echo("DRY RUN — no events will be written.")

    typer.echo(f"Scanning git log with pattern {pattern!r} (env={env})...")
    typer.echo("")

    matching_commits = []
    for commit in repo.iter_commits():
        msg = commit.message if isinstance(commit.message, str) else commit.message.decode("utf-8", errors="replace")
        if compiled.search(msg):
            matching_commits.append(commit)

    if not matching_commits:
        typer.echo(f"No commits matched {pattern!r}. Nothing to backfill.")
        return

    # Oldest first so the JSONL log stays chronological.
    matching_commits.reverse()

    created = 0
    skipped = 0
    failed = 0

    for commit in matching_commits:
        sha = commit.hexsha
        short = sha[:8]
        first_line = (
            commit.message.splitlines()[0]
            if isinstance(commit.message, str)
            else commit.message.decode("utf-8", errors="replace").splitlines()[0]
        )

        if (sha, env) in existing:
            typer.echo(f"  [SKIP] {short} (event already exists for env={env}): {first_line[:60]}")
            skipped += 1
            continue

        ts = datetime.fromtimestamp(commit.authored_date, tz=timezone.utc)
        try:
            event = DeployEvent(
                timestamp=ts,
                env=env,
                commit=sha,
                deployed_by=str(commit.author.name) if commit.author else "unknown",
                metadata={"backfilled": "true", "source": "git-log"},
            )
        except ValueError as exc:
            typer.echo(f"  [FAIL] {short}: {exc}", err=True)
            failed += 1
            continue

        if dry_run:
            typer.echo(
                f"  [DRY ] {short}  ts={ts.isoformat()}  by={event.deployed_by}: {first_line[:60]}"
            )
            created += 1
            continue

        try:
            log.append(event)
            existing.add((sha, env))
            typer.echo(
                f"  [TAG ] {short}  ts={ts.isoformat()}  by={event.deployed_by}: {first_line[:60]}"
            )
            created += 1
        except OSError as exc:
            typer.echo(f"  [FAIL] {short}: {exc}", err=True)
            failed += 1

    typer.echo("")
    verb = "would be created" if dry_run else "created"
    summary = f"Summary: {created} event{'s' if created != 1 else ''} {verb}"
    if skipped:
        summary += f", {skipped} skipped"
    if failed:
        summary += f", {failed} failed"
    typer.echo(summary)

    if failed:
        raise typer.Exit(1)
