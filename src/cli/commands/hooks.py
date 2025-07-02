# cli/commands/hooks.py
import typer
import subprocess
import os
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


def _install_pre_commit_hook(hooks_dir: Path):
    """Install the pre-commit hook with improved error handling."""
    hook_file = hooks_dir / "pre-commit"
    
    # Check if hook already exists
    if hook_file.exists() and not _is_promptops_hook(hook_file):
        backup_file = hooks_dir / "pre-commit.backup"
        hook_file.rename(backup_file)
        typer.echo(f"📦 Backed up existing pre-commit hook to {backup_file}")
    
    # Create hook script with robust error handling
    hook_content = f"""#!/usr/bin/env python3
# PromptOps pre-commit hook
import sys
import os
from pathlib import Path

def find_promptops():
    '''Find promptops installation with clear error messages.'''
    
    # Method 1: Try pip installed package
    try:
        import llmhq_promptops
        return llmhq_promptops.__file__
    except ImportError:
        pass
    
    # Method 2: Try development installation
    repo_root = Path(__file__).parent.parent.parent
    dev_path = repo_root / "src" / "llmhq_promptops"
    
    if dev_path.exists() and (dev_path / "__init__.py").exists():
        sys.path.insert(0, str(repo_root / "src"))
        try:
            import llmhq_promptops
            return str(dev_path)
        except ImportError:
            pass
    
    # Method 3: Try relative to hook location
    hook_dir = Path(__file__).parent
    relative_paths = [
        hook_dir.parent.parent / "src" / "llmhq_promptops",
        hook_dir.parent.parent.parent / "src" / "llmhq_promptops"
    ]
    
    for path in relative_paths:
        if path.exists() and (path / "__init__.py").exists():
            sys.path.insert(0, str(path.parent))
            try:
                import llmhq_promptops
                return str(path)
            except ImportError:
                continue
    
    # Method 4: Try current working directory
    cwd_path = Path.cwd() / "src" / "llmhq_promptops"
    if cwd_path.exists():
        sys.path.insert(0, str(cwd_path.parent))
        try:
            import llmhq_promptops
            return str(cwd_path)
        except ImportError:
            pass
    
    # Clear error message with recovery steps
    print("❌ PromptOps installation not found!", file=sys.stderr)
    print("", file=sys.stderr)
    print("Searched locations:", file=sys.stderr)
    print("  • Python packages (pip install)", file=sys.stderr)
    print(f"  • Development: {{repo_root}}/src/", file=sys.stderr)
    print(f"  • Relative to hook: {{hook_dir}}/../src/", file=sys.stderr)
    print(f"  • Current directory: {{cwd}}/src/", file=sys.stderr)
    print("", file=sys.stderr)
    print("To fix this issue:", file=sys.stderr)
    print("1. Install promptops: pip install llmhq-promptops", file=sys.stderr)
    print("2. Or reinstall hooks: promptops hooks install", file=sys.stderr)
    print("3. Or run from project root directory", file=sys.stderr)
    sys.exit(1)

# Find and import promptops
promotops_path = find_promptops()
print(f"[promptops] Using installation at: {{promotops_path}}", file=sys.stderr)

try:
    from llmhq_promptops.hooks.pre_commit import main
    main()
except Exception as e:
    print(f"❌ PromptOps pre-commit hook failed: {{e}}", file=sys.stderr)
    print("Run 'promptops hooks status' to verify installation", file=sys.stderr)
    sys.exit(1)
"""
    
    hook_file.write_text(hook_content)
    
    # Make executable
    current_mode = hook_file.stat().st_mode
    hook_file.chmod(current_mode | stat.S_IEXEC)
    
    # Test the hook installation
    if not _test_hook_installation(hook_file):
        typer.echo("⚠️  Hook installed but failed validation test", err=True)


def _install_post_commit_hook(hooks_dir: Path):
    """Install the post-commit hook with improved error handling."""
    hook_file = hooks_dir / "post-commit"
    
    # Check if hook already exists
    if hook_file.exists() and not _is_promptops_hook(hook_file):
        backup_file = hooks_dir / "post-commit.backup"
        hook_file.rename(backup_file)
        typer.echo(f"📦 Backed up existing post-commit hook to {backup_file}")
    
    # Create hook script with same robust error handling as pre-commit
    hook_content = f"""#!/usr/bin/env python3
# PromptOps post-commit hook
import sys
import os
from pathlib import Path

def find_promptops():
    '''Find promptops installation with clear error messages.'''
    
    # Method 1: Try pip installed package
    try:
        import llmhq_promptops
        return llmhq_promptops.__file__
    except ImportError:
        pass
    
    # Method 2: Try development installation
    repo_root = Path(__file__).parent.parent.parent
    dev_path = repo_root / "src" / "llmhq_promptops"
    
    if dev_path.exists() and (dev_path / "__init__.py").exists():
        sys.path.insert(0, str(repo_root / "src"))
        try:
            import llmhq_promptops
            return str(dev_path)
        except ImportError:
            pass
    
    # Method 3: Try relative to hook location
    hook_dir = Path(__file__).parent
    relative_paths = [
        hook_dir.parent.parent / "src" / "llmhq_promptops",
        hook_dir.parent.parent.parent / "src" / "llmhq_promptops"
    ]
    
    for path in relative_paths:
        if path.exists() and (path / "__init__.py").exists():
            sys.path.insert(0, str(path.parent))
            try:
                import llmhq_promptops
                return str(path)
            except ImportError:
                continue
    
    # Method 4: Try current working directory
    cwd_path = Path.cwd() / "src" / "llmhq_promptops"
    if cwd_path.exists():
        sys.path.insert(0, str(cwd_path.parent))
        try:
            import llmhq_promptops
            return str(cwd_path)
        except ImportError:
            pass
    
    # Post-commit hooks are less critical, so just warn instead of failing
    print("⚠️  PromptOps installation not found for post-commit hook", file=sys.stderr)
    print("Post-commit features (tagging, reports) will be skipped", file=sys.stderr)
    return None

# Find and import promptops
promotops_path = find_promptops()
if promotops_path:
    print(f"[promptops] Using installation at: {{promotops_path}}", file=sys.stderr)
    try:
        from llmhq_promptops.hooks.post_commit import main
        main()
    except Exception as e:
        print(f"⚠️  PromptOps post-commit hook failed: {{e}}", file=sys.stderr)
        print("Continuing without post-commit processing", file=sys.stderr)
else:
    print("[promptops] Skipping post-commit hook - PromptOps not found", file=sys.stderr)
"""
    
    hook_file.write_text(hook_content)
    
    # Make executable
    current_mode = hook_file.stat().st_mode
    hook_file.chmod(current_mode | stat.S_IEXEC)
    
    # Test the hook installation
    if not _test_hook_installation(hook_file):
        typer.echo("⚠️  Hook installed but failed validation test", err=True)


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
        # Test basic execution (dry run)
        result = subprocess.run(
            ["python3", "-c", f"exec(open('{hook_file}').read().split('find_promptops()')[0] + 'find_promptops()')"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # If it doesn't crash finding promptops, it's probably OK
        return result.returncode == 0 or "PromptOps installation not found" in result.stderr
        
    except Exception:
        return False  # Assume it's broken if we can't test it