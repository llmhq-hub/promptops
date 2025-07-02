# cli/commands/init.py
import typer
import subprocess
from pathlib import Path
from typing import Optional

app = typer.Typer()

@app.command()
def repo(
    with_hooks: bool = typer.Option(True, "--with-hooks/--no-hooks", help="Install git hooks automatically"),
    interactive: bool = typer.Option(True, "--interactive/--non-interactive", help="Show interactive prompts")
):
    """
    Initialize the LLMHQ-promptops repository structure with optional git hooks.
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
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    typer.echo("✅ Created .promptops directory structure")
    
    # Interactive configuration
    if interactive and with_hooks:
        typer.echo("\n🔧 Git Hook Configuration:")
        install_hooks = typer.confirm("Install git hooks for automatic versioning?", default=True)
        
        if install_hooks:
            run_tests = typer.confirm("Run basic tests before commits?", default=False)
            generate_reports = typer.confirm("Generate reports after commits?", default=True)
            verbose_logging = typer.confirm("Enable verbose logging?", default=False)
            
            # Create basic configuration
            _create_initial_config(run_tests, generate_reports, verbose_logging)
            
            # Install hooks
            if _install_hooks():
                typer.echo("✅ Git hooks installed successfully!")
                typer.echo("📝 Hooks will automatically version your prompts on commit.")
            else:
                typer.echo("⚠️  Hook installation failed. Run 'promptops hooks install' manually.")
        else:
            typer.echo("ℹ️  Skipping git hooks. Run 'promptops hooks install' later to enable automation.")
    elif with_hooks and not interactive:
        # Non-interactive mode with hooks
        _create_initial_config(False, True, False)
        if _install_hooks():
            typer.echo("✅ Git hooks installed with default configuration")
        else:
            typer.echo("⚠️  Hook installation failed")
    
    typer.echo("\n🎉 PromptOps initialization complete!")
    typer.echo("\n💡 Next steps:")
    typer.echo("   1. Create your first prompt: promptops create prompt my-prompt")
    typer.echo("   2. Test it: promptops test --prompt my-prompt:unstaged")
    typer.echo("   3. Commit changes to trigger automatic versioning")
    
    if not with_hooks:
        typer.echo("   4. Install hooks later: promptops hooks install")


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
    
    config_file = Path(".promptops/config.yaml")
    config_file.write_text(config_content)


def _install_hooks() -> bool:
    """Install git hooks. Returns True if successful."""
    try:
        # Import here to avoid circular imports
        from ..commands.hooks import _install_pre_commit_hook, _install_post_commit_hook
        
        # Find hooks directory
        repo_root = Path.cwd()
        while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        
        hooks_dir = repo_root / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        
        # Install hooks
        _install_pre_commit_hook(hooks_dir)
        _install_post_commit_hook(hooks_dir)
        
        return True
        
    except Exception as e:
        typer.echo(f"Hook installation failed: {e}", err=True)
        return False
