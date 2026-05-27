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


# ── M2b: per-prompt tag recognition ─────────────────────────────────


SECOND_PROMPT_YAML = """\
prompt:
  description: Farewell prompt for scoping tests
  id: goodbye
  model: gpt-4-turbo
  template: 'Goodbye, {{ name }}.'
variables:
  name:
    type: string
    required: true
"""


@pytest.fixture
def two_prompt_repo(promptops_repo: Path) -> Path:
    """The base repo with a SECOND prompt committed.

    Used to verify per-prompt tag scoping — a tag for prompt X must
    not be returned when looking up prompt Y.
    """
    (promptops_repo / ".promptops" / "prompts" / "goodbye.yaml").write_text(
        SECOND_PROMPT_YAML
    )
    _git(promptops_repo, "add", ".")
    _git(promptops_repo, "commit", "--quiet", "-m", "add goodbye prompt")
    return promptops_repo


class TestPerPromptTagRecognition:
    """M2b: ``prompt-<id>-v1.2.3`` tags are recognized and scoped per-prompt."""

    def test_per_prompt_tag_is_used_for_matching_prompt(self, promptops_repo: Path):
        _git(promptops_repo, "tag", "prompt-hello-v0.3.0")

        gv = GitVersioning(str(promptops_repo))
        assert gv.get_latest_version("hello") == "v0.3.0"

    def test_per_prompt_tag_for_other_prompt_is_ignored(self, two_prompt_repo: Path):
        """A tag for prompt ``goodbye`` must not influence prompt ``hello``'s version."""
        head = _git(two_prompt_repo, "rev-parse", "HEAD")
        _git(two_prompt_repo, "tag", "prompt-goodbye-v9.9.9", head)

        gv = GitVersioning(str(two_prompt_repo))
        # 'hello' has no per-prompt tag and no legacy tag → falls back to commit-sha
        hello_version = gv.get_latest_version("hello")
        assert hello_version is not None
        assert hello_version.startswith("commit-"), (
            f"goodbye's tag leaked into hello's version lookup: {hello_version!r}"
        )

    def test_per_prompt_tag_priority_over_legacy_global_tag(self, promptops_repo: Path):
        """When a commit has both a global ``v1.0.0`` and a per-prompt tag, per-prompt wins."""
        _git(promptops_repo, "tag", "v1.0.0")
        _git(promptops_repo, "tag", "prompt-hello-v5.5.5")

        gv = GitVersioning(str(promptops_repo))
        assert gv.get_latest_version("hello") == "v5.5.5"

    def test_legacy_global_tag_still_works_without_per_prompt(self, promptops_repo: Path):
        """The legacy ``v1.0.0`` form still resolves when no per-prompt tag exists."""
        _git(promptops_repo, "tag", "v2.0.0")

        gv = GitVersioning(str(promptops_repo))
        assert gv.get_latest_version("hello") == "v2.0.0"

    def test_per_prompt_tag_without_v_prefix_is_accepted(self, promptops_repo: Path):
        """``prompt-hello-1.0.0`` (no ``v``) is normalized to ``v1.0.0``."""
        _git(promptops_repo, "tag", "prompt-hello-1.4.2")

        gv = GitVersioning(str(promptops_repo))
        assert gv.get_latest_version("hello") == "v1.4.2"

    def test_lookup_by_per_prompt_tag_string(self, promptops_repo: Path):
        """After tagging, the per-prompt version string round-trips through resolution."""
        _git(promptops_repo, "tag", "prompt-hello-v0.7.0")

        gv = GitVersioning(str(promptops_repo))
        content = gv.get_prompt_at_version("hello", "v0.7.0")
        assert content is not None
        assert "Hello" in content


# ── M5c: resolve a prompt at a commit that didn't touch its file ────


class TestResolveAtUnrelatedCommit:
    """Regression for the blame-multiprompt bug found while building v0.3.1's demo.

    The bug: ``_resolve_version_to_commit`` only walked the prompt's own file
    history, so resolving prompt A at a commit that only touched prompt B
    failed with ``not found`` even though prompt A existed at that commit
    unchanged. This made ``promptops blame --at <ts>`` fail for any prompt
    that wasn't directly modified by the deploy commit — i.e. the common
    case.

    Fix: fall back to ``Repo.commit(version)`` so any valid commit ref in
    the repo resolves, and let ``get_prompt_at_version`` do the actual
    tree lookup (which already handles "file existed at that commit but
    wasn't changed by it" cleanly via ``commit.tree[path]``).
    """

    def test_resolve_at_commit_that_only_touched_other_prompt(
        self, promptops_repo: Path
    ):
        # Add a SECOND prompt in its own commit
        second = promptops_repo / ".promptops" / "prompts" / "goodbye.yaml"
        second.write_text(SAMPLE_PROMPT_YAML.replace("hello", "goodbye"))
        _git(promptops_repo, "add", ".")
        _git(promptops_repo, "commit", "--quiet", "-m", "add goodbye")
        goodbye_commit = _git(promptops_repo, "rev-parse", "HEAD")

        # The goodbye commit didn't touch hello.yaml at all, but hello.yaml
        # existed at that commit (from the initial commit). Resolving hello
        # at the goodbye commit must succeed.
        gv = GitVersioning(str(promptops_repo))
        text = gv.get_prompt_at_version("hello", goodbye_commit)
        assert text is not None
        assert "Hello" in text

    def test_resolve_at_full_sha_anywhere_in_repo(self, promptops_repo: Path):
        head_sha = _git(promptops_repo, "rev-parse", "HEAD")
        gv = GitVersioning(str(promptops_repo))
        # Direct ``_resolve_version_to_commit`` returns the same full SHA back.
        assert gv._resolve_version_to_commit("hello", head_sha) == head_sha

    def test_resolve_at_short_sha_prefix(self, promptops_repo: Path):
        """7-char prefixes were previously rejected (commit_short is 8). Now they resolve via git."""
        head_sha = _git(promptops_repo, "rev-parse", "HEAD")
        short_7 = head_sha[:7]
        gv = GitVersioning(str(promptops_repo))
        assert gv._resolve_version_to_commit("hello", short_7) == head_sha

    def test_truly_invalid_ref_still_returns_none(self, promptops_repo: Path):
        gv = GitVersioning(str(promptops_repo))
        assert gv._resolve_version_to_commit("hello", "definitely-not-a-ref") is None
