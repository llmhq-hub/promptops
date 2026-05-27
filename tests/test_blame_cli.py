"""Tests for ``promptops blame --at <ts>`` (Phase 1.5a M5).

The hero command for incident archaeology. Composes ``DeployLog.find_at``
with ``AutoResolver.resolve`` to answer "what was deployed when?".
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.blame import app as blame_app, _parse_timestamp
from llmhq_promptops import DeployEvent, DeployLog


UTC = timezone.utc


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt
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
def repo_with_deploy(tmp_path: Path) -> tuple[Path, DeployEvent]:
    """A git repo with one prompt + one recorded deploy event at HEAD."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "hello.yaml").write_text(SAMPLE_PROMPT_YAML)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial: hello prompt")

    head_sha = _git(tmp_path, "rev-parse", "HEAD")
    event = DeployEvent(
        timestamp=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
        env="prod",
        commit=head_sha,
        deployed_by="alice",
        metadata={"release": "v1.0.0"},
    )
    DeployLog(str(tmp_path)).append(event)
    return tmp_path, event


@pytest.fixture
def cd_into(monkeypatch):
    def _cd(path: Path) -> None:
        monkeypatch.chdir(path)
    return _cd


runner = CliRunner()


# ── _parse_timestamp ────────────────────────────────────────────────


class TestParseTimestamp:
    def test_now_alias(self):
        ts = _parse_timestamp("now")
        assert ts.tzinfo is not None
        assert (datetime.now(UTC) - ts).total_seconds() < 5

    def test_iso_z_suffix(self):
        ts = _parse_timestamp("2026-05-26T14:00:00Z")
        assert ts.tzinfo is not None
        assert ts.year == 2026 and ts.hour == 14
        assert ts.utcoffset() == timedelta(0)

    def test_iso_offset(self):
        ts = _parse_timestamp("2026-05-26T14:00:00+02:00")
        assert ts.tzinfo is not None
        assert ts.hour == 14

    def test_bare_date_treated_as_utc_midnight(self):
        ts = _parse_timestamp("2026-05-26")
        assert ts.year == 2026 and ts.month == 5 and ts.day == 26
        assert ts.hour == 0
        # Bare date is naive; the parser assumes UTC
        assert ts.tzinfo is not None

    def test_invalid_timestamp_raises(self):
        with pytest.raises(Exception):
            _parse_timestamp("not a date")


# ── happy path ──────────────────────────────────────────────────────


class TestBlameHappyPath:
    def test_finds_deploy_and_lists_prompts(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        # Query at exactly the deploy timestamp
        result = runner.invoke(
            blame_app, ["--at", event.timestamp.isoformat()]
        )
        assert result.exit_code == 0, result.output

        assert "Blame: env=prod" in result.output
        assert "Deploy event:" in result.output
        assert event.commit[:8] in result.output
        assert "alice" in result.output
        assert "release=v1.0.0" in result.output
        assert "Resolved prompts" in result.output
        assert "hello" in result.output

    def test_query_after_deploy_still_finds_it(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        future = (event.timestamp + timedelta(hours=24)).isoformat()
        result = runner.invoke(blame_app, ["--at", future])
        assert result.exit_code == 0
        assert event.commit[:8] in result.output

    def test_prompt_filter_shows_full_text(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        result = runner.invoke(
            blame_app,
            ["--at", event.timestamp.isoformat(), "--prompt", "hello"],
        )
        assert result.exit_code == 0
        assert "Resolved prompt 'hello'" in result.output
        # Full YAML is printed in --prompt mode
        assert "Hello, {{ name }}!" in result.output

    def test_now_alias_works(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, _ = repo_with_deploy
        cd_into(repo)

        result = runner.invoke(blame_app, ["--at", "now"])
        assert result.exit_code == 0
        # "now" is after the recorded deploy → finds it
        assert "Deploy event:" in result.output


# ── error paths ─────────────────────────────────────────────────────


class TestBlameErrors:
    def test_no_deploy_log_errors_with_helpful_message(
        self, tmp_path: Path, cd_into
    ):
        # A git repo but no deploys.jsonl
        _git(tmp_path, "init", "--quiet")
        _git(tmp_path, "config", "user.email", "x@y")
        _git(tmp_path, "config", "user.name", "X")
        _git(tmp_path, "config", "commit.gpgsign", "false")
        (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
        (tmp_path / "README.md").write_text("x\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "init")

        cd_into(tmp_path)
        result = runner.invoke(blame_app, ["--at", "2026-05-26T00:00:00Z"])
        assert result.exit_code != 0
        assert "deploy event" in result.output.lower()
        assert "backfill-deploys" in result.output

    def test_timestamp_before_any_deploy_errors(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        past = (event.timestamp - timedelta(days=1)).isoformat()
        result = runner.invoke(blame_app, ["--at", past])
        assert result.exit_code != 0
        assert "no deploy events" in result.output.lower()

    def test_wrong_env_filter_errors(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        result = runner.invoke(
            blame_app,
            ["--at", event.timestamp.isoformat(), "--env", "staging"],
        )
        assert result.exit_code != 0
        assert "env='staging'" in result.output or "env=staging" in result.output.lower()

    def test_invalid_prompt_id_rejected(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)

        result = runner.invoke(
            blame_app,
            ["--at", event.timestamp.isoformat(), "--prompt", "../../etc/passwd"],
        )
        assert result.exit_code != 0

    def test_missing_at_flag_errors(self, repo_with_deploy, cd_into):
        repo, _ = repo_with_deploy
        cd_into(repo)
        result = runner.invoke(blame_app, [])
        assert result.exit_code != 0
        assert "at" in result.output.lower()

    def test_unknown_prompt_at_commit_in_filter_mode(
        self, repo_with_deploy: tuple[Path, DeployEvent], cd_into
    ):
        repo, event = repo_with_deploy
        cd_into(repo)
        result = runner.invoke(
            blame_app,
            ["--at", event.timestamp.isoformat(), "--prompt", "nonexistent-prompt"],
        )
        assert result.exit_code != 0
