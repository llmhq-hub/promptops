# cli/commands/deploy.py
"""Deploy event log CLI (Phase 1.5a M4).

``promptops deploy event``  appends one entry to ``.promptops/deploys.jsonl``.
``promptops deploy list``   prints recent entries, optionally filtered by env.

The log is the audit trail M5's ``promptops blame --at <ts>`` reads to
answer "what was deployed in production at time T?"
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer

from llmhq_promptops.core.deploys import DeployEvent, DeployLog


app = typer.Typer()


@app.callback()
def _callback():
    """Record and inspect production deploy events."""
    # Presence of a callback forces Typer into multi-command mode so that
    # ``promptops deploy event`` and ``promptops deploy list`` parse as
    # subcommands rather than arguments to a single implicit command.


def _resolve_commit(repo: Path, explicit: Optional[str]) -> str:
    """Return the commit SHA to record. Either the user-provided value or HEAD."""
    if explicit:
        return explicit.strip()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise typer.BadParameter(
            "Could not resolve HEAD. Pass --commit <sha> explicitly, or "
            f"run inside a git repository. ({exc})"
        )


def _resolve_deployed_by(repo: Path, explicit: Optional[str]) -> str:
    """Return the actor to record. CLI arg > git user.name > $USER > 'unknown'."""
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        name = result.stdout.strip()
        if name:
            return name
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return os.environ.get("USER", "unknown")


def _parse_metadata(items: List[str]) -> dict:
    """Parse ``--metadata key=value`` flags into a flat dict."""
    out: dict = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(
                f"--metadata must be in 'key=value' form, got: {item!r}"
            )
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise typer.BadParameter(
                f"--metadata key must not be empty: {item!r}"
            )
        out[key] = value
    return out


@app.command("event")
def deploy_event(
    env: str = typer.Option(
        ...,
        "--env",
        "-e",
        help="Environment name (e.g. 'prod', 'staging', 'dev'). Required.",
    ),
    commit: Optional[str] = typer.Option(
        None,
        "--commit",
        "-c",
        help="Commit SHA being deployed. Defaults to HEAD if omitted.",
    ),
    by: Optional[str] = typer.Option(
        None,
        "--by",
        help="Actor performing the deploy. Defaults to git user.name, then $USER.",
    ),
    metadata: List[str] = typer.Option(
        [],
        "--metadata",
        "-m",
        help="Free-form 'key=value' annotation. Repeat for multiple entries.",
    ),
):
    """Append one deploy event to ``.promptops/deploys.jsonl``.

    The log is the audit trail behind ``promptops blame --at <timestamp>``:
    given a moment in production, blame walks back through the log to find
    the commit that was running at that moment, then resolves prompts at
    that commit.

    Example:

      promptops deploy event --env prod
      promptops deploy event --env staging --commit abc123 -m release=v1.2.3
    """
    repo = Path.cwd()
    log = DeployLog(str(repo))

    commit_sha = _resolve_commit(repo, commit)
    actor = _resolve_deployed_by(repo, by)
    meta = _parse_metadata(metadata)

    event = DeployEvent(
        timestamp=datetime.now(timezone.utc),
        env=env.strip(),
        commit=commit_sha,
        deployed_by=actor,
        metadata=meta,
    )

    try:
        log.append(event)
    except OSError as exc:
        typer.echo(f"Error: failed to append deploy event: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"Recorded deploy: env={event.env} commit={event.commit[:8]} "
        f"by={event.deployed_by} at={event.timestamp.isoformat()}"
    )
    typer.echo(f"Log: {log.path}")


@app.command("list")
def deploy_list(
    env: Optional[str] = typer.Option(
        None,
        "--env",
        "-e",
        help="Filter to one environment.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Maximum number of events to print (most recent first).",
    ),
):
    """Print recent deploy events from ``.promptops/deploys.jsonl``.

    Events are shown newest-first. Without ``--env`` all environments are
    interleaved; with it, only that environment is shown.
    """
    log = DeployLog(str(Path.cwd()))

    if not log.exists():
        typer.echo("No deploys.jsonl found. Record one with 'promptops deploy event'.")
        return

    events = log.all_events()
    if env is not None:
        events = [e for e in events if e.env == env.strip()]

    if not events:
        scope = f" for env={env!r}" if env else ""
        typer.echo(f"No deploy events recorded{scope}.")
        return

    # Reverse for newest-first; cap by limit.
    events = list(reversed(events))[:limit]

    for e in events:
        meta_str = (
            " " + " ".join(f"{k}={v}" for k, v in e.metadata.items())
            if e.metadata
            else ""
        )
        typer.echo(
            f"{e.timestamp.isoformat()}  env={e.env:<8} "
            f"commit={e.commit[:8]}  by={e.deployed_by}{meta_str}"
        )
