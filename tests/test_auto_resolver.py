"""Tests for ``AutoResolver`` (Phase 1.5a M3).

AutoResolver picks SnapshotResolver vs GitResolver at construction time:
- prefer='auto' (default): snapshot if present, else git, else error.
- prefer='snapshot': require snapshot, else error.
- prefer='git': require git, else error.

The chosen backend is exposed via ``self.mode`` ('snapshot' | 'git') and
``resolve()`` delegates to the inner resolver verbatim.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmhq_promptops import (
    AutoResolver,
    GitResolver,
    ResolvedPrompt,
    SnapshotResolver,
    write_snapshot,
)


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt for AutoResolver tests
  id: hello
  model: gpt-4-turbo
  template: 'Hello, {{ name }}!'
variables:
  name:
    type: string
    required: true
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def git_only_repo(tmp_path: Path) -> Path:
    """A git repo with one prompt committed. No snapshot.json."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "hello.yaml").write_text(
        SAMPLE_PROMPT_YAML
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


@pytest.fixture
def repo_with_snapshot(git_only_repo: Path) -> Path:
    """git_only_repo with a snapshot.json also present."""
    write_snapshot(str(git_only_repo))
    return git_only_repo


@pytest.fixture
def snapshot_only_dir(repo_with_snapshot: Path, tmp_path: Path) -> Path:
    """A directory with snapshot.json but no .git/. Simulates a Docker image."""
    import shutil

    target = tmp_path / "container_root"
    target.mkdir()
    shutil.copytree(repo_with_snapshot / ".promptops", target / ".promptops")
    # Deliberately do NOT copy .git/
    assert not (target / ".git").exists()
    return target


# ── prefer='auto' ───────────────────────────────────────────────────


class TestAutoModeDetection:
    def test_snapshot_present_picks_snapshot(self, repo_with_snapshot: Path):
        ar = AutoResolver(repo_path=str(repo_with_snapshot))
        assert ar.mode == "snapshot"
        assert isinstance(ar._inner, SnapshotResolver)

    def test_no_snapshot_falls_back_to_git(self, git_only_repo: Path):
        ar = AutoResolver(repo_path=str(git_only_repo))
        assert ar.mode == "git"
        assert isinstance(ar._inner, GitResolver)

    def test_snapshot_only_works_without_git(self, snapshot_only_dir: Path):
        """The production-runtime case: Docker image with no .git/."""
        ar = AutoResolver(repo_path=str(snapshot_only_dir))
        assert ar.mode == "snapshot"

    def test_neither_backend_available_errors(self, tmp_path: Path):
        with pytest.raises(ValueError, match="could not detect"):
            AutoResolver(repo_path=str(tmp_path))


# ── prefer='snapshot' ───────────────────────────────────────────────


class TestPreferSnapshot:
    def test_explicit_snapshot_mode(self, repo_with_snapshot: Path):
        ar = AutoResolver(repo_path=str(repo_with_snapshot), prefer="snapshot")
        assert ar.mode == "snapshot"

    def test_missing_snapshot_errors_with_helpful_message(
        self, git_only_repo: Path
    ):
        with pytest.raises(ValueError, match="snapshot build"):
            AutoResolver(repo_path=str(git_only_repo), prefer="snapshot")


# ── prefer='git' ────────────────────────────────────────────────────


class TestPreferGit:
    def test_explicit_git_mode_even_when_snapshot_present(
        self, repo_with_snapshot: Path
    ):
        """Snapshot exists but caller explicitly requested git — git wins."""
        ar = AutoResolver(repo_path=str(repo_with_snapshot), prefer="git")
        assert ar.mode == "git"
        assert isinstance(ar._inner, GitResolver)

    def test_missing_git_errors_with_helpful_message(self, snapshot_only_dir: Path):
        with pytest.raises(ValueError, match="not a git repository"):
            AutoResolver(repo_path=str(snapshot_only_dir), prefer="git")


# ── prefer validation ───────────────────────────────────────────────


class TestPreferValidation:
    def test_invalid_prefer_value_rejected(self, git_only_repo: Path):
        with pytest.raises(ValueError, match="prefer="):
            AutoResolver(repo_path=str(git_only_repo), prefer="badvalue")


# ── Delegation ──────────────────────────────────────────────────────


class TestDelegation:
    def test_resolve_through_snapshot_backend(self, repo_with_snapshot: Path):
        ar = AutoResolver(repo_path=str(repo_with_snapshot), prefer="snapshot")
        r = ar.resolve("hello")
        assert isinstance(r, ResolvedPrompt)
        assert r.source == "snapshot"
        assert r.prompt_id == "hello"

    def test_resolve_through_git_backend(self, git_only_repo: Path):
        ar = AutoResolver(repo_path=str(git_only_repo))
        r = ar.resolve("hello", "working")
        assert r.source == "git"
        assert r.prompt_id == "hello"

    def test_unknown_prompt_propagates_from_inner(self, repo_with_snapshot: Path):
        ar = AutoResolver(repo_path=str(repo_with_snapshot))
        with pytest.raises(ValueError, match="not found"):
            ar.resolve("nonexistent")


# ── PromptManager integration ───────────────────────────────────────


class TestPromptManagerWithAutoResolver:
    """The README-recommended production pattern actually works end-to-end."""

    def test_manager_with_auto_resolver_returns_string(
        self, snapshot_only_dir: Path
    ):
        from llmhq_promptops import PromptManager

        manager = PromptManager(
            str(snapshot_only_dir),
            resolver=AutoResolver(repo_path=str(snapshot_only_dir)),
        )
        rendered = manager.get_prompt("hello", {"name": "World"})
        assert "World" in rendered

    def test_manager_with_auto_resolver_returns_resolved_prompt(
        self, snapshot_only_dir: Path
    ):
        from llmhq_promptops import PromptManager

        manager = PromptManager(
            str(snapshot_only_dir),
            resolver=AutoResolver(repo_path=str(snapshot_only_dir)),
        )
        resolved = manager.resolve("hello")
        assert resolved.source == "snapshot"
        assert resolved.prompt_id == "hello"
