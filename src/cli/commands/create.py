# cli/commands/create.py
import typer
import yaml
from pathlib import Path

from llmhq_promptops.core.template import PromptTemplate
from llmhq_promptops.core.validation import validate_prompt_id, sanitize_path

app = typer.Typer()


_STARTER_TEMPLATE = """You are a helpful assistant.

{{ user_input }}
"""


@app.command()
def prompt(
    prompt_id: str = typer.Argument(
        ..., help="Unique identifier for the new prompt (e.g. user-onboarding)"
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="Brief description of the prompt"
    ),
    model: str = typer.Option(
        "gpt-4-turbo", "--model", "-m", help="Default LLM model"
    ),
    template_file: str = typer.Option(
        None,
        "--template-file",
        "-t",
        help="Path to a Jinja2 template file. If omitted, a starter "
             "template is scaffolded for you to edit.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite if the prompt already exists"
    ),
):
    """
    Create a new prompt under .promptops/prompts/<id>.yaml.

    With no --template-file, scaffolds a starter template you can edit.
    Pass --template-file to seed the template from an existing Jinja2 file.
    """
    try:
        validate_prompt_id(prompt_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    prompt_path = Path(".promptops/prompts")
    out_file = prompt_path / f"{prompt_id}.yaml"
    if out_file.exists() and not force:
        typer.echo(
            f"Error: {out_file} already exists. Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(1)

    # Seed the template: from a file if given, else a starter.
    if template_file:
        try:
            safe_template = sanitize_path(Path(template_file), Path.cwd())
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        with open(safe_template, "r") as tf:
            template_content = tf.read()
        scaffolded = False
    else:
        template_content = _STARTER_TEMPLATE
        scaffolded = True

    prompt_structure = {
        "prompt": {
            "id": prompt_id,
            "description": description or f"{prompt_id} prompt",
            "model": model,
            "template": template_content,
        },
        # Auto-detect variables from the template so the file is renderable
        # out of the box.
        "variables": {},
    }

    # Best-effort variable auto-detection via the parser (handles the
    # template we just wrote). Failures here are non-fatal — the file is
    # still written; the user can add variables by hand.
    try:
        detected = PromptTemplate(
            yaml.safe_dump(prompt_structure)
        ).variables
        prompt_structure["variables"] = {
            name: {"type": v.type, "required": v.required}
            for name, v in detected.items()
        }
    except Exception:
        pass

    prompt_path.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as pf:
        yaml.dump(prompt_structure, pf, default_flow_style=False, sort_keys=False)

    typer.echo(f"✅ Created {out_file}")
    if scaffolded:
        typer.echo(
            "   Edit the template, then test it with:\n"
            f"     promptops test runtest --prompt {prompt_id}:unstaged"
        )
