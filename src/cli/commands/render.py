# cli/commands/render.py
import typer
import yaml
from pathlib import Path
from jinja2.sandbox import SandboxedEnvironment

from llmhq_promptops.core.validation import sanitize_path

app = typer.Typer()

_sandbox_env = SandboxedEnvironment()

@app.command()
def prompt(
    prompt_file: str = typer.Argument(..., help="Path to YAML prompt file"),
    vars_file: str = typer.Option(None, help="YAML file with variable values")
):
    """
    Render a prompt with provided variables.
    """
    # Validate file paths are within current working directory
    try:
        safe_prompt = sanitize_path(Path(prompt_file), Path.cwd())
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    with open(safe_prompt, "r") as f:
        prompt_data = yaml.safe_load(f)

    template_str = prompt_data["prompt"]["template"]

    variables = {}
    if vars_file:
        try:
            safe_vars = sanitize_path(Path(vars_file), Path.cwd())
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        with open(safe_vars, "r") as vf:
            variables = yaml.safe_load(vf)

    template = _sandbox_env.from_string(template_str)
    rendered_prompt = template.render(**variables)

    typer.echo(rendered_prompt)
