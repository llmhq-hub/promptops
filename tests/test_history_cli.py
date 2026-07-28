"""Tests for ``promptops history <prompt-id>`` (v0.6.0, TODO-S3).

The timeline answers "what has this prompt been, and what actually shipped".
Version history comes from git; deploy correlation comes from
``.promptops/deploys.jsonl``.

A deploy event records the *repo* commit, not the commit that last touched
this prompt. So a deploy is attributed to the newest prompt version whose
commit landed at or before the deploy: the version that was actually live at
that moment. This is the same semantic ``promptops blame --at`` uses.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmhq_promptops.core.deploys import DeployEvent, DeployLog
from cli.main import app


PROMPT_V1 = """\
metadata:
  id: greeting
  description: Greeting prompt
template: |
  Hello, {{ name }}!
variables:
  name:
    type: string
    required: true
"""

PROMPT_V2 = """\
metadata:
  id: greeting
  description: Greeting prompt
template: |
  Howdy, {{ name }}!
variables:
  name:
    type: string
    required: true
"""


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    full_env = None
    if env:
        import os

        full_env = {**os.environ, **env}
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        env=full_env,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """greeting.yaml with two commits, backdated so ordering is deterministic."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "alice@example.com")
    _git(tmp_path, "config", "user.name", "Alice")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts = tmp_path / ".promptops" / "prompts"
    prompts.mkdir(parents=True)

    (prompts / "greeting.yaml").write_text(PROMPT_V1)
    _git(tmp_path, "add", ".")
    _git(
        tmp_path, "commit", "--quiet", "-m", "feat: initial greeting",
        env={
            "GIT_AUTHOR_DATE": "2026-05-01T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-05-01T10:00:00+00:00",
        },
    )

    (prompts / "greeting.yaml").write_text(PROMPT_V2)
    _git(tmp_path, "add", ".")
    _git(
        tmp_path, "commit", "--quiet", "-m", "feat: warmer greeting",
        env={
            "GIT_AUTHOR_DATE": "2026-05-10T10:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-05-10T10:00:00+00:00",
        },
    )

    return tmp_path


def _add_deploy(repo: Path, when: datetime, env: str) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    DeployLog(str(repo)).append(
        DeployEvent(timestamp=when, env=env, commit=head, deployed_by="ci")
    )


def _run(repo: Path, monkeypatch, *args: str):
    monkeypatch.chdir(repo)
    return CliRunner().invoke(app, ["history", *args])


# ── version timeline ────────────────────────────────────────────────


class TestVersionTimeline:
    def test_lists_every_version(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "greeting")
        assert result.exit_code == 0
        assert "initial greeting" in result.output
        assert "warmer greeting" in result.output

    def test_newest_version_first(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "greeting")
        assert result.output.index("warmer greeting") < result.output.index(
            "initial greeting"
        )

    def test_shows_short_commit_and_author(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "greeting")
        head_short = _git(repo, "rev-parse", "--short=8", "HEAD")
        assert head_short in result.output
        assert "Alice" in result.output

    def test_limit_caps_the_number_of_versions(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "greeting", "--limit", "1")
        assert "warmer greeting" in result.output
        assert "initial greeting" not in result.output


# ── deploy correlation ──────────────────────────────────────────────


class TestDeployCorrelation:
    def test_no_deploy_log_still_lists_versions(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "greeting")
        assert result.exit_code == 0
        assert "warmer greeting" in result.output

    def test_deploy_marker_appears(self, repo: Path, monkeypatch):
        _add_deploy(repo, datetime(2026, 5, 12, tzinfo=timezone.utc), "prod")
        result = _run(repo, monkeypatch, "greeting")
        assert "prod" in result.output

    def test_deploy_attributed_to_version_live_at_that_time(
        self, repo: Path, monkeypatch
    ):
        """A deploy on May 12 shipped the May 10 version, not the May 1 one."""
        _add_deploy(repo, datetime(2026, 5, 12, tzinfo=timezone.utc), "prod")
        result = _run(repo, monkeypatch, "greeting", "--json")

        data = json.loads(result.output)
        by_msg = {v["message"]: v for v in data["versions"]}
        assert len(by_msg["feat: warmer greeting"]["deploys"]) == 1
        assert by_msg["feat: initial greeting"]["deploys"] == []

    def test_deploy_before_any_version_is_not_attributed(
        self, repo: Path, monkeypatch
    ):
        _add_deploy(repo, datetime(2026, 4, 1, tzinfo=timezone.utc), "prod")
        result = _run(repo, monkeypatch, "greeting", "--json")

        data = json.loads(result.output)
        assert all(v["deploys"] == [] for v in data["versions"])

    def test_env_filter_excludes_other_environments(
        self, repo: Path, monkeypatch
    ):
        _add_deploy(repo, datetime(2026, 5, 12, tzinfo=timezone.utc), "prod")
        _add_deploy(
            repo, datetime(2026, 5, 13, tzinfo=timezone.utc), "staging"
        )

        result = _run(repo, monkeypatch, "greeting", "--env", "prod", "--json")

        data = json.loads(result.output)
        envs = {d["env"] for v in data["versions"] for d in v["deploys"]}
        assert envs == {"prod"}


# ── errors ──────────────────────────────────────────────────────────


class TestUnknownPrompt:
    def test_unknown_prompt_raises_e003_not_an_empty_timeline(
        self, repo: Path, monkeypatch
    ):
        """The bug this command must not have: a cheerful empty timeline.

        get_prompt_versions returns [] for anything it cannot find, so a typo
        would otherwise render as 'this prompt has no history' rather than
        'this prompt does not exist'.
        """
        result = _run(repo, monkeypatch, "no-such-prompt")

        assert result.exit_code == 1
        assert "PROMPTOPS_E003" in result.output

    def test_error_names_available_prompts(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "no-such-prompt")
        assert "greeting" in result.output


# ── json ────────────────────────────────────────────────────────────


class TestJsonOutput:
    def test_json_shape(self, repo: Path, monkeypatch):
        _add_deploy(repo, datetime(2026, 5, 12, tzinfo=timezone.utc), "prod")
        result = _run(repo, monkeypatch, "greeting", "--json")

        data = json.loads(result.output)
        assert data["prompt"] == "greeting"
        assert len(data["versions"]) == 2

        newest = data["versions"][0]
        assert {"version", "commit", "commit_short", "author", "date",
                "message", "deploys"} <= set(newest.keys())
        assert {"env", "timestamp", "deployed_by"} <= set(
            newest["deploys"][0].keys()
        )
