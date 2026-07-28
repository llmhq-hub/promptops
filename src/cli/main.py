# cli/main.py
import typer
from cli.commands import init, create, render
from cli.commands import test, hooks, migrate, deploy, snapshot, blame, backfill_deploys
from cli.commands import history, doctor

app = typer.Typer(rich_markup_mode=None)

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
