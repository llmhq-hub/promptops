# cli/commands/render.py
import typer
import yaml
from jinja2 import Template

app = typer.Typer()

@app.command()
def prompt(
    prompt_file: str = typer.Argument(..., help="Path to YAML prompt file"),
    vars_file: str = typer.Option(None, help="YAML file with variable values")
):
    """
    Render a prompt with provided variables.
    """
    with open(prompt_file, "r") as f:
        prompt_data = yaml.safe_load(f)

    template_str = prompt_data["prompt"]["template"]

    variables = {}
    if vars_file:
        with open(vars_file, "r") as vf:
            variables = yaml.safe_load(vf)

    template = Template(template_str)
    rendered_prompt = template.render(**variables)

    typer.echo(rendered_prompt)
