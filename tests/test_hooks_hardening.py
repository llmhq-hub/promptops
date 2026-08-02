"""One validator, and a doctor check that can actually tell (v0.6.0).

Three loose ends from the hooks repair.

**A third copy of the validation.** ``post_commit`` got a real check in
v0.6.0, but ``pre_commit._run_prompt_tests`` still rendered with ``{}`` and so
still failed by construction on any prompt with a required variable. It is
opt-in (``pre_commit_tests`` defaults to False), which is the only reason it
was less visible, not less wrong. Same argument as the semver grader: two
implementations of one question drift. Both now call
``core/template.py::validate_prompt_text``.

**Doctor could not tell.** ``promptops doctor`` reported "PromptOps hooks
installed" for six releases while the hooks were dead, because it checked that
the *files* existed and never that they could run. The hook scripts begin
``#!/usr/bin/env python3``, so a hook installed under an interpreter that has
no PromptOps on its path fails on every commit while doctor calls it healthy.
That is a real and common setup: install PromptOps in a venv, install the
hooks, then commit from a shell where the venv is not active.

A green check that cannot go red is the same failure as a test that cannot
fail, and this release exists because of a whole family of those.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from llmhq_promptops.core.health import CheckStatus, run_all_checks
from llmhq_promptops.core.template import validate_prompt_text
from llmhq_promptops.hooks.pre_commit import PreCommitHook


VALID = """\
metadata:
  id: refund
  version: v1.0.0
template: |
  Hello {{ name }}, your refund of {{ amount }} is on its way.
variables:
  name:
    type: string
    required: true
  amount:
    type: number
    required: true
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Dev")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "refund.yaml").write_text(VALID)
    return tmp_path


# ── one validator ───────────────────────────────────────────────────


class TestValidatePromptText:
    def test_a_prompt_with_required_variables_is_valid(self):
        ok, detail = validate_prompt_text(VALID)
        assert ok is True, detail

    def test_unclosed_jinja_is_invalid(self):
        ok, detail = validate_prompt_text(
            VALID.replace("Hello {{ name }}", "Hello {% if name %}unclosed")
        )
        assert ok is False
        assert detail

    def test_unparseable_yaml_is_invalid(self):
        ok, detail = validate_prompt_text("metadata: [not a mapping\n")
        assert ok is False
        assert detail

    def test_an_undeclared_variable_in_the_body_is_still_valid(self):
        """PromptTemplate treats it as required; the placeholder covers it."""
        ok, detail = validate_prompt_text(
            VALID.replace(
                "is on its way.", "is on its way, {{ undeclared_extra }}."
            )
        )
        assert ok is True, detail

    def test_typed_variables_get_type_plausible_placeholders(self):
        """A number variable used arithmetically must not get a string."""
        source = (
            "metadata:\n  id: t\n  version: v1.0.0\n"
            "template: |\n  Total: {{ amount + 1 }}\n"
            "variables:\n  amount:\n    type: number\n    required: true\n"
        )
        ok, detail = validate_prompt_text(source)
        assert ok is True, detail


class TestPreCommitUsesTheSameValidator:
    def test_a_prompt_with_required_variables_passes(self, repo: Path):
        """This path used to render with {} and fail by construction."""
        hook = PreCommitHook(str(repo))

        assert hook._run_prompt_tests([".promptops/prompts/refund.yaml"]) is True

    def test_a_broken_prompt_still_fails(self, repo: Path):
        (repo / ".promptops" / "prompts" / "refund.yaml").write_text(
            VALID.replace("Hello {{ name }}", "Hello {% if name %}unclosed")
        )
        hook = PreCommitHook(str(repo))

        assert hook._run_prompt_tests([".promptops/prompts/refund.yaml"]) is False


# ── doctor has to be able to say no ─────────────────────────────────


def _check(repo: Path, name: str):
    return next(c for c in run_all_checks(repo) if c.name == name)


class TestDoctorDetectsDeadHooks:
    def _install(self, repo: Path, interpreter: str) -> None:
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name in ("pre-commit", "post-commit"):
            hook = hooks_dir / name
            hook.write_text(
                f"#!{interpreter}\n"
                f'"""PromptOps {name} hook."""\n'
                "from llmhq_promptops.hooks import pre_commit\n"
            )
            hook.chmod(0o755)

    def test_working_hooks_are_reported_ok(self, repo: Path):
        self._install(repo, sys.executable)

        check = _check(repo, "hooks")

        assert check.status is CheckStatus.OK, check.message

    def test_hooks_under_an_interpreter_without_promptops_are_reported_failing(
        self, repo: Path
    ):
        """Installed, executable, and dead on every commit."""
        self._install(repo, "/bin/false")

        check = _check(repo, "hooks")

        assert check.status is CheckStatus.FAIL, (
            f"doctor called a dead hook healthy: {check.status} {check.message}"
        )
        assert "import" in (check.message + (check.hint or "")).lower()

    def test_missing_hooks_are_still_only_a_warning(self, repo: Path):
        """Hooks are opt-in since v0.4.0, so absent is a choice, not a fault."""
        (repo / ".git" / "hooks").mkdir(parents=True, exist_ok=True)

        check = _check(repo, "hooks")

        assert check.status is CheckStatus.WARN
