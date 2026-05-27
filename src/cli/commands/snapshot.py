# cli/commands/snapshot.py
"""Snapshot CLI (Phase 1.5a M3).

``promptops snapshot build``   — write ``.promptops/snapshot.json`` at a commit.
``promptops snapshot inspect`` — show what's in a snapshot file.

The snapshot is the production-runtime artifact: ship it with your Docker
image, point ``SnapshotResolver`` at it, and resolve prompts without git.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from llmhq_promptops.core.snapshot import (
    SNAPSHOT_FILENAME,
    SnapshotResolver,
    write_snapshot,
)


app = typer.Typer()


@app.callback()
def _callback():
    """Build and inspect production-runtime prompt snapshots."""
    # Force Typer into multi-command mode so ``promptops snapshot build`` and
    # ``promptops snapshot inspect`` parse correctly (see M2b for context).


@app.command("build")
def snapshot_build(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path. Defaults to .promptops/snapshot.json under the repo.",
    ),
    commit: Optional[str] = typer.Option(
        None,
        "--commit",
        "-c",
        help=(
            "Commit/tag to snapshot at. Defaults to HEAD working tree. "
            "Pass a SHA or tag to pin to that point in history."
        ),
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        help="Pretty-print JSON (larger file, easier to diff in code review).",
    ),
):
    """Write a snapshot of every prompt at the given commit.

    The snapshot contains, for each prompt under ``.promptops/prompts/``:
    raw YAML text, resolved version string, and the commit SHA.
    Production runtimes load this file via ``SnapshotResolver`` to resolve
    prompts without needing a git working tree.

    Example:

      promptops snapshot build                              # snapshot HEAD
      promptops snapshot build --commit v1.2.3              # snapshot a tag
      promptops snapshot build --output /tmp/snap.json      # custom path
      promptops snapshot build --pretty                     # readable JSON
    """
    try:
        path = write_snapshot(
            repo_path=str(Path.cwd()),
            output_path=output,
            commit=commit,
            pretty=pretty,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    # Read back to summarize what we just wrote — keeps output honest about
    # contents instead of guessing.
    data = json.loads(path.read_text(encoding="utf-8"))
    prompt_count = len(data.get("prompts", {}))
    size_bytes = path.stat().st_size

    typer.echo(f"Wrote {path}")
    typer.echo(
        f"  schema_version={data['schema_version']} "
        f"prompts={prompt_count} size={size_bytes} bytes"
    )
    typer.echo(
        f"  generated_from_commit={(data.get('generated_from_commit') or 'none')[:12]}"
    )


@app.command("inspect")
def snapshot_inspect(
    snapshot: Optional[Path] = typer.Option(
        None,
        "--snapshot",
        "-s",
        help="Path to snapshot.json. Defaults to .promptops/snapshot.json.",
    ),
    detail: bool = typer.Option(
        False,
        "--detail",
        help="Show full text of each prompt (default: just metadata).",
    ),
):
    """Print contents of an existing snapshot file.

    Without ``--detail`` it prints one line per prompt with version + commit.
    With ``--detail`` it prints the raw YAML text of each prompt.
    """
    snapshot_path: Path
    if snapshot is None:
        snapshot_path = Path.cwd() / ".promptops" / SNAPSHOT_FILENAME
    else:
        snapshot_path = snapshot.resolve()

    if not snapshot_path.exists():
        typer.echo(
            f"Error: {snapshot_path} does not exist. "
            f"Generate one with 'promptops snapshot build'.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        # Use SnapshotResolver to validate schema before printing.
        SnapshotResolver(snapshot_path=str(snapshot_path))
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    data = json.loads(snapshot_path.read_text(encoding="utf-8"))

    typer.echo(f"Snapshot: {snapshot_path}")
    typer.echo(f"  schema_version: {data['schema_version']}")
    typer.echo(f"  generated_at:   {data['generated_at']}")
    typer.echo(
        f"  generated_from_commit: "
        f"{(data.get('generated_from_commit') or 'none')}"
    )
    typer.echo(f"  promptops_version: {data.get('promptops_version', 'unknown')}")
    typer.echo("")

    prompts = data.get("prompts", {})
    if not prompts:
        typer.echo("  (no prompts in snapshot)")
        return

    typer.echo(f"Prompts ({len(prompts)}):")
    for pid in sorted(prompts.keys()):
        entry = prompts[pid]
        version = entry.get("version", "?")
        commit_short = (entry.get("commit") or "")[:8] or "none"
        text_len = len(entry.get("text", ""))
        typer.echo(
            f"  - {pid:<24} version={version}  commit={commit_short}  "
            f"bytes={text_len}"
        )
        if detail:
            typer.echo("    text:")
            for line in entry.get("text", "").splitlines():
                typer.echo(f"      {line}")
            typer.echo("")
