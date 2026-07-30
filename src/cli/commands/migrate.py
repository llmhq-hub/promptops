# cli/commands/migrate.py
"""Migration utilities for upgrading existing repos to newer promptops conventions.

Phase 1.5a M2b: ``tag-history`` creates per-prompt git tags retroactively for
historical commits, so users moving off the pre-M2 position-based fake-semver
(``v1.0.0`` derived from commit index) can get real, immutable version tags.
"""

import re
from typing import Optional

import typer
# GitPython is imported lazily inside the command: importing it at module
# scope makes `promptops --help` require a git binary. See
# core/git_versioning.py:repo for the full reasoning.

from llmhq_promptops.core.git_versioning import GitVersioning
from llmhq_promptops.core.validation import validate_prompt_id


app = typer.Typer()


@app.callback()
def _callback():
    """Migration utilities for upgrading existing repos to newer conventions."""
    # Presence of a callback forces Typer into multi-command mode, so that
    # ``promptops migrate tag-history ...`` (and any future subcommands)
    # are parsed as subcommands rather than as arguments to a single
    # implicit command. Without this, a sub-app with one ``@app.command``
    # treats the command name itself as an argument.


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse_start_version(s: str) -> tuple[int, int, int]:
    """Parse '0.1.0' or 'v0.1.0' into (major, minor, patch). Raises ValueError."""
    m = _VERSION_RE.match(s.strip())
    if not m:
        raise ValueError(
            f"Invalid version string: {s!r}. Expected e.g. 'v0.1.0' or '0.1.0'."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


@app.command("tag-history")
def tag_history(
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Prompt ID to tag. If omitted, every prompt under .promptops/prompts/ is tagged.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print planned tags without creating any. Use this first.",
    ),
    start_version: str = typer.Option(
        "v0.1.0",
        "--start-version",
        help="Version to assign to the OLDEST commit. Patch increments by 1 per commit.",
    ),
):
    """Tag every historical commit of a prompt with an immutable version.

    Produces tags of the form ``prompt-<id>-v<major>.<minor>.<patch>``, scoped
    per-prompt so multiple prompts can share commits without colliding.

    Use this after upgrading to v0.3.0+ if you depended on the old
    position-based fake-semver returned by ``get_latest_version()``. After
    tagging, the same calls return real, immutable versions instead of
    ``commit-<sha>`` strings.

    Example:

      promptops migrate tag-history --prompt user-onboarding --dry-run
      promptops migrate tag-history --prompt user-onboarding

    The command is idempotent: existing tags are skipped, not overwritten.
    """
    try:
        gv = GitVersioning(".")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not gv.is_git_repo():
        typer.echo("Error: not a git repository. Run 'git init' first.", err=True)
        raise typer.Exit(1)

    try:
        major0, minor0, patch0 = _parse_start_version(start_version)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if prompt is not None:
        try:
            validate_prompt_id(prompt)
        except ValueError as e:
            typer.echo(f"Error: invalid --prompt: {e}", err=True)
            raise typer.Exit(1)
        prompt_ids = [prompt]
    else:
        prompt_ids = gv.list_available_prompts()
        if not prompt_ids:
            typer.echo(
                "No prompts found under .promptops/prompts/. "
                "Run 'promptops init repo' to set up the directory first.",
                err=True,
            )
            raise typer.Exit(1)

    if dry_run:
        typer.echo("DRY RUN — no tags will be created.")
    typer.echo(f"Start version: v{major0}.{minor0}.{patch0}")
    typer.echo("")

    total_created = 0
    total_skipped = 0
    total_failed = 0

    existing_tag_names = {t.name for t in gv.repo.tags}

    for prompt_id in prompt_ids:
        prompt_file = f".promptops/prompts/{prompt_id}.yaml"
        try:
            commits = list(gv.repo.iter_commits(paths=prompt_file))
        except Exception as e:
            typer.echo(f"  [SKIP] {prompt_id}: {e}", err=True)
            continue

        if not commits:
            typer.echo(f"  [SKIP] {prompt_id}: no commits touch {prompt_file}")
            continue

        # Tag oldest first so patch number grows with chronology.
        commits.reverse()
        typer.echo(f"Prompt: {prompt_id} ({len(commits)} commit{'s' if len(commits) != 1 else ''})")

        for i, commit in enumerate(commits):
            patch = patch0 + i
            tag_name = f"prompt-{prompt_id}-v{major0}.{minor0}.{patch}"
            short = commit.hexsha[:8]

            if tag_name in existing_tag_names:
                typer.echo(f"  [SKIP] {short} → {tag_name} (tag already exists)")
                total_skipped += 1
                continue

            if dry_run:
                typer.echo(f"  [DRY ] {short} → {tag_name}")
                total_created += 1
                continue

            try:
                gv.repo.create_tag(
                    tag_name,
                    ref=commit.hexsha,
                    message=f"promptops migrate tag-history: {prompt_id} @ {short}",
                )
                existing_tag_names.add(tag_name)
                typer.echo(f"  [TAG ] {short} → {tag_name}")
                total_created += 1
            except Exception as e:
                typer.echo(f"  [FAIL] {short} → {tag_name}: {e}", err=True)
                total_failed += 1

        typer.echo("")

    verb = "would be created" if dry_run else "created"
    summary = f"Summary: {total_created} tag{'s' if total_created != 1 else ''} {verb}"
    if total_skipped:
        summary += f", {total_skipped} skipped"
    if total_failed:
        summary += f", {total_failed} failed"
    typer.echo(summary)

    if total_failed:
        raise typer.Exit(1)
