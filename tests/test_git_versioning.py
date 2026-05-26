"""Tests for GitVersioning (Phase 1.5a M2).

Focus: the version identifier returned for a commit is *immutable*.

Before M2, `_generate_version` derived a fake semver from the commit's
position in `iter_commits` output (``v{major}.{minor}.{patch}``). That
meant the same commit got a different "version" every time a new commit
landed — directly breaking the `promptops blame --at <ts>` use case the
Resolver layer is being built to support.

After M2:
- Tagged commits still return the git tag (unchanged behavior).
- Untagged commits return a ``commit-<short-sha>`` reference, which is
  a stable identifier for that commit specifically — the version string
  does not shift when new commits arrive.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmhq_promptops.core.git_versioning import GitVersioning


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt for tests
  id: hello
  model: gpt-4-turbo
  template: 'Hello, {{ name }}! Welcome.'
variables:
  name:
    type: string
    required: true
"""


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo` and return stdout. Test-only helper."""
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def promptops_repo(tmp_path: Path) -> Path:
    """An isolated git repo with one committed prompt (`hello`)."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts_dir = tmp_path / ".promptops" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "hello.yaml").write_text(SAMPLE_PROMPT_YAML)

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial: add hello prompt")

    return tmp_path


class TestUntaggedCommitFallback:
    """Untagged commits return ``commit-<short-sha>``, not fake semver."""

    def test_untagged_commit_returns_commit_reference(self, promptops_repo: Path):
        gv = GitVersioning(str(promptops_repo))
        latest = gv.get_latest_version("hello")
        assert latest is not None
        assert latest.startswith("commit-"), (
            f"untagged commit should yield 'commit-<sha>', got {latest!r}"
        )
        # 'commit-' + 8 hex chars
        assert len(latest) == len("commit-") + 8

    def test_no_fake_semver_for_untagged_commit(self, promptops_repo: Path):
        """The old position-based ``v1.0.0`` semver is gone."""
        gv = GitVersioning(str(promptops_repo))
        versions = gv.get_prompt_versions("hello")
        assert len(versions) == 1
        v_str = versions[0]["version"]
        # The pre-M2 implementation would return "v1.0.0" here.
        assert not v_str.startswith("v"), (
            f"untagged commit must not look like semver; got {v_str!r}"
        )


class TestVersionImmutabilityAcrossHistory:
    """The version of an existing commit must not shift when new commits land."""

    def test_first_commit_version_is_stable_after_a_second_commit(
        self, promptops_repo: Path
    ):
        gv = GitVersioning(str(promptops_repo))

        versions_before = gv.get_prompt_versions("hello")
        assert len(versions_before) == 1
        first_commit_sha = versions_before[0]["commit"]
        first_commit_version = versions_before[0]["version"]

        # Bust the in-process cache by recreating the versioning instance.
        # (The cache is keyed by HEAD sha, so a new HEAD would naturally
        # invalidate it, but a fresh instance guarantees a clean read.)
        prompt_path = promptops_repo / ".promptops" / "prompts" / "hello.yaml"
        prompt_path.write_text(
            SAMPLE_PROMPT_YAML.replace("Welcome.", "Welcome aboard.")
        )
        _git(promptops_repo, "add", ".")
        _git(promptops_repo, "commit", "--quiet", "-m", "tweak greeting")

        gv2 = GitVersioning(str(promptops_repo))
        versions_after = gv2.get_prompt_versions("hello")
        assert len(versions_after) == 2

        first_after = next(
            v for v in versions_after if v["commit"] == first_commit_sha
        )
        assert first_after["version"] == first_commit_version, (
            "The first commit's version string must be identical before and "
            "after a second commit lands. The pre-M2 position-based fallback "
            "would have changed it from v1.0.0 to v1.0.1, which is the bug."
        )


class TestTaggedCommitsStillReturnTag:
    """Existing tagged-commit behavior is preserved."""

    def test_tagged_commit_returns_tag_version(self, promptops_repo: Path):
        _git(promptops_repo, "tag", "v2.5.0")

        gv = GitVersioning(str(promptops_repo))
        versions = gv.get_prompt_versions("hello")
        assert versions[0]["version"] == "v2.5.0"

    def test_tagged_overrides_commit_reference(self, promptops_repo: Path):
        """When a commit has a tag, the tag wins over the commit-sha form."""
        _git(promptops_repo, "tag", "v0.1.0")
        gv = GitVersioning(str(promptops_repo))
        latest = gv.get_latest_version("hello")
        assert latest == "v0.1.0"
        assert latest != f"commit-{_git(promptops_repo, 'rev-parse', 'HEAD')[:8]}"


class TestCommitReferenceRoundtrip:
    """The new commit-reference can be used as a version string to look up content."""

    def test_lookup_by_commit_reference_returns_content(self, promptops_repo: Path):
        gv = GitVersioning(str(promptops_repo))
        latest = gv.get_latest_version("hello")
        assert latest is not None and latest.startswith("commit-")

        content = gv.get_prompt_at_version("hello", latest)
        assert content is not None
        assert "Hello" in content

    def test_lookup_by_bare_short_sha_still_works(self, promptops_repo: Path):
        """Pre-existing behavior: commit_short (raw 8-char sha) resolves."""
        gv = GitVersioning(str(promptops_repo))
        versions = gv.get_prompt_versions("hello")
        short_sha = versions[0]["commit_short"]

        content = gv.get_prompt_at_version("hello", short_sha)
        assert content is not None
        assert "Hello" in content
