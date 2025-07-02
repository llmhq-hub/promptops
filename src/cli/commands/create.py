# cli/commands/create.py
import typer
import yaml
from pathlib import Path

app = typer.Typer()

@app.command()
def prompt(
    prompt_id: str = typer.Option(..., help="Unique identifier for the prompt"),
    description: str = typer.Option(..., help="Brief description of the prompt"),
    model: str = typer.Option("gpt-4-turbo", help="Default LLM model"),
    template_file: str = typer.Option(..., help="Path to Jinja2 template file")
):
    """
    Create a new prompt template from a Jinja2 file.
    """
    with open(template_file, "r") as tf:
        template_content = tf.read()

    prompt_structure = {
        "prompt": {
            "id": prompt_id,
            "description": description,
            "model": model,
            "template": template_content
        },
        "variables": []  # Optionally, this can be auto-detected or specified
    }

    prompt_path = Path(".promptops/prompts")
    prompt_path.mkdir(parents=True, exist_ok=True)

    with open(prompt_path / f"{prompt_id}.yaml", "w") as pf:
        yaml.dump(prompt_structure, pf)

    typer.echo(f"Prompt {prompt_id} created successfully.")
