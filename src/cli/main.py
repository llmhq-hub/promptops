# cli/main.py
import typer
from cli.commands import init, create, render
from cli.commands import test, hooks

app = typer.Typer(rich_markup_mode=None)

app.add_typer(init.app, name="init", help="Initialize promptops structure")
app.add_typer(create.app, name="create", help="Create a new prompt template")
app.add_typer(render.app, name="render", help="Render a prompt with variables")
app.add_typer(test.app, name="test", help="Run prompt tests and generate reports")
app.add_typer(hooks.app, name="hooks", help="Manage git hooks for automatic versioning")


if __name__ == "__main__":
    app()
