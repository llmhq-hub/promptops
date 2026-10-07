# cli/commands/hooks.py
import typer
import subprocess
import os
import sys
import stat
from pathlib import Path

app = typer.Typer()


@app.command()
def install():
    """Install PromptOps git hooks for automatic versioning."""
    
    # Find the hooks directory
    try:
        repo_root = Path.cwd()
        while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        
        if not (repo_root / ".git").exists():
            typer.echo("❌ Not in a git repository", err=True)
            raise typer.Exit(1)
        
        hooks_dir = repo_root / ".git" / "hooks"
        
        # Create hook scripts
        _install_pre_commit_hook(hooks_dir)
        _install_post_commit_hook(hooks_dir)
        
        typer.echo("✅ PromptOps git hooks installed successfully!")
        typer.echo("📝 Hooks will now automatically version your prompts on commit.")
        
    except Exception as e:
        typer.echo(f"❌ Failed to install hooks: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def uninstall():
    """Uninstall PromptOps git hooks."""
    
    try:
        repo_root = Path.cwd()
        while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        
        hooks_dir = repo_root / ".git" / "hooks"
        
        # Remove our hooks
        pre_commit = hooks_dir / "pre-commit"
        post_commit = hooks_dir / "post-commit"
        
        removed = []
        if pre_commit.exists() and _is_promptops_hook(pre_commit):
            pre_commit.unlink()
            removed.append("pre-commit")
        
        if post_commit.exists() and _is_promptops_hook(post_commit):
            post_commit.unlink()
            removed.append("post-commit")
        
        if removed:
            typer.echo(f"✅ Removed hooks: {', '.join(removed)}")
        else:
            typer.echo("ℹ️  No PromptOps hooks found to remove")
        
    except Exception as e:
        typer.echo(f"❌ Failed to uninstall hooks: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def status():
    """Check the status of PromptOps git hooks."""
    
    try:
        repo_root = Path.cwd()
        while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        
        hooks_dir = repo_root / ".git" / "hooks"
        
        typer.echo("🔍 PromptOps Git Hooks Status:")
        typer.echo("=" * 40)
        
        # Check pre-commit hook
        pre_commit = hooks_dir / "pre-commit"
        if pre_commit.exists():
            if _is_promptops_hook(pre_commit):
                typer.echo("✅ pre-commit: PromptOps hook installed")
            else:
                typer.echo("⚠️  pre-commit: Other hook installed (not PromptOps)")
        else:
            typer.echo("❌ pre-commit: Not installed")
        
        # Check post-commit hook
        post_commit = hooks_dir / "post-commit"
        if post_commit.exists():
            if _is_promptops_hook(post_commit):
                typer.echo("✅ post-commit: PromptOps hook installed")
            else:
                typer.echo("⚠️  post-commit: Other hook installed (not PromptOps)")
        else:
            typer.echo("❌ post-commit: Not installed")
        
        # Check configuration
        promptops_dir = repo_root / ".promptops"
        config_file = promptops_dir / "config.yaml"
        
        if config_file.exists():
            typer.echo("✅ config.yaml: Found")
        else:
            typer.echo("ℹ️  config.yaml: Using defaults")
        
    except Exception as e:
        typer.echo(f"❌ Failed to check status: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def configure():
    """Configure PromptOps hook behavior."""
    
    try:
        repo_root = Path.cwd()
        while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
            repo_root = repo_root.parent
        
        promptops_dir = repo_root / ".promptops"
        promptops_dir.mkdir(exist_ok=True)
        
        config_file = promptops_dir / "config.yaml"
        
        # Interactive configuration
        typer.echo("🔧 PromptOps Hook Configuration")
        typer.echo("=" * 40)
        
        verbose = typer.confirm("Enable verbose logging?", default=False)
        pre_commit_tests = typer.confirm("Run tests before commits?", default=False)
        block_on_failure = typer.confirm("Block commits if tests fail?", default=True)
        auto_tag = typer.confirm("Auto-create git tags for versions?", default=True)
        post_commit_tests = typer.confirm("Run tests after commits?", default=True)
        
        config_content = f"""# PromptOps Configuration
# This file controls git hook behavior

# Logging
verbose: {str(verbose).lower()}

# Pre-commit hook settings
pre_commit_tests: {str(pre_commit_tests).lower()}
block_on_test_failure: {str(block_on_failure).lower()}

# Post-commit hook settings  
auto_tag_versions: {str(auto_tag).lower()}
post_commit_tests: {str(post_commit_tests).lower()}

# Versioning rules
versioning:
  # Auto-increment rules by branch
  development:
    auto_increment: patch
    require_tests: false
  staging:
    auto_increment: minor
    require_tests: true
  main:
    auto_increment: major
    require_manual_approval: false
"""
        
        config_file.write_text(config_content)
        typer.echo(f"✅ Configuration saved to {config_file}")
        
    except Exception as e:
        typer.echo(f"❌ Failed to configure: {e}", err=True)
        raise typer.Exit(1)


def _hook_interpreter() -> str:
    """The interpreter written into the hook's shebang: this one.

    Whoever runs ``hooks install`` is, by construction, running a Python that
    can import PromptOps, so the hook is bound to it. Through v0.6.0 the
    shebang was ``#!/usr/bin/env python3``, which resolved to whatever PATH
    held at commit time; when that was a different interpreter the hook went
    searching the repository for a ``src/llmhq_promptops`` to import instead
    (CWE-427). Binding removes both the search and the mismatch.

    ``sys.executable`` is deliberately not resolved through symlinks: inside
    a venv it is the venv's own ``bin/python``, and following it would land
    on the base interpreter and lose the venv's site-packages.

    A path containing whitespace cannot be a shebang (the kernel splits on
    it), so that case, and an empty ``sys.executable`` (embedded
    interpreters), fall back to PATH resolution with a warning.
    """
    exe = sys.executable
    if exe and os.path.isabs(exe) and not any(ch.isspace() for ch in exe):
        return exe
    typer.echo(
        "⚠️  Cannot bind the hooks to this interpreter "
        f"({exe or 'unknown path'}); they will resolve 'python3' from PATH at "
        "commit time. Make sure that Python can import llmhq_promptops.",
        err=True,
    )
    return "/usr/bin/env python3"


_HOOK_HEADER = '''\
#!__INTERPRETER__
# PromptOps __NAME__ hook
#
# Installed by `promptops hooks install` and bound to the interpreter on the
# first line: PromptOps is imported from there and from nowhere else. Releases
# before 0.6.1 resolved python3 from PATH and, when it could not import
# PromptOps, searched the repository being committed to for a
# src/llmhq_promptops package and imported whatever they found. Repository
# content is not a trusted place to load code from on every commit.
#
# If this interpreter goes away (a rebuilt venv, say), re-run
# `promptops hooks install` from the environment you commit from.
# `promptops doctor` reports a hook whose interpreter cannot import PromptOps.
import sys
'''

_PRE_COMMIT_BODY = '''

def find_promptops():
    """Import PromptOps from this interpreter, or say exactly why that failed."""
    try:
        import llmhq_promptops
    except ImportError as exc:
        print("❌ PromptOps installation not found!", file=sys.stderr)
        print(f"   interpreter: {sys.executable}", file=sys.stderr)
        print(f"   reason:      {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        print("To fix this issue:", file=sys.stderr)
        print("  1. Install PromptOps into that interpreter: pip install llmhq-promptops", file=sys.stderr)
        print("  2. Or reinstall the hooks from the environment you commit from: promptops hooks install", file=sys.stderr)
        print("  3. Or remove the hooks: promptops hooks uninstall", file=sys.stderr)
        sys.exit(1)
    return llmhq_promptops.__file__


promptops_path = find_promptops()
print(f"[promptops] Using installation at: {promptops_path}", file=sys.stderr)

try:
    from llmhq_promptops.hooks.pre_commit import main
    main()
except Exception as e:
    print(f"❌ PromptOps pre-commit hook failed: {e}", file=sys.stderr)
    print("Run 'promptops hooks status' to verify installation", file=sys.stderr)
    sys.exit(1)
'''

_POST_COMMIT_BODY = '''

def find_promptops():
    """Import PromptOps from this interpreter; None, with a warning, if it cannot."""
    try:
        import llmhq_promptops
    except ImportError as exc:
        # The commit has already happened. Tagging and reports are
        # best-effort, so a missing install is reported, not fatal.
        print("⚠️  PromptOps installation not found for post-commit hook", file=sys.stderr)
        print(f"   interpreter: {sys.executable}", file=sys.stderr)
        print(f"   reason:      {exc}", file=sys.stderr)
        print("Post-commit features (tagging, reports) will be skipped.", file=sys.stderr)
        print("Reinstall from the environment you commit from: promptops hooks install", file=sys.stderr)
        return None
    return llmhq_promptops.__file__


promptops_path = find_promptops()
if promptops_path:
    print(f"[promptops] Using installation at: {promptops_path}", file=sys.stderr)
    try:
        from llmhq_promptops.hooks.post_commit import main
        main()
    except Exception as e:
        print(f"⚠️  PromptOps post-commit hook failed: {e}", file=sys.stderr)
        print("Continuing without post-commit processing", file=sys.stderr)
else:
    print("[promptops] Skipping post-commit hook - PromptOps not found", file=sys.stderr)
'''


def _render_hook(name: str, body: str) -> str:
    header = (
        _HOOK_HEADER
        .replace("__INTERPRETER__", _hook_interpreter())
        .replace("__NAME__", name)
    )
    return header + body


def _write_hook(hook_file: Path, content: str) -> None:
    """Back up a foreign hook, write ours, make it executable, sanity-check it."""
    try:
        if hook_file.exists() and not _is_promptops_hook(hook_file):
            backup_file = hook_file.with_name(hook_file.name + ".backup")
            hook_file.rename(backup_file)
            typer.echo(f"📦 Backed up existing {hook_file.name} hook to {backup_file}")
    except FileNotFoundError:
        pass  # File was removed between check and rename

    hook_file.write_text(content)

    # Make executable
    current_mode = hook_file.stat().st_mode
    hook_file.chmod(current_mode | stat.S_IEXEC)

    if not _test_hook_installation(hook_file):
        typer.echo("⚠️  Hook installed but failed validation test", err=True)


def _install_pre_commit_hook(hooks_dir: Path):
    """Install the pre-commit hook, bound to the current interpreter."""
    _write_hook(hooks_dir / "pre-commit", _render_hook("pre-commit", _PRE_COMMIT_BODY))


def _install_post_commit_hook(hooks_dir: Path):
    """Install the post-commit hook, bound to the current interpreter."""
    _write_hook(hooks_dir / "post-commit", _render_hook("post-commit", _POST_COMMIT_BODY))


def _is_promptops_hook(hook_file: Path) -> bool:
    """Check if a hook file is a PromptOps hook."""
    try:
        content = hook_file.read_text()
        return "PromptOps" in content and ("pre-commit hook" in content or "post-commit hook" in content)
    except Exception:
        return False


def _test_hook_installation(hook_file: Path) -> bool:
    """Test if a hook can be executed successfully."""
    try:
        import ast
        # Validate the hook is syntactically valid Python
        content = hook_file.read_text()
        ast.parse(content)
        # Check it contains the expected PromptOps markers
        return "PromptOps" in content and "find_promptops" in content
    except SyntaxError:
        return False
    except Exception:
        return False