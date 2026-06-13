"""Tests for ``promptops render prompt`` (B6, v0.4.0).

Before v0.4.0, render read ``prompt_data["prompt"]["template"]`` — the
legacy ``prompt:`` schema only — and crashed with a raw KeyError on the
``metadata:`` schema the README documents. It now routes through
PromptTemplate, which handles both schemas and renders in a sandbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands.render import app as render_app


runner = CliRunner()

META_SCHEMA = """\
metadata:
  id: greet
  version: "1.0.0"
template: "Hello {{ name }}!"
variables:
  name:
    type: string
    required: true
"""

LEGACY_SCHEMA = """\
prompt:
  id: greet
  description: test
  template: "Hi {{ name }}"
variables:
  name:
    type: string
    required: true
"""


def _write(d: Path, name: str, content: str) -> Path:
    p = d / name
    p.write_text(content)
    return p


class TestRenderBothSchemas:
    def test_metadata_schema_renders(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "p.yaml", META_SCHEMA)
        _write(tmp_path, "v.yaml", "name: World\n")
        result = runner.invoke(render_app, ["p.yaml", "--vars-file", "v.yaml"])
        assert result.exit_code == 0, result.output
        assert "Hello World!" in result.output

    def test_legacy_schema_renders(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "p.yaml", LEGACY_SCHEMA)
        _write(tmp_path, "v.yaml", "name: World\n")
        result = runner.invoke(render_app, ["p.yaml", "--vars-file", "v.yaml"])
        assert result.exit_code == 0, result.output
        assert "Hi World" in result.output

    def test_malformed_file_errors_cleanly(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "p.yaml", "this: is: not: valid: prompt\n")
        result = runner.invoke(render_app, ["p.yaml"])
        assert result.exit_code == 1
        # Clean error message, not a raw traceback
        assert "Error" in result.output
        assert "Traceback" not in result.output
