# cli/commands/init.py
import typer
import subprocess
from pathlib import Path
from typing import Optional

app = typer.Typer()

@app.command()
def repo(
    with_hooks: bool = typer.Option(
        False,
        "--with-hooks/--no-hooks",
        help=(
            "Also install git hooks for automatic versioning. "
            "Off by default since v0.4.0 — init never modifies .git/hooks/ "
            "unless you ask. Enable later with 'promptops hooks install'."
        ),
    ),
    interactive: bool = typer.Option(True, "--interactive/--non-interactive", help="Show interactive prompts")
):
    """
    Initialize the LLMHQ-promptops repository structure.

    Creates the .promptops/ directory tree and a default config.yaml.
    Does NOT touch .git/hooks/ unless --with-hooks is passed — installing
    hooks is a deliberate second step via 'promptops hooks install'.
    """
    # Validate git repository
    if not _is_git_repo():
        typer.echo("❌ Not in a git repository. Please run 'git init' first.", err=True)
        raise typer.Exit(1)

    # Create directory structure
    dirs = [
        ".promptops/prompts",
        ".promptops/configs",
        ".promptops/templates",
        ".promptops/vars",
        ".promptops/tests",
        ".promptops/results",
        ".promptops/logs",
        ".promptops/reports"
    ]

    typer.echo("🚀 Initializing PromptOps repository structure...")

    # Anchor to the repository root, the same place _install_hooks targets.
    # See _repo_root for why these must not diverge.
    root = _repo_root()

    for dir_path in dirs:
        (root / dir_path).mkdir(parents=True, exist_ok=True)

    typer.echo("✅ Created .promptops directory structure")

    if root != Path.cwd():
        # Never write outside the CWD silently.
        typer.echo(
            f"ℹ️  Wrote to the repository root ({root}), not the current "
            f"directory, so the prompts and the git hooks share a root."
        )

    # Directory + config only (D9): write a default config unless one
    # already exists — re-running init must never clobber user settings.
    if not (root / ".promptops" / "config.yaml").exists():
        _create_initial_config(False, True, False)
        typer.echo("✅ Created default .promptops/config.yaml")

    if with_hooks:
        if interactive:
            typer.echo("\n🔧 Git Hook Configuration:")
            run_tests = typer.confirm("Run basic tests before commits?", default=False)
            # Defaults to no, matching the hook: this writes markdown files
            # into the user's repository after every commit.
            generate_reports = typer.confirm(
                "Write a markdown report into .promptops/reports/ after commits?",
                default=False,
            )
            verbose_logging = typer.confirm("Enable verbose logging?", default=False)
            # Honor the same idempotency contract as the default path:
            # never silently clobber a config the user has already edited.
            config_path = _repo_root() / ".promptops" / "config.yaml"
            if not config_path.exists() or typer.confirm(
                f"{config_path} already exists. Overwrite with these answers?",
                default=False,
            ):
                _create_initial_config(run_tests, generate_reports, verbose_logging)

        if _install_hooks():
            typer.echo("✅ Git hooks installed successfully!")
            typer.echo("📝 Hooks will automatically version your prompts on commit.")
        else:
            typer.echo("⚠️  Hook installation failed. Run 'promptops hooks install' manually.")

    typer.echo("\n🎉 PromptOps initialization complete!")
    typer.echo("\n💡 Next steps:")
    typer.echo("   1. Create your first prompt: promptops create prompt my-prompt")
    typer.echo("   2. Test it: promptops test runtest --prompt my-prompt:unstaged")

    if with_hooks:
        typer.echo("   3. Commit changes to trigger automatic versioning")
    else:
        typer.echo("   3. Optional: enable automatic versioning with 'promptops hooks install'")
        typer.echo("      (init did not modify .git/hooks/ — hooks are opt-in since v0.4.0)")


def _is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except (FileNotFoundError, OSError):
        # No git binary on PATH at all. That is still "not a git repo" from
        # the caller's point of view, and it must produce init's friendly
        # message rather than a raw traceback.
        return False


def _repo_root() -> Path:
    """The git repository root, or the CWD if there is no .git/ above us.

    Both the ``.promptops/`` tree and the git hooks must be anchored to the
    same directory. Hooks can only live at the repository root, so that is
    where the prompts go too. Creating ``.promptops/`` in the CWD instead
    (the pre-v0.5.0 behavior) meant running ``init`` from a subdirectory put
    prompts and hooks in different places, and the root pre-commit hook then
    looked for ``.promptops/prompts/`` relative to itself, found nothing, and
    silently versioned nothing.
    """
    current = Path.cwd()
    while not (current / ".git").exists() and current != current.parent:
        current = current.parent
    return current if (current / ".git").exists() else Path.cwd()


def _create_initial_config(run_tests: bool, generate_reports: bool, verbose: bool):
    """Create initial configuration file."""
    config_content = f"""# PromptOps Configuration
# Generated during initialization

# Logging
verbose: {str(verbose).lower()}

# Pre-commit hook settings
pre_commit_tests: {str(run_tests).lower()}
block_on_test_failure: true

# Post-commit hook settings  
auto_tag_versions: true
post_commit_tests: {str(run_tests).lower()}
generate_reports: {str(generate_reports).lower()}

# Versioning rules
versioning:
  development:
    auto_increment: patch
    require_tests: false
  main:
    auto_increment: minor
    require_tests: {str(run_tests).lower()}
"""
    
    # Same anchor as the directory tree: see _repo_root.
    config_file = _repo_root() / ".promptops" / "config.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(config_content)


def _install_hooks() -> bool:
    """Install git hooks. Returns True if successful."""
    try:
        # Import here to avoid circular imports
        from ..commands.hooks import _install_pre_commit_hook, _install_post_commit_hook
        
        # Same root the .promptops/ tree was anchored to, so the hook can
        # actually find the prompts it is supposed to version.
        hooks_dir = _repo_root() / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        
        # Install hooks
        _install_pre_commit_hook(hooks_dir)
        _install_post_commit_hook(hooks_dir)
        
        return True
        
    except Exception as e:
        typer.echo(f"Hook installation failed: {e}", err=True)
        return False
