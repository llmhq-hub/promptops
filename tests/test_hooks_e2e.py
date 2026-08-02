"""End-to-end tests for the git hooks (v0.5.1).

The gap these close: before this file, **zero** tests imported
``llmhq_promptops.hooks``. 761 lines of hook code with 15 bare
``except Exception`` handlers ran uncovered through six releases, and the
headline auto-versioning feature was broken in every one of them.

The bug: ``hooks/pre_commit.py`` and ``hooks/post_commit.py`` invoked
``git show -- <rev>:<path>``. The ``--`` separator (added in the v0.2.0
security pass to block filename injection) tells git that everything after
it is a **pathspec**, so ``<rev>:<path>`` stopped being parsed as a revision.
Git then exits 0 with empty output rather than failing, so:

- ``_get_staged_content`` returned ``""``, which is not ``None`` and so
  passed the guard, then ``yaml.safe_load("")`` returned ``None`` and
  ``"metadata" in None`` raised TypeError. The pre-commit hook caught it and
  **blocked the commit**.
- ``_get_committed_content`` returned ``""``, so every existing prompt looked
  brand new to the version detector.
- ``_detect_change_type`` fell into its ``except Exception`` and always
  reported ``UNKNOWN``.

``--`` is correct for commands taking pathspecs (``git tag -l --``,
``git add --``, both verified fine). It is wrong for ``git show <rev>:<path>``,
where the argument is a revision.

These tests drive real ``git commit`` calls, because that is the only way to
catch it. Every unit-level test passed throughout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from llmhq_promptops.hooks.pre_commit import PreCommitHook
from llmhq_promptops.hooks.post_commit import PostCommitHook


PROMPT = """\
metadata:
  id: greeting
  description: Greeting prompt
  version: v1.0.0
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
def empty_repo(tmp_path: Path) -> Path:
    """An initialized repo with **no commits yet**.

    Separate from ``repo`` because the first commit in a repository is a root
    commit, and root commits are their own failure mode: they have no parent,
    so ``git diff-tree HEAD`` reports nothing. That is the state a first-time
    user is in.
    """
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Dev")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


@pytest.fixture
def repo(empty_repo: Path) -> Path:
    (empty_repo / "README.md").write_text("x\n")
    _git(empty_repo, "add", ".")
    _git(empty_repo, "commit", "--quiet", "-m", "initial")
    return empty_repo


@pytest.fixture
def repo_with_prompt(repo: Path) -> Path:
    prompts = repo / ".promptops" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "greeting.yaml").write_text(PROMPT)
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "feat: greeting")
    return repo


# ── the git plumbing the hooks depend on ────────────────────────────


class TestHookGitPlumbing:
    """Each accessor must return real content, not an empty string.

    Asserting non-empty is the whole point: the bug produced empty output
    with a zero exit code, which every caller mistook for valid data.
    """

    def test_staged_content_is_readable(self, repo: Path):
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)
        _git(repo, "add", ".")

        hook = PreCommitHook(str(repo))
        content = hook._get_staged_content(".promptops/prompts/greeting.yaml")

        assert content, "staged content came back empty"
        assert "id: greeting" in content

    def test_committed_content_is_readable(self, repo_with_prompt: Path):
        hook = PreCommitHook(str(repo_with_prompt))
        content = hook._get_committed_content(".promptops/prompts/greeting.yaml")

        assert content, "committed (HEAD) content came back empty"
        assert "id: greeting" in content

    def test_extract_version_survives_unparseable_content(self, repo: Path):
        """Defence in depth: yaml.safe_load returns None for empty input.

        ``except yaml.YAMLError`` does not catch the resulting TypeError, so
        an empty string reached ``"metadata" in None`` and crashed.
        """
        hook = PreCommitHook(str(repo))
        assert hook._extract_current_version("") == "v1.0.0"
        assert hook._extract_current_version("# just a comment\n") == "v1.0.0"

    def test_change_type_is_classified_not_unknown(self, repo_with_prompt: Path):
        (repo_with_prompt / ".promptops" / "prompts" / "greeting.yaml").write_text(
            PROMPT.replace("Hello {{ name }}.", "Hello {{ name }}, welcome.")
        )
        _git(repo_with_prompt, "add", ".")
        _git(repo_with_prompt, "commit", "--quiet", "--no-verify", "-m", "fix: reword")

        hook = PostCommitHook(str(repo_with_prompt))
        result = hook._detect_change_type(".promptops/prompts/greeting.yaml")

        assert result != "UNKNOWN", "change detection fell into its except handler"
        assert result in {"NEW", "MAJOR", "MINOR", "PATCH"}

    def test_staged_deletions_are_not_offered_for_versioning(
        self, repo_with_prompt: Path
    ):
        """A deleted prompt has no staged content, so there is nothing to version.

        Listing it anyway sends ``_process_prompt_file`` looking for content
        that cannot exist, and its failure return blocks the commit.
        """
        _git(repo_with_prompt, "rm", "--quiet", ".promptops/prompts/greeting.yaml")

        staged = PreCommitHook(str(repo_with_prompt))._get_staged_prompt_files()

        assert staged == [], f"a staged deletion was offered for versioning: {staged}"

    def test_deletions_and_edits_stage_together_cleanly(self, repo_with_prompt: Path):
        """Excluding deletions must not drop the ordinary files beside them."""
        prompts = repo_with_prompt / ".promptops" / "prompts"
        (prompts / "farewell.yaml").write_text(PROMPT.replace("greeting", "farewell"))
        _git(repo_with_prompt, "add", ".")
        _git(repo_with_prompt, "commit", "--quiet", "--no-verify", "-m", "feat: farewell")

        _git(repo_with_prompt, "rm", "--quiet", ".promptops/prompts/greeting.yaml")
        (prompts / "farewell.yaml").write_text(
            PROMPT.replace("greeting", "farewell").replace("Hello", "Goodbye")
        )
        _git(repo_with_prompt, "add", ".")

        staged = PreCommitHook(str(repo_with_prompt))._get_staged_prompt_files()

        assert staged == [".promptops/prompts/farewell.yaml"]

    def test_change_type_for_a_deleted_prompt_is_deleted(self, repo_with_prompt: Path):
        _git(repo_with_prompt, "rm", "--quiet", ".promptops/prompts/greeting.yaml")
        _git(repo_with_prompt, "commit", "--quiet", "--no-verify", "-m", "chore: drop")

        hook = PostCommitHook(str(repo_with_prompt))
        result = hook._detect_change_type(".promptops/prompts/greeting.yaml")

        assert result == "DELETED", (
            "a removed prompt should be reported as DELETED, not swallowed by the "
            f"except handler; got {result!r}"
        )

    def test_a_root_commit_reports_its_prompt_files(self, empty_repo: Path):
        """``git diff-tree HEAD`` prints nothing for a parentless commit.

        It exits 0 while doing so, so post-commit read the silence as "no
        prompts changed" and skipped versioning entirely. That is the very
        first commit of every new repository.
        """
        prompts = empty_repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)
        _git(empty_repo, "add", ".")
        _git(empty_repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        changed = PostCommitHook(str(empty_repo))._get_changed_prompt_files()

        assert changed == [".promptops/prompts/greeting.yaml"], (
            f"root commit reported {changed!r}; versioning never runs"
        )


# ── a real commit, with hooks installed ─────────────────────────────


def _install_hooks(repo: Path) -> None:
    from cli.commands.hooks import _install_pre_commit_hook, _install_post_commit_hook

    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    _install_pre_commit_hook(hooks_dir)
    _install_post_commit_hook(hooks_dir)


def _commit(repo: Path, message: str) -> subprocess.CompletedProcess:
    """Commit for real, with the installed hooks running.

    The hook scripts start with ``#!/usr/bin/env python3``, so PATH decides
    which interpreter runs them. Put this interpreter's directory first, or
    the hook imports a different install (or none) and the test proves
    nothing about the code under test.
    """
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo, env=env, capture_output=True, text=True,
    )


class TestCommitWithHooksInstalled:
    """The documented flow: init, hooks install, create prompt, commit."""

    def test_committing_a_new_prompt_succeeds(self, repo: Path):
        _install_hooks(repo)
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)

        result = _commit(repo, "feat: greeting")

        assert result.returncode == 0, (
            "the pre-commit hook blocked the commit:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert _git(repo, "log", "--oneline") .count("\n") >= 1

    def test_committing_a_modified_prompt_succeeds(self, repo_with_prompt: Path):
        _install_hooks(repo_with_prompt)
        (repo_with_prompt / ".promptops" / "prompts" / "greeting.yaml").write_text(
            PROMPT.replace("Hello {{ name }}.", "Hello {{ name }}, welcome aboard.")
        )

        result = _commit(repo_with_prompt, "fix: warmer greeting")

        assert result.returncode == 0, (
            "the pre-commit hook blocked the commit:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_the_hook_does_not_report_a_processing_failure(self, repo: Path):
        """A zero exit is not enough; the hook must not log a failure."""
        _install_hooks(repo)
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)

        result = _commit(repo, "feat: greeting")
        combined = result.stdout + result.stderr

        assert "Failed to process" not in combined
        assert "blocking commit" not in combined

    def test_a_commit_touching_no_prompts_is_unaffected(self, repo_with_prompt: Path):
        _install_hooks(repo_with_prompt)
        (repo_with_prompt / "README.md").write_text("changed\n")

        result = _commit(repo_with_prompt, "docs: touch readme")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_deleting_a_prompt_succeeds(self, repo_with_prompt: Path):
        """Removing a prompt is a normal thing to do and must not be blocked."""
        _install_hooks(repo_with_prompt)
        _git(repo_with_prompt, "rm", "--quiet", ".promptops/prompts/greeting.yaml")

        result = _commit(repo_with_prompt, "chore: retire the greeting prompt")

        assert result.returncode == 0, (
            "the pre-commit hook blocked a deletion:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        tracked = _git(repo_with_prompt, "ls-files", ".promptops/prompts")
        assert "greeting.yaml" not in tracked, "the delete commit never landed"

    def test_a_prompt_in_the_very_first_commit_is_versioned(self, empty_repo: Path):
        """init, hooks install, write a prompt, commit: the first-run path."""
        _install_hooks(empty_repo)
        prompts = empty_repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)

        result = _commit(empty_repo, "feat: greeting")

        assert result.returncode == 0, result.stdout + result.stderr
        tags = _git(empty_repo, "tag", "-l").split()
        assert any(t.startswith("greeting-v") for t in tags), (
            "a root commit produced no version tag; auto-versioning silently "
            f"did nothing. tags={tags!r}"
        )
