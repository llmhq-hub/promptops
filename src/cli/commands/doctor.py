# cli/commands/doctor.py
"""Health check CLI (v0.5.0, TODO-S4).

``promptops doctor`` — one command that answers "is this setup sane".

Exit 0 when every check is OK or WARN, 1 when any check FAILs. WARN covers
states you may have chosen deliberately (hooks are opt-in since v0.4.0, a repo
can legitimately have no snapshot yet), so warnings must not fail CI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from llmhq_promptops.core.health import CheckStatus, run_all_checks


_ICONS = {
    CheckStatus.OK: "OK  ",
    CheckStatus.WARN: "WARN",
    CheckStatus.FAIL: "FAIL",
}

_COLORS = {
    CheckStatus.OK: typer.colors.GREEN,
    CheckStatus.WARN: typer.colors.YELLOW,
    CheckStatus.FAIL: typer.colors.RED,
}


def doctor(
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
):
    """Check hooks, snapshot freshness, deploy log, versions, and resolver mode.

    Exits 0 if everything is OK or only warns, 1 if any check fails.

    Examples:

      promptops doctor
      promptops doctor --json
    """
    checks = run_all_checks(str(Path.cwd()))
    healthy = all(c.status is not CheckStatus.FAIL for c in checks)

    if as_json:
        typer.echo(
            json.dumps(
                {"healthy": healthy, "checks": [c.to_dict() for c in checks]},
                indent=2,
            )
        )
    else:
        color = not os.environ.get("NO_COLOR") and sys.stdout.isatty()

        typer.echo("🩺 PromptOps doctor")
        typer.echo("=" * 60)

        for check in checks:
            label = _ICONS[check.status]
            if color:
                label = typer.style(label, fg=_COLORS[check.status], bold=True)
            typer.echo(f"{label}  {check.name}")
            typer.echo(f"        {check.message}")
            if check.hint and check.status is not CheckStatus.OK:
                typer.echo(f"        hint: {check.hint}")

        typer.echo("")
        failures = sum(1 for c in checks if c.status is CheckStatus.FAIL)
        warnings = sum(1 for c in checks if c.status is CheckStatus.WARN)
        typer.echo(
            f"{len(checks)} checks, {failures} failed, {warnings} warned."
        )

    if not healthy:
        raise typer.Exit(1)
