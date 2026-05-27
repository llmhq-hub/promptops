"""Tests for the ``promptops migrate tag-history`` CLI (Phase 1.5a M2b).

The command walks each prompt's commit history and creates per-prompt
tags of the form ``prompt-<id>-v<X>.<Y>.<Z>``, oldest commit first. This
gives users a real, immutable version string in place of the
``commit-<sha>`` fallback introduced by M2.

Tests use ``typer.testing.CliRunner`` against the migrate Typer app
directly. The CLI internally calls ``GitVersioning(".")``, so each test
``chdir``s into an isolated tmp_path git repo to stay deterministic.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.migrate import app as migrate_app
from llmhq_promptops.core.git_versioning import GitVersioning


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt for tests
  id: hello
  model: gpt-4-turbo
  template: 'Hello, {{ name }}!'
variables:
  name:
    type: string
    required: true
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo_with_history(tmp_path: Path) -> Path:
    """Isolated git repo with three commits on .promptops/prompts/hello.yaml."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts_dir = tmp_path / ".promptops" / "prompts"
    prompts_dir.mkdir(parents=True)

    hello = prompts_dir / "hello.yaml"
    hello.write_text(SAMPLE_PROMPT_YAML)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial: hello prompt")

    hello.write_text(SAMPLE_PROMPT_YAML.replace("Hello", "Hi"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "edit: switch to 'Hi'")

    hello.write_text(SAMPLE_PROMPT_YAML.replace("Hello, {{ name }}!", "Hey, {{ name }}!"))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "edit: switch to 'Hey'")

    return tmp_path


@pytest.fixture
def cd_into(monkeypatch):
    """Helper that returns a closure to ``chdir`` into a path inside a test."""
    def _cd(path: Path) -> None:
        monkeypatch.chdir(path)
    return _cd


runner = CliRunner()


# ── Happy path ──────────────────────────────────────────────────────


class TestTagHistoryHappyPath:
    def test_single_prompt_creates_tag_per_commit_oldest_first(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)

        result = runner.invoke(migrate_app, ["tag-history", "--prompt", "hello"])
        assert result.exit_code == 0, result.output

        tags = _git(repo_with_history, "tag").splitlines()
        assert "prompt-hello-v0.1.0" in tags
        assert "prompt-hello-v0.1.1" in tags
        assert "prompt-hello-v0.1.2" in tags
        # Exactly 3 commits → exactly 3 tags
        assert sum(1 for t in tags if t.startswith("prompt-hello-")) == 3

    def test_dry_run_creates_no_tags(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)

        result = runner.invoke(
            migrate_app, ["tag-history", "--prompt", "hello", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "[DRY ]" in result.output

        tags = _git(repo_with_history, "tag").splitlines()
        assert not any(t.startswith("prompt-hello-") for t in tags), (
            f"--dry-run must not create tags, but found: {tags!r}"
        )

    def test_custom_start_version_is_respected(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)

        result = runner.invoke(
            migrate_app,
            ["tag-history", "--prompt", "hello", "--start-version", "v2.0.0"],
        )
        assert result.exit_code == 0

        tags = _git(repo_with_history, "tag").splitlines()
        assert "prompt-hello-v2.0.0" in tags
        assert "prompt-hello-v2.0.1" in tags
        assert "prompt-hello-v2.0.2" in tags

    def test_start_version_without_v_prefix_is_accepted(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)

        result = runner.invoke(
            migrate_app,
            ["tag-history", "--prompt", "hello", "--start-version", "0.5.0"],
        )
        assert result.exit_code == 0
        tags = _git(repo_with_history, "tag").splitlines()
        assert "prompt-hello-v0.5.0" in tags


# ── Idempotency ─────────────────────────────────────────────────────


class TestIdempotency:
    def test_rerunning_skips_existing_tags(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)

        first = runner.invoke(migrate_app, ["tag-history", "--prompt", "hello"])
        assert first.exit_code == 0

        second = runner.invoke(migrate_app, ["tag-history", "--prompt", "hello"])
        assert second.exit_code == 0
        assert "skipped" in second.output
        # All three should be reported as skipped on the second run
        assert second.output.count("[SKIP]") >= 3

        # Tag set has not changed
        tags = _git(repo_with_history, "tag").splitlines()
        assert sum(1 for t in tags if t.startswith("prompt-hello-")) == 3


# ── All-prompts mode ────────────────────────────────────────────────


class TestAllPromptsMode:
    def test_no_prompt_arg_tags_every_prompt(
        self, repo_with_history: Path, cd_into
    ):
        # Add a second prompt with one commit
        goodbye = repo_with_history / ".promptops" / "prompts" / "goodbye.yaml"
        goodbye.write_text(
            SAMPLE_PROMPT_YAML.replace("hello", "goodbye").replace("Hello", "Goodbye")
        )
        _git(repo_with_history, "add", ".")
        _git(repo_with_history, "commit", "--quiet", "-m", "add goodbye")

        cd_into(repo_with_history)

        result = runner.invoke(migrate_app, ["tag-history"])
        assert result.exit_code == 0, result.output

        tags = _git(repo_with_history, "tag").splitlines()
        assert any(t.startswith("prompt-hello-") for t in tags)
        assert any(t.startswith("prompt-goodbye-") for t in tags)


# ── Error paths ─────────────────────────────────────────────────────


class TestErrorPaths:
    def test_invalid_start_version_errors(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)

        result = runner.invoke(
            migrate_app,
            ["tag-history", "--prompt", "hello", "--start-version", "not-a-version"],
        )
        assert result.exit_code != 0
        assert "Invalid version" in result.output

    def test_invalid_prompt_id_errors(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)

        result = runner.invoke(
            migrate_app, ["tag-history", "--prompt", "../../etc/passwd"]
        )
        assert result.exit_code != 0

    def test_non_git_directory_errors(self, tmp_path: Path, cd_into):
        cd_into(tmp_path)

        result = runner.invoke(migrate_app, ["tag-history"])
        assert result.exit_code != 0

    def test_no_prompts_in_promptops_dir_errors(
        self, repo_with_history: Path, cd_into
    ):
        # Remove the prompt file (and commit) — leave an empty prompts dir
        (repo_with_history / ".promptops" / "prompts" / "hello.yaml").unlink()
        cd_into(repo_with_history)

        result = runner.invoke(migrate_app, ["tag-history"])
        assert result.exit_code != 0
        assert "No prompts found" in result.output


# ── Integration with GitVersioning ──────────────────────────────────


class TestEndToEndWithGitVersioning:
    """After tagging, get_latest_version returns the real version, not commit-<sha>."""

    def test_tagged_history_replaces_commit_sha_fallback(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)

        gv_before = GitVersioning(str(repo_with_history))
        pre = gv_before.get_latest_version("hello")
        assert pre is not None and pre.startswith("commit-"), pre

        # Run the migration
        result = runner.invoke(
            migrate_app,
            ["tag-history", "--prompt", "hello", "--start-version", "v0.1.0"],
        )
        assert result.exit_code == 0, result.output

        # Fresh GitVersioning to avoid cache from the prior call
        gv_after = GitVersioning(str(repo_with_history))
        post = gv_after.get_latest_version("hello")
        # Latest commit (highest patch) is v0.1.2 because three commits → 0, 1, 2
        assert post == "v0.1.2", (
            f"After tagging, get_latest_version should return the tag, got {post!r}"
        )
