"""Tests for the v0.4.0 Lane E PromptManager changes.

- P2.1: render/parse catch only expected exception families; foreign
  exceptions propagate with their real type.
- P2.2: ``get_prompt_diff`` raises ``PromptOpsError`` (E003) instead of
  returning an ``{"error": ...}`` dict.
- P2.8: working-tree versions bypass the template cache in git mode, so
  a disk edit is visible on the very next ``get_prompt`` call; snapshot
  mode keeps caching everything (frozen artifact).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmhq_promptops import PromptManager, PromptOpsError, write_snapshot
from llmhq_promptops.core.snapshot import AutoResolver


PROMPT_YAML = """\
prompt:
  description: Greeting prompt
  id: greet
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
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@t.io")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "greet.yaml").write_text(PROMPT_YAML)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


# ── P2.1: narrowed exception handling ───────────────────────────────


class TestNarrowedRenderExceptions:
    def test_missing_variable_still_becomes_e014(self, repo: Path):
        manager = PromptManager(str(repo))
        with pytest.raises(PromptOpsError) as exc:
            manager.get_prompt("greet")  # 'name' missing
        assert exc.value.code == "PROMPTOPS_E014"

    def test_foreign_exception_propagates_with_real_type(self, repo: Path):
        """A bug in user-passed objects must not be masked as E014."""

        class Bomb:
            def __str__(self):
                raise RuntimeError("user-object bug")

        manager = PromptManager(str(repo))
        with pytest.raises(RuntimeError, match="user-object bug"):
            manager.get_prompt("greet", {"name": Bomb()})

    def test_malformed_yaml_becomes_e015(self, repo: Path):
        bad = repo / ".promptops" / "prompts" / "broken.yaml"
        bad.write_text("prompt: [unclosed\n  template: oops\n")
        manager = PromptManager(str(repo))
        with pytest.raises(PromptOpsError) as exc:
            manager.get_template("broken", "unstaged")
        assert exc.value.code == "PROMPTOPS_E015"


# ── P2.2: get_prompt_diff raises ────────────────────────────────────


class TestDiffRaises:
    def test_missing_version_raises_e003(self, repo: Path):
        manager = PromptManager(str(repo))
        with pytest.raises(PromptOpsError) as exc:
            manager.get_prompt_diff("greet", "working", "v99.99.99")
        assert exc.value.code == "PROMPTOPS_E003"
        assert "v99.99.99" in exc.value.message

    def test_no_error_key_in_successful_diff(self, repo: Path):
        manager = PromptManager(str(repo))
        diff = manager.get_prompt_diff("greet", "working", "unstaged")
        assert "error" not in diff
        assert diff["identical"] is True


# ── P2.8: working-tree versions bypass the cache ────────────────────


class TestWorkingTreeCacheBypass:
    def test_disk_edit_visible_without_refresh_in_git_mode(self, repo: Path):
        """The dev WTF: edit a prompt, rerun, see the OLD text. Fixed."""
        manager = PromptManager(str(repo))
        first = manager.get_prompt("greet", {"name": "A"}, )
        assert "Hello" in first

        edited = PROMPT_YAML.replace("Hello, {{ name }}!", "Howdy, {{ name }}!")
        (repo / ".promptops" / "prompts" / "greet.yaml").write_text(edited)

        second = manager.get_prompt("greet", {"name": "A"})
        assert "Howdy" in second, (
            "working-tree edit must be visible on the next call without "
            "manager.refresh()"
        )

    def test_pinned_versions_still_cached(self, repo: Path):
        manager = PromptManager(str(repo))
        t1 = manager.get_template("greet", "working")
        t2 = manager.get_template("greet", "working")
        assert t1 is t2, "HEAD-alias versions stay cached (refresh() to clear)"

    def test_snapshot_mode_caches_default_version(self, repo: Path, tmp_path: Path):
        """Snapshot is frozen: version=None is cacheable there."""
        import shutil

        write_snapshot(str(repo))
        target = tmp_path / "container"
        target.mkdir()
        (target / ".promptops").mkdir()
        shutil.copy(
            repo / ".promptops" / "snapshot.json",
            target / ".promptops" / "snapshot.json",
        )

        manager = PromptManager(
            str(target), resolver=AutoResolver(repo_path=str(target))
        )
        t1 = manager.get_template("greet")
        t2 = manager.get_template("greet")
        assert t1 is t2, "snapshot-backed default version should hit the cache"
