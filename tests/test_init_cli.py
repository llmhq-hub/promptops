"""Tests for ``promptops init repo`` (D9, v0.4.0).

The v0.4.0 behavior change: init creates the directory structure + default
config ONLY. It never modifies ``.git/hooks/`` unless ``--with-hooks`` is
passed explicitly. Installing hooks is a deliberate second step via
``promptops hooks install``.

Rationale (from the DX review): ``init`` is the first command every new
user runs. Silently writing into ``.git/hooks/`` on first contact is a
trust violation for exactly the architect persona the tool targets.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app


runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestInitDefaultIsHookless:
    """The D9 contract: default init never touches .git/hooks/."""

    def test_default_init_does_not_install_hooks(self, git_repo: Path):
        result = runner.invoke(app, ["init", "repo"])
        assert result.exit_code == 0, result.output

        pre_commit = git_repo / ".git" / "hooks" / "pre-commit"
        post_commit = git_repo / ".git" / "hooks" / "post-commit"
        assert not pre_commit.exists(), (
            "init must not write .git/hooks/pre-commit by default (D9)"
        )
        assert not post_commit.exists(), (
            "init must not write .git/hooks/post-commit by default (D9)"
        )

    def test_default_init_creates_directory_structure(self, git_repo: Path):
        result = runner.invoke(app, ["init", "repo"])
        assert result.exit_code == 0, result.output
        assert (git_repo / ".promptops" / "prompts").is_dir()
        assert (git_repo / ".promptops" / "configs").is_dir()

    def test_default_init_creates_config(self, git_repo: Path):
        result = runner.invoke(app, ["init", "repo"])
        assert result.exit_code == 0, result.output
        config = git_repo / ".promptops" / "config.yaml"
        assert config.exists(), "init should create a default config.yaml"
        assert "auto_tag_versions" in config.read_text()

    def test_default_init_points_at_hooks_install(self, git_repo: Path):
        result = runner.invoke(app, ["init", "repo"])
        assert "promptops hooks install" in result.output
        assert "opt-in" in result.output

    def test_rerunning_init_preserves_existing_config(self, git_repo: Path):
        runner.invoke(app, ["init", "repo"])
        config = git_repo / ".promptops" / "config.yaml"
        config.write_text("# customized by user\nverbose: true\n")

        result = runner.invoke(app, ["init", "repo"])
        assert result.exit_code == 0, result.output
        assert config.read_text() == "# customized by user\nverbose: true\n", (
            "re-running init must not clobber an existing config.yaml"
        )


class TestInitWithHooksOptIn:
    """--with-hooks restores the old behavior, explicitly."""

    def test_with_hooks_non_interactive_installs_hooks(self, git_repo: Path):
        result = runner.invoke(
            app, ["init", "repo", "--with-hooks", "--non-interactive"]
        )
        assert result.exit_code == 0, result.output

        pre_commit = git_repo / ".git" / "hooks" / "pre-commit"
        post_commit = git_repo / ".git" / "hooks" / "post-commit"
        assert pre_commit.exists(), "--with-hooks must install pre-commit"
        assert post_commit.exists(), "--with-hooks must install post-commit"

    def test_explicit_no_hooks_flag_still_accepted(self, git_repo: Path):
        """--no-hooks (the pre-v0.4.0 opt-out spelling) keeps working."""
        result = runner.invoke(app, ["init", "repo", "--no-hooks"])
        assert result.exit_code == 0, result.output
        assert not (git_repo / ".git" / "hooks" / "pre-commit").exists()


class TestInitOutsideGitRepo:
    def test_init_outside_git_repo_fails_cleanly(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "repo"])
        assert result.exit_code == 1
        assert "git init" in result.output
