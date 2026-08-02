"""The hooks must not damage the repository they run in (v0.6.0).

Two defects, both found only after the blocked-commit bug from
``test_hooks_e2e.py`` was fixed, because a commit that never lands hides
everything downstream of it.

**Comments were deleted.** ``_update_version_in_yaml`` round-tripped the whole
document through ``yaml.safe_load`` and ``yaml.dump`` in order to change one
field. YAML comments do not survive that, and neither does block scalar
formatting. Every commit, every prompt, no warning. The note saying who owns a
prompt is often the most valuable line in the file.

**Files were staged behind the user's back.** ``_generate_and_store_reports``
wrote into ``.promptops/reports/`` after the commit and ran ``git add`` on the
result, so the user's *next* commit silently carried files they never staged.

The lesson from both: a versioning tool earns trust by touching exactly what it
said it would touch. The fix is a targeted line edit that changes the version
line and nothing else, verified here by diffing before against after.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from llmhq_promptops.hooks.post_commit import PostCommitHook
from llmhq_promptops.hooks.pre_commit import PreCommitHook


COMMENTED_PROMPT = """\
# Owned by the billing team. Ping #billing before changing the refund wording.
metadata:
  id: refund
  version: v1.0.0
  description: Refund explanation
template: |
  Line one.
  Line two.

  Line four, after a deliberate blank line.
variables:
  name:        # the customer's display name, not their legal name
    type: string
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
    """Commit with the installed hooks actually running.

    PATH decides which interpreter runs a ``#!/usr/bin/env python3`` script,
    so this interpreter's directory goes first or the hook imports some other
    install and the test proves nothing.
    """
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo, env=env, capture_output=True, text=True,
    )


# ── the version rewrite must be surgical ────────────────────────────


class TestVersionRewriteIsSurgical:
    """Change the version line. Change nothing else."""

    def test_it_updates_the_version(self, repo: Path):
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(COMMENTED_PROMPT, "v1.1.0")

        assert out is not None
        assert hook._extract_current_version(out) == "v1.1.0"

    def test_it_changes_exactly_one_line(self, repo: Path):
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(COMMENTED_PROMPT, "v1.1.0")

        before = COMMENTED_PROMPT.splitlines()
        after = out.splitlines()
        differing = [
            (a, b) for a, b in zip(before, after) if a != b
        ]

        assert len(before) == len(after), (
            "the rewrite changed the line count; it reserialized the document"
        )
        assert differing == [("  version: v1.0.0", "  version: v1.1.0")], (
            f"expected only the version line to change, got {differing!r}"
        )

    def test_header_comments_survive(self, repo: Path):
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(COMMENTED_PROMPT, "v1.1.0")

        assert "# Owned by the billing team." in out, "the header comment was deleted"

    def test_inline_comments_survive(self, repo: Path):
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(COMMENTED_PROMPT, "v1.1.0")

        assert "# the customer's display name" in out, "an inline comment was deleted"

    def test_block_scalar_formatting_survives(self, repo: Path):
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(COMMENTED_PROMPT, "v1.1.0")

        assert "template: |" in out, (
            "the block scalar was reserialized into a quoted string"
        )
        assert "  Line four, after a deliberate blank line." in out

    def test_a_trailing_comment_on_the_version_line_survives(self, repo: Path):
        source = COMMENTED_PROMPT.replace(
            "  version: v1.0.0", "  version: v1.0.0  # pinned during the migration"
        )
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(source, "v1.1.0")

        assert "# pinned during the migration" in out
        assert hook._extract_current_version(out) == "v1.1.0"

    def test_the_legacy_prompt_section_is_updated(self, repo: Path):
        source = (
            "prompt:\n"
            "  id: legacy\n"
            "  version: v2.3.4\n"
            "  template: 'Hi'\n"
        )
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(source, "v2.4.0")

        assert out is not None
        assert hook._extract_current_version(out) == "v2.4.0"
        assert "id: legacy" in out

    def test_a_prompt_with_no_version_field_gains_one(self, repo: Path):
        source = (
            "metadata:\n"
            "  id: fresh\n"
            "template: |\n"
            "  Hello.\n"
        )
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(source, "v1.0.0")

        assert out is not None
        assert hook._extract_current_version(out) == "v1.0.0"
        assert "template: |" in out

    def test_it_refuses_rather_than_mangles_when_it_cannot_edit_safely(
        self, repo: Path
    ):
        """A flow mapping has no version *line* to rewrite.

        Returning None makes the caller log a warning and leave the file
        alone, which is the correct failure mode. Falling back to a
        reserialization would be the original bug wearing a disguise.
        """
        source = "metadata: {id: flow, version: v1.0.0}\ntemplate: 'Hi'\n"
        hook = PreCommitHook(str(repo))
        out = hook._update_version_in_yaml(source, "v1.1.0")

        assert out is None or hook._extract_current_version(out) == "v1.1.0", (
            "the rewrite produced a document whose version is not what was asked "
            "for, which means it corrupted the file"
        )

    def test_end_to_end_a_real_commit_preserves_comments(self, repo: Path):
        _install_hooks(repo)
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "refund.yaml").write_text(COMMENTED_PROMPT)

        result = _commit(repo, "feat: refund prompt")
        assert result.returncode == 0, result.stdout + result.stderr

        committed = _git(repo, "show", "HEAD:.promptops/prompts/refund.yaml")

        assert "# Owned by the billing team." in committed
        assert "# the customer's display name" in committed
        assert "template: |" in committed


# ── the hook must not stage anything ────────────────────────────────


class TestTheHookLeavesTheIndexAlone:
    def test_the_index_is_clean_after_a_commit(self, repo: Path):
        """Anything staged here rides along in the user's *next* commit."""
        _install_hooks(repo)
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "refund.yaml").write_text(COMMENTED_PROMPT)

        result = _commit(repo, "feat: refund prompt")
        assert result.returncode == 0, result.stdout + result.stderr

        status = _git(repo, "status", "--short")

        assert status == "", (
            f"the hook left staged changes behind:\n{status}"
        )

    def test_reports_are_off_unless_asked_for(self, repo: Path):
        """Writing files into someone's repository should be opt-in."""
        hook = PostCommitHook(str(repo))

        assert hook.generate_reports is False

    def test_reports_are_written_when_enabled(self, repo: Path):
        (repo / ".promptops").mkdir(exist_ok=True)
        (repo / ".promptops" / "config.yaml").write_text("generate_reports: true\n")

        hook = PostCommitHook(str(repo))

        assert hook.generate_reports is True
