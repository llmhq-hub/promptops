"""Tests for ``core/health.py`` and ``promptops doctor`` (v0.6.0, TODO-S4).

`doctor` answers "is this setup sane" in one command, instead of making
someone remember which of six separate things to check by hand.

Contract: OK and WARN both exit 0, FAIL exits 1. WARN is for "this is a
choice you may have made deliberately" (hooks not installed, no deploys yet);
FAIL is for "this is broken" (no .promptops/, unparseable config).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmhq_promptops.core.deploys import DeployEvent, DeployLog
from llmhq_promptops.core.health import CheckStatus, run_all_checks
from cli.main import app


PROMPT_YAML = """\
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def healthy_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts = tmp_path / ".promptops" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "greeting.yaml").write_text(PROMPT_YAML)
    (tmp_path / ".promptops" / "config.yaml").write_text("logging:\n  level: INFO\n")

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


def _status_of(checks, name_fragment: str) -> CheckStatus:
    for check in checks:
        if name_fragment in check.name:
            return check.status
    raise AssertionError(
        f"no check named like {name_fragment!r} in {[c.name for c in checks]}"
    )


def _run(repo: Path, monkeypatch, *args: str):
    monkeypatch.chdir(repo)
    return CliRunner().invoke(app, ["doctor", *args])


# ── the check registry ──────────────────────────────────────────────


class TestCheckRegistry:
    def test_runs_exactly_six_checks(self, healthy_repo: Path):
        assert len(run_all_checks(str(healthy_repo))) == 6

    def test_healthy_repo_has_no_failures(self, healthy_repo: Path):
        checks = run_all_checks(str(healthy_repo))
        assert all(c.status is not CheckStatus.FAIL for c in checks)

    def test_every_check_has_a_name_and_message(self, healthy_repo: Path):
        for check in run_all_checks(str(healthy_repo)):
            assert check.name
            assert check.message

    def test_non_promptops_directory_fails_structure(self, tmp_path: Path):
        checks = run_all_checks(str(tmp_path))
        assert _status_of(checks, "structure") is CheckStatus.FAIL


class TestIndividualChecks:
    def test_hooks_warn_when_not_installed(self, healthy_repo: Path):
        """v0.4.0 made hooks opt-in, so absent hooks are a choice, not a bug."""
        assert _status_of(run_all_checks(str(healthy_repo)), "hooks") is (
            CheckStatus.WARN
        )

    def test_snapshot_warns_when_absent(self, healthy_repo: Path):
        assert _status_of(run_all_checks(str(healthy_repo)), "snapshot") is (
            CheckStatus.WARN
        )

    def test_snapshot_ok_when_fresh(self, healthy_repo: Path):
        from llmhq_promptops import write_snapshot

        write_snapshot(str(healthy_repo))
        assert _status_of(run_all_checks(str(healthy_repo)), "snapshot") is (
            CheckStatus.OK
        )

    def test_snapshot_warns_when_stale(self, healthy_repo: Path):
        from llmhq_promptops import write_snapshot

        write_snapshot(str(healthy_repo))
        (healthy_repo / "unrelated.txt").write_text("moved on")
        _git(healthy_repo, "add", ".")
        _git(healthy_repo, "commit", "--quiet", "-m", "later commit")

        checks = run_all_checks(str(healthy_repo))
        assert _status_of(checks, "snapshot") is CheckStatus.WARN
        assert any(
            "stale" in c.message.lower() for c in checks if "snapshot" in c.name
        )

    def test_deploy_log_warns_when_absent(self, healthy_repo: Path):
        assert _status_of(run_all_checks(str(healthy_repo)), "deploy") is (
            CheckStatus.WARN
        )

    def test_deploy_log_ok_with_events(self, healthy_repo: Path):
        DeployLog(str(healthy_repo)).append(
            DeployEvent(
                timestamp=datetime.now(timezone.utc),
                env="prod",
                commit=_git(healthy_repo, "rev-parse", "HEAD"),
                deployed_by="ci",
            )
        )
        assert _status_of(run_all_checks(str(healthy_repo)), "deploy") is (
            CheckStatus.OK
        )

    def test_deploy_log_fails_on_malformed_lines(self, healthy_repo: Path):
        log_path = healthy_repo / ".promptops" / "deploys.jsonl"
        log_path.write_text("this is not json\n")

        checks = run_all_checks(str(healthy_repo))
        assert _status_of(checks, "deploy") is CheckStatus.FAIL

    def test_resolver_check_names_the_chosen_backend(self, healthy_repo: Path):
        checks = run_all_checks(str(healthy_repo))
        resolver = next(c for c in checks if "resolver" in c.name)
        assert "git" in resolver.message.lower()

    def test_resolver_reports_snapshot_mode_when_snapshot_present(
        self, healthy_repo: Path
    ):
        from llmhq_promptops import write_snapshot

        write_snapshot(str(healthy_repo))
        checks = run_all_checks(str(healthy_repo))
        resolver = next(c for c in checks if "resolver" in c.name)
        assert "snapshot" in resolver.message.lower()

    def test_versions_check_ok_for_committed_prompt(self, healthy_repo: Path):
        assert _status_of(run_all_checks(str(healthy_repo)), "version") is not (
            CheckStatus.FAIL
        )

    def test_versions_check_warns_for_uncommitted_prompt(
        self, healthy_repo: Path
    ):
        (healthy_repo / ".promptops" / "prompts" / "ghost.yaml").write_text(
            PROMPT_YAML
        )
        checks = run_all_checks(str(healthy_repo))
        assert _status_of(checks, "version") is CheckStatus.WARN
        assert any("ghost" in c.message for c in checks if "version" in c.name)


# ── CLI ─────────────────────────────────────────────────────────────


class TestDoctorCLI:
    def test_healthy_repo_exits_zero(self, healthy_repo: Path, monkeypatch):
        result = _run(healthy_repo, monkeypatch)
        assert result.exit_code == 0

    def test_warnings_still_exit_zero(self, healthy_repo: Path, monkeypatch):
        """WARN means 'a choice you may have made', not 'broken'."""
        result = _run(healthy_repo, monkeypatch)
        assert "WARN" in result.output
        assert result.exit_code == 0

    def test_failure_exits_one(self, tmp_path: Path, monkeypatch):
        result = _run(tmp_path, monkeypatch)
        assert result.exit_code == 1

    def test_output_lists_every_check(self, healthy_repo: Path, monkeypatch):
        result = _run(healthy_repo, monkeypatch)
        for check in run_all_checks(str(healthy_repo)):
            assert check.name in result.output

    def test_json_shape(self, healthy_repo: Path, monkeypatch):
        result = _run(healthy_repo, monkeypatch, "--json")

        data = json.loads(result.output)
        assert data["healthy"] is True
        assert len(data["checks"]) == 6
        assert {"name", "status", "message", "hint"} <= set(
            data["checks"][0].keys()
        )

    def test_json_reports_unhealthy_on_failure(self, tmp_path: Path, monkeypatch):
        result = _run(tmp_path, monkeypatch, "--json")
        assert json.loads(result.output)["healthy"] is False
