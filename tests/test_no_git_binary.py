"""PromptOps must work without the git *binary* installed (v0.5.0).

The bug: ``core/git_versioning.py`` imported GitPython at module level, and
GitPython raises during its own ``refresh()`` when there is no git executable
on PATH. So ``import llmhq_promptops`` failed outright, taking the
snapshot-only production runtime with it.

That runtime is the headline v0.3.0 feature. The README tells you to ship
``snapshot.json`` in a Docker image, and the natural base image
(``python:3.11-slim``) has no git binary. The docs conflated two different
things: running without the ``.git/`` *directory* worked, running without the
git *binary* did not, and nobody reading "no git needed in production" would
draw that distinction.

These tests run a real subprocess with a stripped PATH. That is the only
honest way to check it: monkeypatching cannot reproduce an import-time
failure in a dependency.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llmhq_promptops import write_snapshot
from llmhq_promptops.core.errors import E018_GIT_BINARY_MISSING


PROMPT = """\
metadata:
  id: greeting
  description: Greeting
template: |
  Hello {{ name }}.
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
def no_git_path(tmp_path: Path) -> Path:
    """An empty directory to use as PATH, so no git binary is reachable."""
    d = tmp_path / "empty-bin"
    d.mkdir()
    return d


@pytest.fixture
def snapshot_only_dir(tmp_path: Path) -> Path:
    """A directory containing only .promptops/snapshot.json.

    Built with git available (as CI would), then handed to a subprocess that
    has none, which is exactly the build-then-ship split.
    """
    source = tmp_path / "source"
    prompts = source / ".promptops" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "greeting.yaml").write_text(PROMPT)

    _git(source, "init", "--quiet")
    _git(source, "config", "user.email", "t@e.com")
    _git(source, "config", "user.name", "Dev")
    _git(source, "config", "commit.gpgsign", "false")
    _git(source, "add", ".")
    _git(source, "commit", "--quiet", "-m", "feat: greeting")

    write_snapshot(str(source))

    runtime = tmp_path / "runtime"
    (runtime / ".promptops").mkdir(parents=True)
    (runtime / ".promptops" / "snapshot.json").write_text(
        (source / ".promptops" / "snapshot.json").read_text()
    )
    assert not (runtime / ".git").exists()
    return runtime


def _run_without_git(cwd: Path, no_git_path: Path, *args: str):
    """Run a subprocess whose PATH contains no git binary."""
    env = dict(os.environ)
    env["PATH"] = str(no_git_path)
    env.pop("GIT_PYTHON_REFRESH", None)
    return subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True
    )


# ── the SDK must import and resolve ─────────────────────────────────


class TestSdkWorksWithoutGitBinary:
    def test_importing_the_package_succeeds(self, tmp_path, no_git_path):
        result = _run_without_git(
            tmp_path, no_git_path, sys.executable, "-c", "import llmhq_promptops"
        )
        assert result.returncode == 0, result.stderr
        assert "GIT_PYTHON_REFRESH" not in result.stderr

    def test_snapshot_resolution_works(self, snapshot_only_dir, no_git_path):
        """The headline v0.3.0 claim, with no git binary anywhere."""
        result = _run_without_git(
            snapshot_only_dir,
            no_git_path,
            sys.executable,
            "-c",
            "from llmhq_promptops import get_prompt;"
            "print(get_prompt('greeting', {'name': 'Ada'}))",
        )
        assert result.returncode == 0, result.stderr
        assert "Hello Ada." in result.stdout

    def test_resolve_reports_snapshot_as_the_source(
        self, snapshot_only_dir, no_git_path
    ):
        result = _run_without_git(
            snapshot_only_dir,
            no_git_path,
            sys.executable,
            "-c",
            "from llmhq_promptops import PromptManager, AutoResolver;"
            "m = PromptManager('.', resolver=AutoResolver(repo_path='.'));"
            "print(m.resolve('greeting').source)",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "snapshot"


# ── git-needing paths fail with OUR message ─────────────────────────


class TestGitNeedingPathsExplainThemselves:
    def test_sdk_raises_e018_naming_git(self, tmp_path, no_git_path):
        """Touching git without the binary must name git, in our voice.

        The traceback still shows GitPython's ImportError as the __cause__,
        which is correct Python behavior and useful for debugging. What
        matters is that OUR error is the one raised and the last thing read.
        """
        result = _run_without_git(
            tmp_path,
            no_git_path,
            sys.executable,
            "-c",
            "from llmhq_promptops import GitVersioning;"
            "GitVersioning('.').repo",
        )
        assert result.returncode != 0
        assert "PROMPTOPS_E018" in result.stderr
        assert "snapshot" in result.stderr, "the hint should point at the snapshot path"
        assert result.stderr.rstrip().endswith("#promptops_e018")

    def test_cli_git_command_prints_our_message(self, tmp_path, no_git_path):
        """A real repo, but no git binary: E018, not a GitPython wall.

        The directory must actually be a repository. In a non-repo the correct
        answer is E005 ("not a git repository"), which is a different fact and
        would make this test pass for the wrong reason.
        """
        prompts = tmp_path / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)
        _git(tmp_path, "init", "--quiet")
        _git(tmp_path, "config", "user.email", "t@e.com")
        _git(tmp_path, "config", "user.name", "Dev")
        _git(tmp_path, "config", "commit.gpgsign", "false")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "feat: greeting")
        # A snapshot would make AutoResolver skip git entirely, so ensure none.
        assert not (tmp_path / ".promptops" / "snapshot.json").exists()

        promptops = Path(sys.executable).parent / "promptops"
        result = _run_without_git(
            tmp_path, no_git_path, str(promptops), "snapshot", "build"
        )

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "PROMPTOPS_E018" in combined
        assert "GIT_PYTHON_REFRESH" not in combined
        assert "Traceback" not in combined

    def test_cli_help_still_works_without_git(self, tmp_path, no_git_path):
        """--help must never require a system dependency."""
        promptops = Path(sys.executable).parent / "promptops"
        result = _run_without_git(tmp_path, no_git_path, str(promptops), "--help")
        assert result.returncode == 0, result.stderr
        assert "history" in result.stdout

    def test_error_code_is_registered(self):
        assert E018_GIT_BINARY_MISSING == "PROMPTOPS_E018"
