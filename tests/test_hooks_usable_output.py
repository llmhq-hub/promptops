"""What the hooks produce has to be usable by the rest of the tool (v0.6.0).

Two defects that survived because nothing checked the hook's *output*, only
that it ran.

**The tags were write-only.** The post-commit hook tagged commits
``<prompt-id>-v1.1.0``. ``GitVersioning._get_tag_version`` reads exactly two
formats: per-prompt ``prompt-<id>-v1.2.3`` (what ``promptops migrate
tag-history`` writes) and legacy global ``v1.2.3``. The hook's format matched
neither, so ``history``, ``blame`` and version resolution all ignored every tag
auto-versioning ever created and fell back to ``commit-<sha>``. The headline
feature worked and no other part of the product could see that it had.

**The post-commit check failed on every prompt with a required variable.** It
rendered with ``{}``, so any prompt declaring a required variable failed by
construction with ``PROMPTOPS_E014: Required variable 'name' not provided``.
``post_commit_tests`` defaults to True, so every user saw a red mark on every
commit. A check that always fails teaches people to ignore everything the tool
says, which is worse than having no check.

The replacement validates what the check was reaching for: that the prompt
parses, that its Jinja compiles, and that it renders given values for the
variables it declares.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from llmhq_promptops.core.git_versioning import GitVersioning
from llmhq_promptops.hooks.post_commit import PostCommitHook


PROMPT = """\
metadata:
  id: refund
  version: v1.0.0
  description: Refund explanation
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
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


def _install_hooks(repo: Path) -> None:
    from cli.commands.hooks import _install_post_commit_hook, _install_pre_commit_hook

    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    _install_pre_commit_hook(hooks_dir)
    _install_post_commit_hook(hooks_dir)


def _commit(repo: Path, message: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo, env=env, capture_output=True, text=True,
    )


def _commit_a_prompt(repo: Path, body: str = PROMPT) -> subprocess.CompletedProcess:
    _install_hooks(repo)
    prompts = repo / ".promptops" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "refund.yaml").write_text(body)
    return _commit(repo, "feat: refund prompt")


# ── the tags have to be readable ────────────────────────────────────


class TestTagsAreReadableByTheSdk:
    def test_the_tag_uses_the_documented_per_prompt_format(self, repo: Path):
        result = _commit_a_prompt(repo)
        assert result.returncode == 0, result.stdout + result.stderr

        tags = _git(repo, "tag", "-l").split()

        assert tags, "no tag was created at all"
        assert all(
            re.fullmatch(r"prompt-refund-v\d+\.\d+\.\d+", t) for t in tags
        ), (
            "tags are in a format GitVersioning._get_tag_version cannot read, "
            f"so history and blame will never see them: {tags!r}"
        )

    def test_the_version_is_visible_to_the_sdk(self, repo: Path):
        """The real test: can the rest of the product see what the hook did."""
        result = _commit_a_prompt(repo)
        assert result.returncode == 0, result.stdout + result.stderr

        head = _git(repo, "rev-parse", "HEAD")
        version = GitVersioning(str(repo)).version_at_commit("refund", head)

        assert version is not None
        assert not version.startswith("commit-"), (
            f"the SDK fell back to a commit sha ({version}); it could not see "
            "the tag the hook just created"
        )
        assert re.fullmatch(r"v\d+\.\d+\.\d+", version), version

    def test_versions_of_other_prompts_are_not_confused(self, repo: Path):
        """Per-prompt tags must stay scoped to their prompt."""
        _commit_a_prompt(repo)
        prompts = repo / ".promptops" / "prompts"
        (prompts / "welcome.yaml").write_text(
            PROMPT.replace("id: refund", "id: welcome")
        )
        result = _commit(repo, "feat: welcome prompt")
        assert result.returncode == 0, result.stdout + result.stderr

        tags = sorted(_git(repo, "tag", "-l").split())

        assert any(t.startswith("prompt-refund-v") for t in tags), tags
        assert any(t.startswith("prompt-welcome-v") for t in tags), tags


# ── the check has to be able to pass ────────────────────────────────


class TestPostCommitValidation:
    def test_a_prompt_with_required_variables_passes(self, repo: Path):
        """Rendering with no variables tested nothing except that they exist."""
        result = _commit_a_prompt(repo)
        combined = result.stdout + result.stderr

        assert "Post-commit test failed" not in combined, (
            "a perfectly valid prompt was reported as failing:\n" + combined
        )
        assert "E014" not in combined

    def test_broken_jinja_is_still_caught(self, repo: Path):
        """The check must still be capable of failing, or it is theatre.

        The pre-commit hook has always claimed to "validate prompt syntax",
        but it only constructed a ``PromptTemplate``, and the Jinja source is
        compiled lazily by the ``.template`` property, so an unclosed block
        sailed through. It is caught before the commit lands now, which is
        where a guaranteed-broken template should be caught.
        """
        broken = PROMPT.replace(
            "Hello {{ name }}, your refund of {{ amount }} is on its way.",
            "Hello {% if name %}unclosed",
        )
        result = _commit_a_prompt(repo, broken)
        combined = result.stdout + result.stderr

        assert result.returncode != 0, (
            "a prompt with an unclosed Jinja block was committed:\n" + combined
        )
        assert "refund" in combined

    def test_validation_reports_success_for_a_valid_prompt(self, repo: Path):
        hook = PostCommitHook(str(repo))
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        (prompts / "refund.yaml").write_text(PROMPT)

        ok, detail = hook._validate_prompt(".promptops/prompts/refund.yaml")

        assert ok is True, detail

    def test_validation_reports_failure_for_broken_yaml(self, repo: Path):
        hook = PostCommitHook(str(repo))
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True, exist_ok=True)
        (prompts / "refund.yaml").write_text("metadata: [this is not a mapping\n")

        ok, detail = hook._validate_prompt(".promptops/prompts/refund.yaml")

        assert ok is False
        assert detail
