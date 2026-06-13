"""Tests for ``promptops create prompt`` (B5, v0.4.0).

v0.4.0 made prompt_id a positional argument and made --template-file
optional (scaffolds a starter template when omitted), so the README's
`promptops create prompt user-onboarding` works as written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from cli.commands.create import app as create_app
from llmhq_promptops.core.template import PromptTemplate


runner = CliRunner()


class TestCreatePositionalScaffold:
    def test_positional_id_scaffolds_renderable_file(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(create_app, ["user-onboarding"])
        assert result.exit_code == 0, result.output

        out = tmp_path / ".promptops" / "prompts" / "user-onboarding.yaml"
        assert out.exists()
        data = yaml.safe_load(out.read_text())
        assert data["prompt"]["id"] == "user-onboarding"

        # The scaffolded file parses and its auto-detected variable renders.
        tmpl = PromptTemplate(out.read_text())
        rendered = tmpl.render({"user_input": "hi there"})
        assert "hi there" in rendered

    def test_points_at_correct_test_command(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(create_app, ["greet"])
        assert "promptops test runtest --prompt greet:unstaged" in result.output

    def test_template_file_option_still_works(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tpl.j2").write_text("Custom {{ thing }}")
        result = runner.invoke(
            create_app, ["custom", "--template-file", "tpl.j2"]
        )
        assert result.exit_code == 0, result.output
        out = tmp_path / ".promptops" / "prompts" / "custom.yaml"
        assert "Custom {{ thing }}" in out.read_text()

    def test_duplicate_without_force_errors(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(create_app, ["dup"])
        result = runner.invoke(create_app, ["dup"])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_force_overwrites(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(create_app, ["dup"])
        result = runner.invoke(create_app, ["dup", "--force"])
        assert result.exit_code == 0, result.output

    def test_invalid_id_rejected(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(create_app, ["../escape"])
        assert result.exit_code == 1
        assert "Error" in result.output
