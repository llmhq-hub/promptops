"""Polish fixes carried over from the v0.4.0 audit's P3 list (v0.5.0).

Four independent items, each small, each a rough edge a real user hits:

1. ``_is_git_repo`` caught only ``CalledProcessError``, so a missing git
   binary produced a raw traceback instead of the intended error message.
2. ``init`` created ``.promptops/`` in the CWD while ``_install_hooks``
   walked up to the git root, so running it from a subdirectory left
   prompts and hooks in different places and auto-versioning silently
   never fired.
3. ``blame``'s failure-reason line spent 18 of its 120 display characters
   on the ``[PROMPTOPS_E0XX] `` prefix.
4. ``history --limit`` truncated with no indication that it had.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.init import _is_git_repo
from llmhq_promptops.core.deploys import DeployEvent, DeployLog
from cli.main import app


PROMPT = """\
metadata:
  id: greeting
  description: Greeting
template: |
  Hello {{ name }}.
variables:
  name:
    type: string
    required: true
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(path: Path) -> Path:
    _git(path, "init", "--quiet")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "Dev")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("x\n")
    _git(path, "add", ".")
    _git(path, "commit", "--quiet", "-m", "init")
    return path


# ── 1. missing git binary ───────────────────────────────────────────


class TestIsGitRepoHandlesMissingGit:
    def test_missing_git_binary_returns_false_not_a_traceback(self, monkeypatch):
        """A machine without git should get the friendly message, not a stack trace."""

        def _no_git(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory: 'git'")

        monkeypatch.setattr(subprocess, "run", _no_git)
        assert _is_git_repo() is False

    def test_non_repo_still_returns_false(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _is_git_repo() is False

    def test_real_repo_returns_true(self, tmp_path: Path, monkeypatch):
        _init_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert _is_git_repo() is True


# ── 2. init from a subdirectory ─────────────────────────────────────


class TestInitFromSubdirectory:
    def test_promptops_dir_lands_at_the_repo_root(self, tmp_path: Path, monkeypatch):
        """Hooks can only live at the git root, so prompts must too.

        Otherwise the root pre-commit hook looks for .promptops/prompts/
        relative to itself, finds nothing, and versioning silently no-ops.
        """
        _init_repo(tmp_path)
        subdir = tmp_path / "services" / "api"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        result = CliRunner().invoke(app, ["init", "repo"])

        assert result.exit_code == 0
        assert (tmp_path / ".promptops" / "prompts").is_dir()
        assert not (subdir / ".promptops").exists()

    def test_it_says_where_it_wrote_when_that_is_not_here(
        self, tmp_path: Path, monkeypatch
    ):
        _init_repo(tmp_path)
        subdir = tmp_path / "services" / "api"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        result = CliRunner().invoke(app, ["init", "repo"])

        # Silently writing outside the CWD would be its own surprise.
        assert "repository root" in result.output.lower()

    def test_hooks_and_prompts_share_a_root(self, tmp_path: Path, monkeypatch):
        _init_repo(tmp_path)
        subdir = tmp_path / "deep" / "nested"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        CliRunner().invoke(app, ["init", "repo", "--with-hooks", "--non-interactive"])

        assert (tmp_path / ".promptops" / "prompts").is_dir()
        hook = tmp_path / ".git" / "hooks" / "pre-commit"
        assert hook.exists()
        # The hook's root is the same place the prompts went.
        assert (hook.parent.parent.parent / ".promptops").is_dir()

    def test_running_at_the_root_is_unchanged(self, tmp_path: Path, monkeypatch):
        _init_repo(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(app, ["init", "repo"])

        assert result.exit_code == 0
        assert (tmp_path / ".promptops" / "prompts").is_dir()
        # No confusing "wrote elsewhere" note when it wrote right here.
        assert "repository root" not in result.output.lower()


# ── 3. blame failure-reason width ───────────────────────────────────


class TestBlameFailureReasonWidth:
    def test_reason_is_not_eaten_by_the_error_code_prefix(
        self, tmp_path: Path, monkeypatch
    ):
        """Show [E003], not [PROMPTOPS_E003], so the message keeps its width."""
        _init_repo(tmp_path)
        prompts = tmp_path / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "feat: greeting")

        # Deploy at the FIRST commit, before greeting existed, so resolving
        # it there fails and lands in the failures list.
        first = _git(tmp_path, "rev-parse", "HEAD~1")
        DeployLog(str(tmp_path)).append(
            DeployEvent(
                timestamp=datetime.now(timezone.utc),
                env="prod",
                commit=first,
                deployed_by="ci",
            )
        )
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(app, ["blame", "--at", "now"])

        assert "could not be resolved" in result.output
        # The compact form is present and the verbose one is gone.
        assert "[PROMPTOPS_E" not in result.output.split("could not be resolved")[1]
        assert "[E0" in result.output.split("could not be resolved")[1]


# ── 4. history --limit indicator ────────────────────────────────────


class TestHistoryLimitIndicator:
    @pytest.fixture
    def repo_with_three_versions(self, tmp_path: Path) -> Path:
        _init_repo(tmp_path)
        prompts = tmp_path / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        for i in range(1, 4):
            (prompts / "greeting.yaml").write_text(
                PROMPT.replace("Hello {{ name }}.", f"Hello {{{{ name }}}} v{i}.")
            )
            _git(tmp_path, "add", ".")
            _git(tmp_path, "commit", "--quiet", "-m", f"feat: greeting v{i}")
        return tmp_path

    def test_says_how_many_were_hidden(
        self, repo_with_three_versions: Path, monkeypatch
    ):
        monkeypatch.chdir(repo_with_three_versions)

        result = CliRunner().invoke(app, ["history", "greeting", "--limit", "1"])

        assert "1 of 3" in result.output

    def test_no_indicator_when_nothing_was_truncated(
        self, repo_with_three_versions: Path, monkeypatch
    ):
        monkeypatch.chdir(repo_with_three_versions)

        result = CliRunner().invoke(app, ["history", "greeting", "--limit", "50"])

        assert "of 3" not in result.output

    def test_json_reports_the_totals(
        self, repo_with_three_versions: Path, monkeypatch
    ):
        import json

        monkeypatch.chdir(repo_with_three_versions)

        result = CliRunner().invoke(
            app, ["history", "greeting", "--limit", "1", "--json"]
        )

        data = json.loads(result.output)
        assert data["shown"] == 1
        assert data["total"] == 3
        assert len(data["versions"]) == 1
