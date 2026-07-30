# cli/commands/history.py
"""Prompt history CLI (v0.5.0, TODO-S3).

``promptops history <prompt-id>`` — every version this prompt has been,
newest first, with the deploys that actually shipped each one.

``blame --at <ts>`` answers "what was running then". This answers the
complementary question: "what has this prompt been, and which of those
versions ever reached production". Together they are the archaeology pair.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from llmhq_promptops import PromptManager
from llmhq_promptops.core.deploys import DeployEvent, DeployLog
from llmhq_promptops.core.errors import E003_PROMPT_NOT_FOUND, PromptOpsError


def _as_utc(value: datetime) -> datetime:
    """Normalize a commit datetime for comparison against deploy timestamps.

    ``GitVersioning.get_prompt_versions`` builds dates with
    ``datetime.fromtimestamp(...)``, which yields a *naive local* datetime,
    while ``DeployEvent.timestamp`` is always timezone-aware UTC. Comparing
    the two directly raises TypeError, so naive values are interpreted in the
    local zone (which is what fromtimestamp meant) and converted.
    """
    if value.tzinfo is None:
        return value.astimezone().astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _attribute_deploys(
    versions: List[Dict[str, Any]], events: List[DeployEvent]
) -> Dict[int, List[DeployEvent]]:
    """Map each deploy to the prompt version that was live when it happened.

    A deploy event records the *repository* commit, which is usually not the
    commit that last touched this prompt. The version actually shipped is the
    newest one committed at or before the deploy: the same semantic
    ``promptops blame --at`` uses.

    Args:
        versions: Newest-first, as returned by ``get_prompt_versions``.
        events: Deploy events to attribute.

    Returns:
        version index -> events shipped by that version.
    """
    attributed: Dict[int, List[DeployEvent]] = {}

    for event in events:
        when = _as_utc(event.timestamp)
        # versions are newest-first, so the first one at or before the
        # deploy is the one that was live.
        for index, version in enumerate(versions):
            if _as_utc(version["date"]) <= when:
                attributed.setdefault(index, []).append(event)
                break
        # A deploy predating every version ships no version of this prompt,
        # so it is intentionally dropped rather than pinned to the oldest.

    for events_for_version in attributed.values():
        events_for_version.sort(key=lambda e: e.timestamp)

    return attributed


def history(
    prompt_id: str = typer.Argument(..., help="Prompt id to show history for"),
    env: Optional[str] = typer.Option(
        None, "--env", help="Only show deploys to this environment."
    ),
    limit: int = typer.Option(
        20, "--limit", help="Maximum number of versions to show."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
):
    """Show every version of a prompt, with the deploys that shipped it.

    Examples:

      promptops history greeting
      promptops history greeting --env prod
      promptops history greeting --limit 5 --json
    """
    repo_path = str(Path.cwd())

    try:
        manager = PromptManager(repo_path)
        git = manager.git_versioning

        # get_prompt_versions returns [] for anything it cannot find, so an
        # unknown id would otherwise render as "no history" rather than "no
        # such prompt". Check existence explicitly against what is on disk.
        available = sorted(git.list_available_prompts())
        if prompt_id not in available:
            raise PromptOpsError(
                code=E003_PROMPT_NOT_FOUND,
                message=(
                    f"Prompt '{prompt_id}' not found. "
                    f"Available prompts: {available}"
                ),
                hint=(
                    "Check the spelling, or list what exists with "
                    "'promptops test status'."
                ),
            )

        all_versions = git.get_prompt_versions(prompt_id)
        total = len(all_versions)
        versions = all_versions[:limit]

        log = DeployLog(repo_path)
        events = log.events_for_env(env) if env else log.all_events()
        attributed = _attribute_deploys(versions, events)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    payload_versions = []
    for index, version in enumerate(versions):
        payload_versions.append(
            {
                "version": version["version"],
                "commit": version["commit"],
                "commit_short": version["commit_short"],
                "author": version["author"],
                "date": _as_utc(version["date"]).isoformat(),
                "message": version["message"],
                "deploys": [
                    {
                        "env": e.env,
                        "timestamp": e.timestamp.isoformat(),
                        "deployed_by": e.deployed_by,
                    }
                    for e in attributed.get(index, [])
                ],
            }
        )

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "prompt": prompt_id,
                    "shown": len(payload_versions),
                    "total": total,
                    "versions": payload_versions,
                },
                indent=2,
            )
        )
        return

    typer.echo(f"📜 History for {prompt_id}")
    typer.echo("=" * 60)

    if not payload_versions:
        typer.echo(
            "No committed history yet. This prompt exists on disk but has "
            "not been committed."
        )
        return

    for entry in payload_versions:
        date = entry["date"][:10]
        typer.echo(
            f"  {entry['version']:<16} {entry['commit_short']}  {date}  "
            f"{entry['author']}"
        )
        typer.echo(f"      {entry['message'].splitlines()[0]}")
        for deploy in entry["deploys"]:
            typer.echo(
                f"      └─ deployed to {deploy['env']} "
                f"at {deploy['timestamp']} by {deploy['deployed_by']}"
            )
        typer.echo("")

    # Silent truncation reads as "this is the whole history" when it is not.
    if total > len(payload_versions):
        typer.echo(
            f"Showing {len(payload_versions)} of {total} versions. "
            f"Pass --limit {total} to see them all."
        )
