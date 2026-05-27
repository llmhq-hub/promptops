"""Tests for ``promptops deploy event`` and ``promptops deploy list`` (M4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.deploy import app as deploy_app
from llmhq_promptops import DeployLog


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit so HEAD resolves."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "alice@example.com")
    _git(tmp_path, "config", "user.name", "Alice Engineer")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "README.md").write_text("# test\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


@pytest.fixture
def cd_into(monkeypatch):
    def _cd(path: Path) -> None:
        monkeypatch.chdir(path)
    return _cd


runner = CliRunner()


# ── deploy event ────────────────────────────────────────────────────


class TestDeployEvent:
    def test_appends_event_with_defaults_from_git(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        head = _git(git_repo, "rev-parse", "HEAD")

        result = runner.invoke(deploy_app, ["event", "--env", "prod"])
        assert result.exit_code == 0, result.output

        log = DeployLog(str(git_repo))
        events = log.all_events()
        assert len(events) == 1
        assert events[0].env == "prod"
        assert events[0].commit == head
        assert events[0].deployed_by == "Alice Engineer"
        assert events[0].metadata == {}

    def test_explicit_commit_is_recorded(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(
            deploy_app, ["event", "--env", "staging", "--commit", "deadbeef"]
        )
        assert result.exit_code == 0
        events = DeployLog(str(git_repo)).all_events()
        assert events[0].commit == "deadbeef"

    def test_explicit_by_is_recorded(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(
            deploy_app, ["event", "--env", "prod", "--by", "ci-bot"]
        )
        assert result.exit_code == 0
        assert DeployLog(str(git_repo)).all_events()[0].deployed_by == "ci-bot"

    def test_metadata_flags_are_parsed(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(
            deploy_app,
            ["event", "--env", "prod", "-m", "release=v1.2.3", "-m", "ticket=PROMPT-42"],
        )
        assert result.exit_code == 0
        meta = DeployLog(str(git_repo)).all_events()[0].metadata
        assert meta == {"release": "v1.2.3", "ticket": "PROMPT-42"}

    def test_malformed_metadata_errors(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(
            deploy_app, ["event", "--env", "prod", "-m", "no-equals-sign"]
        )
        assert result.exit_code != 0
        assert "key=value" in result.output

    def test_missing_env_errors(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(deploy_app, ["event"])
        assert result.exit_code != 0
        # typer surfaces a "Missing option" error for required flags
        assert "env" in result.output.lower()

    def test_two_events_in_a_row_both_recorded(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        assert runner.invoke(deploy_app, ["event", "--env", "staging"]).exit_code == 0
        assert runner.invoke(deploy_app, ["event", "--env", "prod"]).exit_code == 0
        events = DeployLog(str(git_repo)).all_events()
        assert [e.env for e in events] == ["staging", "prod"]

    def test_writes_one_line_per_event_with_trailing_newline(
        self, git_repo: Path, cd_into
    ):
        cd_into(git_repo)
        runner.invoke(deploy_app, ["event", "--env", "prod"])
        runner.invoke(deploy_app, ["event", "--env", "prod"])
        content = (git_repo / ".promptops" / "deploys.jsonl").read_text()
        assert content.count("\n") == 2
        # Each line is valid JSON on its own
        for line in content.strip().split("\n"):
            json.loads(line)


# ── deploy list ─────────────────────────────────────────────────────


class TestDeployList:
    def test_empty_log_shows_helpful_message(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        result = runner.invoke(deploy_app, ["list"])
        assert result.exit_code == 0
        assert "No deploys.jsonl" in result.output

    def test_lists_events_newest_first(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        runner.invoke(deploy_app, ["event", "--env", "dev"])
        runner.invoke(deploy_app, ["event", "--env", "staging"])
        runner.invoke(deploy_app, ["event", "--env", "prod"])

        result = runner.invoke(deploy_app, ["list"])
        assert result.exit_code == 0

        # Newest-first means 'prod' appears before 'staging' before 'dev'
        idx_prod = result.output.index("env=prod")
        idx_staging = result.output.index("env=staging")
        idx_dev = result.output.index("env=dev")
        assert idx_prod < idx_staging < idx_dev

    def test_env_filter(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        runner.invoke(deploy_app, ["event", "--env", "dev"])
        runner.invoke(deploy_app, ["event", "--env", "prod"])

        result = runner.invoke(deploy_app, ["list", "--env", "prod"])
        assert result.exit_code == 0
        assert "env=prod" in result.output
        assert "env=dev" not in result.output

    def test_env_filter_with_no_matches(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        runner.invoke(deploy_app, ["event", "--env", "dev"])

        result = runner.invoke(deploy_app, ["list", "--env", "prod"])
        assert result.exit_code == 0
        assert "No deploy events recorded" in result.output

    def test_limit_caps_output(self, git_repo: Path, cd_into):
        cd_into(git_repo)
        for _ in range(5):
            runner.invoke(deploy_app, ["event", "--env", "prod"])

        result = runner.invoke(deploy_app, ["list", "--limit", "2"])
        assert result.exit_code == 0
        # Two event lines (env= appears once per line)
        assert result.output.count("env=prod") == 2
