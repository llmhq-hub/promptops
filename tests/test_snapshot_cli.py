"""Tests for ``promptops snapshot build`` and ``promptops snapshot inspect`` (M3)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.snapshot import app as snapshot_app


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
def promptops_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "hello.yaml").write_text(SAMPLE_PROMPT_YAML)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


@pytest.fixture
def cd_into(monkeypatch):
    def _cd(path: Path) -> None:
        monkeypatch.chdir(path)
    return _cd


runner = CliRunner()


# ── snapshot build ──────────────────────────────────────────────────


class TestSnapshotBuild:
    def test_creates_default_snapshot_path(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        result = runner.invoke(snapshot_app, ["build"])
        assert result.exit_code == 0, result.output

        expected = promptops_repo / ".promptops" / "snapshot.json"
        assert expected.exists()
        assert "Wrote" in result.output

    def test_summarizes_prompt_count(self, promptops_repo: Path, cd_into):
        cd_into(promptops_repo)
        result = runner.invoke(snapshot_app, ["build"])
        assert "prompts=1" in result.output

    def test_custom_output_path(self, promptops_repo: Path, cd_into, tmp_path: Path):
        cd_into(promptops_repo)
        out = tmp_path / "custom.json"
        result = runner.invoke(snapshot_app, ["build", "--output", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_pretty_flag_produces_indented_json(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        result = runner.invoke(snapshot_app, ["build", "--pretty"])
        assert result.exit_code == 0
        content = (promptops_repo / ".promptops" / "snapshot.json").read_text()
        assert "\n  " in content  # indented lines

    def test_packed_default_has_no_indentation(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        result = runner.invoke(snapshot_app, ["build"])
        assert result.exit_code == 0
        content = (promptops_repo / ".promptops" / "snapshot.json").read_text()
        # First line should already contain a prompt entry — no pretty whitespace
        first_line = content.split("\n", 1)[0]
        assert "schema_version" in first_line
        assert "prompts" in first_line

    def test_commit_flag_snapshots_specific_point(
        self, promptops_repo: Path, cd_into
    ):
        # Add a second commit changing the prompt
        cd_into(promptops_repo)
        (promptops_repo / ".promptops" / "prompts" / "hello.yaml").write_text(
            SAMPLE_PROMPT_YAML.replace("Hello", "Howdy")
        )
        _git(promptops_repo, "add", ".")
        _git(promptops_repo, "commit", "--quiet", "-m", "change greeting")
        old_sha = _git(promptops_repo, "rev-parse", "HEAD~1")

        result = runner.invoke(snapshot_app, ["build", "--commit", old_sha])
        assert result.exit_code == 0

        data = json.loads(
            (promptops_repo / ".promptops" / "snapshot.json").read_text()
        )
        # Older commit had "Hello", not "Howdy"
        assert "Hello, {{ name }}!" in data["prompts"]["hello"]["text"]
        assert "Howdy" not in data["prompts"]["hello"]["text"]

    def test_non_git_directory_errors(self, tmp_path: Path, cd_into):
        cd_into(tmp_path)
        # No .git/ exists in tmp_path
        result = runner.invoke(snapshot_app, ["build"])
        assert result.exit_code != 0
        assert "git" in result.output.lower()


# ── snapshot inspect ────────────────────────────────────────────────


class TestSnapshotInspect:
    def test_default_path_inspect_shows_summary(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        runner.invoke(snapshot_app, ["build"])

        result = runner.invoke(snapshot_app, ["inspect"])
        assert result.exit_code == 0
        assert "Snapshot:" in result.output
        assert "schema_version: 1" in result.output
        assert "Prompts (1):" in result.output
        assert "hello" in result.output

    def test_inspect_summary_omits_full_text_by_default(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        runner.invoke(snapshot_app, ["build"])

        result = runner.invoke(snapshot_app, ["inspect"])
        # Raw template text should NOT appear in the summary
        assert "Hello, {{ name }}!" not in result.output

    def test_inspect_with_detail_shows_full_text(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        runner.invoke(snapshot_app, ["build"])

        result = runner.invoke(snapshot_app, ["inspect", "--detail"])
        assert result.exit_code == 0
        assert "Hello, {{ name }}!" in result.output

    def test_inspect_missing_file_errors(self, tmp_path: Path, cd_into):
        cd_into(tmp_path)
        result = runner.invoke(snapshot_app, ["inspect"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_inspect_malformed_snapshot_errors(
        self, promptops_repo: Path, cd_into
    ):
        cd_into(promptops_repo)
        snap = promptops_repo / ".promptops" / "snapshot.json"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text("not json")

        result = runner.invoke(snapshot_app, ["inspect"])
        assert result.exit_code != 0
        assert "not valid JSON" in result.output

    def test_inspect_explicit_snapshot_path(
        self, promptops_repo: Path, cd_into, tmp_path: Path
    ):
        cd_into(promptops_repo)
        out = tmp_path / "alt.json"
        runner.invoke(snapshot_app, ["build", "--output", str(out)])

        result = runner.invoke(snapshot_app, ["inspect", "--snapshot", str(out)])
        assert result.exit_code == 0
        assert "hello" in result.output
