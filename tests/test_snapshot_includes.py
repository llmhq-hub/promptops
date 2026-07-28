"""Tests for the E012 Jinja include scan in ``core/snapshot.py`` (v0.6.0).

PromptOps renders templates in a Jinja2 ``SandboxedEnvironment`` with no file
loader, so ``{% include %}``, ``{% import %}``, ``{% from %}`` and
``{% extends %}`` can never work at runtime. Before this scan existed, a
template using one would snapshot silently and only fail later, at render
time, in production. ``promptops snapshot build`` now refuses to produce that
snapshot.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmhq_promptops import write_snapshot
from llmhq_promptops.core.errors import PromptOpsError
from llmhq_promptops.core.snapshot import find_unsupported_includes
from cli.main import app


PLAIN_PROMPT_YAML = """\
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


def _prompt_with_template(body: str) -> str:
    """A valid prompt YAML whose template block is ``body``."""
    return (
        "prompt:\n"
        "  description: Prompt under test\n"
        "  id: hello\n"
        "  model: gpt-4-turbo\n"
        "  template: |\n"
        + "".join(f"    {line}\n" for line in body.splitlines())
        + "variables:\n"
        "  name:\n"
        "    type: string\n"
        "    required: true\n"
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo_with(tmp_path: Path):
    """Factory: build a committed repo whose hello.yaml is the given YAML."""

    def _build(prompt_yaml: str) -> Path:
        _git(tmp_path, "init", "--quiet")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "Test User")
        _git(tmp_path, "config", "commit.gpgsign", "false")

        prompts = tmp_path / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "hello.yaml").write_text(prompt_yaml)

        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "initial")
        return tmp_path

    return _build


# ── the pure scanner ────────────────────────────────────────────────


class TestFindUnsupportedIncludes:
    @pytest.mark.parametrize(
        "tag",
        [
            '{% include "other.txt" %}',
            "{% import 'macros.j2' as m %}",
            "{% from 'macros.j2' import helper %}",
            '{% extends "base.j2" %}',
        ],
    )
    def test_detects_each_unsupported_tag(self, tag: str):
        findings = find_unsupported_includes(f"Hello.\n{tag}\nBye.")
        assert len(findings) == 1
        line, keyword = findings[0]
        assert line == 2
        assert keyword in {"include", "import", "from", "extends"}

    def test_detects_whitespace_control_variant(self):
        findings = find_unsupported_includes('a\n{%- include "x.txt" -%}\nb')
        assert [line for line, _ in findings] == [2]

    def test_reports_every_occurrence_with_correct_line_numbers(self):
        text = (
            'line one\n'
            '{% include "a.txt" %}\n'
            'line three\n'
            '{% extends "b.j2" %}\n'
        )
        assert [line for line, _ in find_unsupported_includes(text)] == [2, 4]

    def test_ignores_the_words_in_ordinary_prose(self):
        text = (
            "Please include the account tier in your summary.\n"
            "Do not import assumptions from earlier turns.\n"
            "This extends beyond the current scope.\n"
        )
        assert find_unsupported_includes(text) == []

    def test_ignores_tags_inside_a_jinja_comment(self):
        text = 'before\n{# {% include "x.txt" %} #}\nafter'
        assert find_unsupported_includes(text) == []

    def test_ignores_supported_control_tags(self):
        text = "{% if x %}a{% endif %}\n{% for i in xs %}{{ i }}{% endfor %}"
        assert find_unsupported_includes(text) == []

    def test_clean_template_yields_no_findings(self):
        assert find_unsupported_includes("Hello, {{ name }}!") == []


# ── write_snapshot enforcement ──────────────────────────────────────


class TestWriteSnapshotRejectsIncludes:
    def test_raises_e012_naming_prompt_and_line(self, repo_with):
        repo = repo_with(_prompt_with_template('Hi.\n{% include "x.txt" %}'))

        with pytest.raises(PromptOpsError) as exc:
            write_snapshot(str(repo))

        err = exc.value
        assert err.code == "PROMPTOPS_E012"
        assert "hello" in str(err)
        # the offending tag sits on line 7 of the YAML file
        assert "line 7" in str(err)
        assert err.hint

    def test_snapshot_file_is_not_written_on_rejection(self, repo_with):
        repo = repo_with(_prompt_with_template('{% include "x.txt" %}'))

        with pytest.raises(PromptOpsError):
            write_snapshot(str(repo))

        assert not (repo / ".promptops" / "snapshot.json").exists()

    def test_allow_includes_builds_anyway(self, repo_with):
        repo = repo_with(_prompt_with_template('Hi.\n{% include "x.txt" %}'))

        path = write_snapshot(str(repo), allow_includes=True)

        assert path.exists()

    def test_allow_includes_warns(self, repo_with, caplog):
        repo = repo_with(_prompt_with_template('{% include "x.txt" %}'))

        with caplog.at_level("WARNING"):
            write_snapshot(str(repo), allow_includes=True)

        assert "PROMPTOPS_E012" in caplog.text
        assert "hello" in caplog.text

    def test_clean_repo_still_builds(self, repo_with):
        repo = repo_with(PLAIN_PROMPT_YAML)
        assert write_snapshot(str(repo)).exists()


# ── CLI surface ─────────────────────────────────────────────────────


class TestSnapshotBuildCLI:
    def test_build_fails_with_e012(self, repo_with, monkeypatch):
        repo = repo_with(_prompt_with_template('{% include "x.txt" %}'))
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(app, ["snapshot", "build"])

        assert result.exit_code == 1
        assert "PROMPTOPS_E012" in result.output

    def test_build_succeeds_with_allow_includes_flag(self, repo_with, monkeypatch):
        repo = repo_with(_prompt_with_template('{% include "x.txt" %}'))
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(app, ["snapshot", "build", "--allow-includes"])

        assert result.exit_code == 0
        assert (repo / ".promptops" / "snapshot.json").exists()

    def test_allow_includes_warning_is_visible_to_the_user(
        self, repo_with, monkeypatch
    ):
        """A logger.warning alone is invisible: the CLI installs no handler.

        Someone who passes --allow-includes is producing a snapshot that will
        fail at render time. That must be stated on screen, not only to a
        logger nobody configured.
        """
        repo = repo_with(_prompt_with_template('{% include "x.txt" %}'))
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(app, ["snapshot", "build", "--allow-includes"])

        assert "PROMPTOPS_E012" in result.output
        assert "hello" in result.output

    def test_no_include_warning_when_prompts_are_clean(self, repo_with, monkeypatch):
        repo = repo_with(PLAIN_PROMPT_YAML)
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(app, ["snapshot", "build", "--allow-includes"])

        assert result.exit_code == 0
        assert "PROMPTOPS_E012" not in result.output
