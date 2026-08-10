# cli/main.py
from typing import Optional

import typer

import llmhq_promptops
from cli.commands import init, create, render
from cli.commands import test, hooks, migrate, deploy, snapshot, blame, backfill_deploys
from cli.commands import history, doctor

app = typer.Typer(rich_markup_mode=None)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"promptops {llmhq_promptops.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version,
        is_eager=True,
        help="Show the installed PromptOps version and exit.",
    ),
) -> None:
    """Git-native prompt versioning, incident archaeology, and a
    production runtime that needs neither .git/ nor the git binary."""

app.add_typer(init.app, name="init", help="Initialize promptops structure")
app.add_typer(create.app, name="create", help="Create a new prompt template")
app.add_typer(render.app, name="render", help="Render a prompt with variables")
app.add_typer(test.app, name="test", help="Run prompt tests and generate reports")
app.add_typer(hooks.app, name="hooks", help="Manage git hooks for automatic versioning")
app.add_typer(migrate.app, name="migrate", help="Migration utilities (e.g. retroactive prompt version tagging)")
app.add_typer(deploy.app, name="deploy", help="Record and inspect production deploy events")
app.add_typer(snapshot.app, name="snapshot", help="Build and inspect production-runtime prompt snapshots")
app.add_typer(blame.app, name="blame", help="Show what was deployed at a given timestamp (incident archaeology)")
app.add_typer(backfill_deploys.app, name="backfill-deploys", help="Backfill the deploy event log from git history")
# Registered as a direct command, not a sub-app: `history` takes a positional
# argument and has no subcommands, and a positional Argument on a Typer group
# callback collides with subcommand parsing.
app.command("history", help="Show every version of a prompt, with the deploys that shipped it")(history.history)
app.command("doctor", help="Check hooks, snapshot freshness, deploy log, versions, and resolver mode")(doctor.doctor)


if __name__ == "__main__":
    app()
