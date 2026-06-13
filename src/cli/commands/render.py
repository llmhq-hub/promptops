# cli/commands/render.py
import typer
import yaml
from pathlib import Path

from llmhq_promptops.core.template import PromptTemplate
from llmhq_promptops.core.validation import sanitize_path

app = typer.Typer()


@app.command()
def prompt(
    prompt_file: str = typer.Argument(..., help="Path to YAML prompt file"),
    vars_file: str = typer.Option(None, help="YAML file with variable values")
):
    """
    Render a prompt with provided variables.

    Accepts either prompt-file schema (the ``metadata:`` layout documented
    in the README, or the legacy ``prompt:`` layout) — both are handled by
    PromptTemplate, which also renders inside a Jinja2 sandbox.
    """
    # Validate file paths are within current working directory
    try:
        safe_prompt = sanitize_path(Path(prompt_file), Path.cwd())
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    with open(safe_prompt, "r") as f:
        yaml_content = f.read()

    # PromptTemplate handles both schemas and parses/validates the file.
    try:
        template = PromptTemplate(yaml_content)
    except Exception as e:
        typer.echo(f"Error: could not parse prompt file: {e}", err=True)
        raise typer.Exit(1)

    variables = {}
    if vars_file:
        try:
            safe_vars = sanitize_path(Path(vars_file), Path.cwd())
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        with open(safe_vars, "r") as vf:
            variables = yaml.safe_load(vf) or {}

    # PromptTemplate.render uses the SandboxedEnvironment internally.
    try:
        rendered_prompt = template.render(variables)
    except Exception as e:
        typer.echo(f"Error: render failed: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(rendered_prompt)
