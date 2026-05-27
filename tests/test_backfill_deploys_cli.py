"""Tests for ``promptops backfill-deploys --from-git-log`` (Phase 1.5a M5b).

Walks git log, finds commits matching a pattern, and creates DeployEvent
records for each — the escape hatch for repos that started recording
deploys mid-stream.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.backfill_deploys import app as backfill_app
from llmhq_promptops import DeployLog


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo_with_history(tmp_path: Path) -> Path:
    """A git repo with 5 commits, 3 of which are tagged as deploys."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "alice@example.com")
    _git(tmp_path, "config", "user.name", "Alice")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    # 5 commits, two with [deploy] prefix, one with [release:], two plain
    (tmp_path / "README.md").write_text("init\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "[deploy] initial release")

    (tmp_path / "README.md").write_text("update 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "wip: not a deploy")

    (tmp_path / "README.md").write_text("update 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "[deploy] v0.2.0")

    (tmp_path / "README.md").write_text("update 3\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "refactor: internal change")

    (tmp_path / "README.md").write_text("update 4\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "[release: 1.0] another flavor")

    return tmp_path


@pytest.fixture
def cd_into(monkeypatch):
    def _cd(path: Path) -> None:
        monkeypatch.chdir(path)
    return _cd


runner = CliRunner()


# ── --from-git-log gate ─────────────────────────────────────────────


class TestRequiresFromGitLog:
    def test_without_from_git_log_errors(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)
        result = runner.invoke(backfill_app, [])
        assert result.exit_code != 0
        assert "--from-git-log" in result.output


# ── happy path: default [deploy] pattern ────────────────────────────


class TestBackfillFromGitLog:
    def test_creates_one_event_per_matching_commit(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        result = runner.invoke(backfill_app, ["--from-git-log"])
        assert result.exit_code == 0, result.output

        events = DeployLog(str(repo_with_history)).all_events()
        assert len(events) == 2  # the two [deploy] commits
        for e in events:
            assert e.env == "prod"
            assert e.metadata.get("backfilled") == "true"
            assert e.metadata.get("source") == "git-log"
            assert e.timestamp.tzinfo is not None
            assert e.deployed_by == "Alice"

    def test_events_are_chronological_oldest_first(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        result = runner.invoke(backfill_app, ["--from-git-log"])
        assert result.exit_code == 0
        events = DeployLog(str(repo_with_history)).all_events()
        assert events[0].timestamp <= events[1].timestamp

    def test_summary_reports_created_count(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        result = runner.invoke(backfill_app, ["--from-git-log"])
        assert result.exit_code == 0
        assert "2 events created" in result.output


# ── --dry-run ───────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_writes_no_events(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)
        result = runner.invoke(backfill_app, ["--from-git-log", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "would be created" in result.output

        log_path = repo_with_history / ".promptops" / "deploys.jsonl"
        assert not log_path.exists(), "dry-run must not create the log file"


# ── idempotency ─────────────────────────────────────────────────────


class TestIdempotency:
    def test_rerunning_skips_existing_events(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        first = runner.invoke(backfill_app, ["--from-git-log"])
        assert first.exit_code == 0
        first_count = len(DeployLog(str(repo_with_history)).all_events())

        second = runner.invoke(backfill_app, ["--from-git-log"])
        assert second.exit_code == 0
        assert "skipped" in second.output
        assert second.output.count("[SKIP]") >= 2

        second_count = len(DeployLog(str(repo_with_history)).all_events())
        assert second_count == first_count

    def test_different_env_creates_new_events_for_same_commits(
        self, repo_with_history: Path, cd_into
    ):
        """(commit, env) is the dedupe key; same commits in two envs both record."""
        cd_into(repo_with_history)
        assert runner.invoke(
            backfill_app, ["--from-git-log", "--env", "prod"]
        ).exit_code == 0
        assert runner.invoke(
            backfill_app, ["--from-git-log", "--env", "staging"]
        ).exit_code == 0

        events = DeployLog(str(repo_with_history)).all_events()
        assert len(events) == 4
        prod_events = [e for e in events if e.env == "prod"]
        staging_events = [e for e in events if e.env == "staging"]
        assert len(prod_events) == 2 and len(staging_events) == 2


# ── --pattern ──────────────────────────────────────────────────────


class TestCustomPattern:
    def test_custom_pattern_matches_only_intended_commits(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        result = runner.invoke(
            backfill_app,
            ["--from-git-log", "--pattern", r"^\[release:"],
        )
        assert result.exit_code == 0
        events = DeployLog(str(repo_with_history)).all_events()
        # Only the one '[release:' commit matches
        assert len(events) == 1

    def test_invalid_regex_errors(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)
        result = runner.invoke(
            backfill_app, ["--from-git-log", "--pattern", "[unclosed"]
        )
        assert result.exit_code != 0
        assert "not a valid regex" in result.output

    def test_zero_matches_reports_nothing(self, repo_with_history: Path, cd_into):
        cd_into(repo_with_history)
        result = runner.invoke(
            backfill_app, ["--from-git-log", "--pattern", "^never-matches"]
        )
        assert result.exit_code == 0
        assert "Nothing to backfill" in result.output


# ── --env ──────────────────────────────────────────────────────────


class TestEnvOverride:
    def test_env_override_recorded_on_events(
        self, repo_with_history: Path, cd_into
    ):
        cd_into(repo_with_history)
        result = runner.invoke(
            backfill_app, ["--from-git-log", "--env", "canary"]
        )
        assert result.exit_code == 0
        events = DeployLog(str(repo_with_history)).all_events()
        assert all(e.env == "canary" for e in events)


# ── error paths ─────────────────────────────────────────────────────


class TestNonGitRepo:
    def test_non_git_directory_errors(self, tmp_path: Path, cd_into):
        cd_into(tmp_path)
        result = runner.invoke(backfill_app, ["--from-git-log"])
        assert result.exit_code != 0
        assert "not a git repository" in result.output
