"""Tests for the rewritten ``promptops test diff`` (v0.5.0).

Before v0.5.0 this command printed two 500-char truncated content blobs, which
could not be reviewed. It now prints a real unified diff plus a semver impact
verdict derived from the variable signature.

Exit codes borrow git's ``--exit-code`` *flag* but not git's *numbers*:
``git diff`` uses 1 for "differences found", while we reserve 1 for command
failure because there are three severities to encode.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


BASE_YAML = """\
metadata:
  id: greeting
  description: Greeting prompt
  models:
    default: gpt-4-turbo
template: |
  Hello, {{ name }}!
variables:
  name:
    type: string
    required: true
"""


def _yaml(body: str, variables: str, models: str = "    default: gpt-4-turbo\n") -> str:
    return (
        "metadata:\n"
        "  id: greeting\n"
        "  description: Greeting prompt\n"
        "  models:\n" + models + "template: |\n"
        + "".join(f"  {line}\n" for line in body.splitlines())
        + "variables:\n" + variables
    )


REQUIRED_NAME = "  name:\n    type: string\n    required: true\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Repo with greeting.yaml committed at BASE_YAML."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts = tmp_path / ".promptops" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "greeting.yaml").write_text(BASE_YAML)

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


def _edit(repo: Path, yaml_text: str) -> None:
    """Change the working tree copy, leaving HEAD alone."""
    (repo / ".promptops" / "prompts" / "greeting.yaml").write_text(yaml_text)


def _run(repo: Path, monkeypatch, *args: str):
    monkeypatch.chdir(repo)
    return CliRunner().invoke(app, ["test", "diff", "greeting", *args])


# ── unified diff output ─────────────────────────────────────────────


class TestUnifiedDiffOutput:
    def test_prints_a_real_unified_diff(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))

        result = _run(repo, monkeypatch)

        assert "---" in result.output
        assert "+++" in result.output
        assert "@@" in result.output
        assert "-  Hello, {{ name }}!" in result.output
        assert "+  Hi there, {{ name }}!" in result.output

    def test_identical_versions_say_so(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch)
        assert "identical" in result.output.lower()
        assert result.exit_code == 0

    def test_no_color_env_strips_ansi(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))
        monkeypatch.setenv("NO_COLOR", "1")

        result = _run(repo, monkeypatch)

        assert ANSI_RE.search(result.output) is None


# ── impact banner ───────────────────────────────────────────────────


class TestImpactBanner:
    def test_major_when_required_variable_added(self, repo: Path, monkeypatch):
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }} of {{ tier }}!",
                REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
            ),
        )

        result = _run(repo, monkeypatch)

        assert "MAJOR" in result.output
        assert "tier" in result.output

    def test_minor_when_optional_variable_added(self, repo: Path, monkeypatch):
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }}!",
                REQUIRED_NAME + "  nickname:\n    type: string\n    required: false\n",
            ),
        )

        result = _run(repo, monkeypatch)

        assert "MINOR" in result.output

    def test_patch_when_only_prose_changes(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))

        result = _run(repo, monkeypatch)

        assert "PATCH" in result.output


# ── exit codes ──────────────────────────────────────────────────────


class TestExitCodes:
    def test_default_exits_zero_on_major(self, repo: Path, monkeypatch):
        """Backwards compatible: without the flag, 0 means 'ran fine'."""
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }} of {{ tier }}!",
                REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
            ),
        )

        result = _run(repo, monkeypatch)

        assert result.exit_code == 0

    def test_default_prints_note_when_impact_is_major(self, repo: Path, monkeypatch):
        """The silent-failure guard: someone who forgot the flag is told."""
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }} of {{ tier }}!",
                REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
            ),
        )

        result = _run(repo, monkeypatch)

        assert "--exit-code" in result.output

    def test_no_note_when_impact_is_patch(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))

        result = _run(repo, monkeypatch)

        assert "--exit-code" not in result.output

    def test_exit_code_flag_returns_3_on_major(self, repo: Path, monkeypatch):
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }} of {{ tier }}!",
                REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
            ),
        )

        result = _run(repo, monkeypatch, "--exit-code")

        assert result.exit_code == 3

    def test_exit_code_flag_returns_2_on_minor(self, repo: Path, monkeypatch):
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }}!",
                REQUIRED_NAME + "  nickname:\n    type: string\n    required: false\n",
            ),
        )

        result = _run(repo, monkeypatch, "--exit-code")

        assert result.exit_code == 2

    def test_exit_code_flag_returns_0_on_patch(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))

        result = _run(repo, monkeypatch, "--exit-code")

        assert result.exit_code == 0

    def test_exit_code_flag_returns_0_when_identical(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "--exit-code")
        assert result.exit_code == 0

    def test_failure_is_1_even_with_exit_code_flag(self, repo: Path, monkeypatch):
        """1 stays reserved for 'the command failed', never a severity."""
        monkeypatch.chdir(repo)
        result = CliRunner().invoke(
            app, ["test", "diff", "no-such-prompt", "--exit-code"]
        )
        assert result.exit_code == 1


# ── json ────────────────────────────────────────────────────────────


class TestJsonOutput:
    def test_json_shape(self, repo: Path, monkeypatch):
        _edit(
            repo,
            _yaml(
                "Hello, {{ name }} of {{ tier }}!",
                REQUIRED_NAME + "  tier:\n    type: string\n    required: true\n",
            ),
        )

        result = _run(repo, monkeypatch, "--json")

        data = json.loads(result.output)
        assert data["prompt"] == "greeting"
        assert data["impact"] == "major"
        assert data["identical"] is False
        assert isinstance(data["changes"], list)
        assert any("tier" in c["detail"] for c in data["changes"])
        assert isinstance(data["diff"], str)

    def test_json_is_parseable_when_identical(self, repo: Path, monkeypatch):
        result = _run(repo, monkeypatch, "--json")
        data = json.loads(result.output)
        assert data["impact"] == "none"
        assert data["identical"] is True

    def test_json_emits_no_ansi(self, repo: Path, monkeypatch):
        _edit(repo, _yaml("Hi there, {{ name }}!", REQUIRED_NAME))
        result = _run(repo, monkeypatch, "--json")
        assert ANSI_RE.search(result.output) is None
