# cli/commands/blame.py
"""``promptops blame --at <timestamp>`` — incident archaeology (Phase 1.5a M5).

Given a moment in production, answer "which prompts were running, and what
did their text say?"

Composes three primitives:

1. ``DeployLog.find_at(ts, env=...)``  — locate the deploy event covering ``ts``.
2. ``AutoResolver.resolve(prompt_id, version=event.commit)``  — resolve each
   prompt at that deploy's commit (works in dev with git, prod with snapshot).
3. ``GitVersioning.list_available_prompts()``  — enumerate prompts to display
   when no ``--prompt`` filter is given.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from llmhq_promptops.core.deploys import DeployLog
from llmhq_promptops.core.errors import E011_NO_DEPLOY_EVENTS, PromptOpsError
from llmhq_promptops.core.snapshot import AutoResolver
from llmhq_promptops.core.git_versioning import GitVersioning
from llmhq_promptops.core.validation import validate_prompt_id


app = typer.Typer()


def _parse_timestamp(raw: str) -> datetime:
    """Parse the ``--at`` value into a tz-aware datetime.

    Accepts:
    - ``"now"``
    - ISO 8601 with Z suffix: ``2026-05-26T14:00:00Z``
    - ISO 8601 with offset: ``2026-05-26T14:00:00+00:00``
    - Date only: ``2026-05-26`` (interpreted as 00:00:00 UTC)

    Naive ISO strings without tz info are interpreted as UTC, with a stderr
    note so the caller knows the assumption was made.
    """
    raw = raw.strip()
    if raw.lower() == "now":
        return datetime.now(timezone.utc)

    # ``datetime.fromisoformat`` accepts the "Z" suffix from 3.11+; normalize
    # for older interpreters by replacing it explicitly.
    normalized = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw

    try:
        ts = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise typer.BadParameter(
            f"--at value {raw!r} is not a valid timestamp. "
            f"Examples: 'now', '2026-05-26', '2026-05-26T14:00:00Z', "
            f"'2026-05-26T14:00:00+00:00'. ({exc})"
        )

    if ts.tzinfo is None:
        typer.echo(
            f"Note: --at value {raw!r} has no timezone; assuming UTC.",
            err=True,
        )
        ts = ts.replace(tzinfo=timezone.utc)

    return ts


def _format_metadata(meta: dict) -> str:
    if not meta:
        return "(none)"
    return " ".join(f"{k}={v}" for k, v in meta.items())


@app.callback(invoke_without_command=True)
def blame(
    at: str = typer.Option(
        ...,
        "--at",
        help=(
            "When did the incident happen? ISO 8601 timestamp, date "
            "(YYYY-MM-DD → midnight UTC), or the literal 'now'."
        ),
    ),
    env: str = typer.Option(
        "prod",
        "--env",
        "-e",
        help="Environment to blame. Defaults to 'prod'.",
    ),
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help=(
            "If set, show only this prompt with its full text. Otherwise "
            "show every prompt resolved at that deploy commit."
        ),
    ),
):
    """Show what was deployed in production at a given moment.

    The Phase 1.5a hero use case: an LLM behavior changed in production and
    you need to know *which* prompt version was running when it happened.
    This command pairs the deploy event log (``promptops deploy event``)
    with the Resolver layer to give a precise answer.

    Examples:

      promptops blame --at 2026-05-26T14:00:00Z
      promptops blame --at 'now' --env staging
      promptops blame --at 2026-05-26 --prompt user-onboarding
    """
    ts = _parse_timestamp(at)

    repo = Path.cwd()
    log = DeployLog(str(repo))

    if not log.exists():
        err = PromptOpsError(
            code=E011_NO_DEPLOY_EVENTS,
            message="No deploy log at .promptops/deploys.jsonl.",
            hint=(
                "Record deploys with 'promptops deploy event' in CI, or "
                "backfill from git history with "
                "'promptops backfill-deploys --from-git-log'."
            ),
        )
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(1)

    # Corrupted lines must never silently skew the answer: count them
    # and tell the user before showing the result.
    log_read = log.read()
    if log_read.skipped:
        lines = ", ".join(str(n) for n in log_read.skipped_lines)
        typer.echo(
            f"Warning: {log_read.skipped} malformed deploy event line(s) "
            f"skipped (line {lines} of deploys.jsonl). The answer below "
            f"may be incomplete — inspect the file or re-record those "
            f"deploys.",
            err=True,
        )

    event = log.find_at(ts, env=env)
    if event is None:
        err = PromptOpsError(
            code=E011_NO_DEPLOY_EVENTS,
            message=(
                f"No deploy events for env={env!r} at or before "
                f"{ts.isoformat()}."
            ),
            hint=(
                "Either the timestamp predates any recorded deploy, or the "
                "env name is wrong. Run 'promptops deploy list' to see "
                "what's recorded."
            ),
        )
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(1)

    # Banner: which deploy answers the question.
    typer.echo(f"Blame: env={env}, at={ts.isoformat()}")
    typer.echo("")
    typer.echo("Deploy event:")
    typer.echo(f"  timestamp:   {event.timestamp.isoformat()}")
    typer.echo(f"  commit:      {event.commit[:12]} ({event.commit})")
    typer.echo(f"  deployed_by: {event.deployed_by}")
    typer.echo(f"  metadata:    {_format_metadata(event.metadata)}")
    typer.echo("")

    # blame is incident archaeology: it resolves prompts at *arbitrary
    # historical deploy commits*. A snapshot.json is frozen at ONE build
    # commit, so AutoResolver's default snapshot-preference makes blame
    # fail with E004 at every other commit once a snapshot exists in the
    # repo. Prefer git whenever .git/ is present; only fall back to the
    # snapshot in a snapshot-only runtime (where blame can answer for the
    # snapshot's pinned commit and little else).
    prefer = "git" if (repo / ".git").exists() else "auto"
    try:
        resolver = AutoResolver(repo_path=str(repo), prefer=prefer)
    except ValueError as exc:
        typer.echo(f"Error: cannot construct resolver: {exc}", err=True)
        raise typer.Exit(1)

    if prompt is not None:
        try:
            validate_prompt_id(prompt)
        except ValueError as exc:
            typer.echo(f"Error: invalid --prompt: {exc}", err=True)
            raise typer.Exit(1)

        try:
            resolved = resolver.resolve(prompt, event.commit)
        except ValueError as exc:
            typer.echo(f"Error resolving '{prompt}' at deploy commit: {exc}", err=True)
            raise typer.Exit(1)

        typer.echo(f"Resolved prompt '{prompt}' (source={resolved.source}):")
        typer.echo(f"  version: {resolved.version}")
        typer.echo(f"  commit:  {resolved.commit or '(none)'}")
        typer.echo("  text:")
        for line in resolved.text.splitlines():
            typer.echo(f"    {line}")
        return

    # All-prompts mode. Enumerate using GitVersioning when available, fall
    # back to whatever the resolver exposes. In a snapshot-only runtime,
    # ``list_available_prompts`` would still work because it just reads
    # the .promptops/prompts/ dir, which is checked-in source.
    try:
        gv = GitVersioning(str(repo))
        prompt_ids = sorted(gv.list_available_prompts())
    except Exception:
        # Best-effort: directory listing without git.
        prompts_dir = repo / ".promptops" / "prompts"
        if prompts_dir.exists():
            prompt_ids = sorted(p.stem for p in prompts_dir.glob("*.yaml"))
        else:
            prompt_ids = []

    if not prompt_ids:
        typer.echo(
            "No prompts found under .promptops/prompts/ to resolve. "
            "Pass --prompt <id> if you know which one you want.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"Resolved prompts ({len(prompt_ids)}):")
    failures: list[tuple[str, Optional[str], str]] = []
    for pid in prompt_ids:
        try:
            r = resolver.resolve(pid, event.commit)
            typer.echo(
                f"  {pid:<24} version={r.version}  commit={(r.commit or 'none')[:8]}"
            )
        except ValueError as exc:
            # A prompt may not have existed at the deploy commit — that's
            # informational, not fatal. Keep the code and the message apart:
            # rendering str(exc) spent 18 of 120 display columns on the
            # "[PROMPTOPS_E0XX] " prefix, squeezing out the part that says
            # what actually happened.
            code = getattr(exc, "code", None)
            message = getattr(exc, "message", None) or str(exc)
            failures.append((pid, code, message))

    if failures:
        typer.echo("")
        typer.echo(f"Note: {len(failures)} prompt(s) could not be resolved at this commit:")
        for pid, code, message in failures:
            # PROMPTOPS_E003 -> E003: still greppable, 12 columns cheaper.
            label = f"[{code.removeprefix('PROMPTOPS_')}] " if code else ""
            typer.echo(f"  {pid}: {label}{message.splitlines()[0][:120]}")
