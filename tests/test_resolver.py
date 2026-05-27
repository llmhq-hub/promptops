"""Tests for the Resolver layer (Phase 1.5a M1).

Covers:
- ResolvedPrompt frozen dataclass (immutability + to_dict/from_dict roundtrip)
- Resolver Protocol (runtime_checkable behavior)
- GitResolver constructor (requires git repo)
- GitResolver.resolve at each version reference
- GitResolver.resolve raises on prompt not found
- PromptManager(resolver=...) injection + backwards compat
- PromptManager.resolve() returns ResolvedPrompt
- PromptManager.get_prompt() still returns rendered str

All filesystem-dependent tests use the `promptops_repo` fixture which creates
an isolated git repo + .promptops/ in a tmp_path. Tests are independent of
the host filesystem layout.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llmhq_promptops import (
    GitResolver,
    PromptManager,
    ResolvedPrompt,
    Resolver,
)


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


@pytest.fixture
def promptops_repo(tmp_path: Path) -> Path:
    """Create an isolated git repo with a .promptops/prompts/hello.yaml.

    Returns the repo root path. The repo has one committed prompt
    (`hello`) so version-reference tests can resolve against HEAD.
    """
    # git init
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True
    )

    # Create .promptops/prompts/hello.yaml
    prompts_dir = tmp_path / ".promptops" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "hello.yaml").write_text(SAMPLE_PROMPT_YAML)

    # Commit it so HEAD has the file
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "initial: add hello prompt"],
        cwd=tmp_path,
        check=True,
    )

    return tmp_path


# ── ResolvedPrompt dataclass ────────────────────────────────────────


class TestResolvedPrompt:
    """ResolvedPrompt is a frozen dataclass with provenance fields."""

    def _sample(self) -> ResolvedPrompt:
        return ResolvedPrompt(
            text="prompt:\n  id: x\n",
            version="v1.2.3",
            commit="abc1234",
            resolved_at=datetime(2026, 5, 11, 14, 23, 0, tzinfo=timezone.utc),
            source="git",
            prompt_id="x",
        )

    def test_construction_assigns_all_fields(self):
        r = self._sample()
        assert r.text == "prompt:\n  id: x\n"
        assert r.version == "v1.2.3"
        assert r.commit == "abc1234"
        assert r.source == "git"
        assert r.prompt_id == "x"
        assert r.resolved_at.tzinfo is not None

    def test_frozen(self):
        r = self._sample()
        with pytest.raises(Exception):
            # frozen dataclass raises FrozenInstanceError on assignment
            r.text = "mutated"  # type: ignore[misc]

    def test_to_dict_roundtrip(self):
        original = self._sample()
        as_dict = original.to_dict()
        restored = ResolvedPrompt.from_dict(as_dict)
        assert restored == original

    def test_to_dict_serializes_datetime_as_iso(self):
        r = self._sample()
        as_dict = r.to_dict()
        assert isinstance(as_dict["resolved_at"], str)
        parsed = datetime.fromisoformat(as_dict["resolved_at"])
        assert parsed == r.resolved_at

    def test_from_dict_accepts_missing_optional_fields(self):
        # commit and version are Optional
        restored = ResolvedPrompt.from_dict({
            "text": "x",
            "resolved_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "source": "snapshot",
            "prompt_id": "x",
        })
        assert restored.version is None
        assert restored.commit is None


# ── Resolver Protocol ───────────────────────────────────────────────


class TestResolverProtocol:
    """Resolver is a @runtime_checkable Protocol."""

    def test_git_resolver_is_a_resolver(self, promptops_repo: Path):
        gr = GitResolver(str(promptops_repo))
        assert isinstance(gr, Resolver)

    def test_minimal_duck_typed_resolver(self):
        class Stub:
            def resolve(self, prompt_id, version=None):
                return ResolvedPrompt(
                    text="x", version=None, commit=None,
                    resolved_at=datetime.now(timezone.utc),
                    source="stub", prompt_id=prompt_id,
                )
        assert isinstance(Stub(), Resolver)

    def test_object_without_resolve_is_not_a_resolver(self):
        class Bad:
            pass
        assert not isinstance(Bad(), Resolver)


# ── GitResolver ─────────────────────────────────────────────────────


class TestGitResolverConstructor:
    """GitResolver requires a git repository at the given path."""

    def test_accepts_real_git_repo(self, promptops_repo: Path):
        gr = GitResolver(str(promptops_repo))
        assert gr.repo_path == promptops_repo.resolve()

    def test_rejects_non_git_directory(self, tmp_path: Path):
        # tmp_path here has no .git/ — fresh directory only
        with pytest.raises(ValueError, match="git repository"):
            GitResolver(str(tmp_path))


class TestGitResolverResolve:
    """GitResolver.resolve returns a ResolvedPrompt for each version reference."""

    @pytest.fixture
    def resolver(self, promptops_repo: Path) -> GitResolver:
        return GitResolver(str(promptops_repo))

    def test_resolves_with_no_version(self, resolver: GitResolver):
        r = resolver.resolve("hello")
        assert isinstance(r, ResolvedPrompt)
        assert r.prompt_id == "hello"
        assert r.source == "git"
        assert "Hello" in r.text or "hello" in r.text.lower()
        # No version implies working-tree resolution; commit is None
        assert r.commit is None

    def test_resolves_working_version_includes_head_commit(self, resolver: GitResolver):
        r = resolver.resolve("hello", "working")
        assert r.commit is not None
        assert len(r.commit) == 40  # full SHA
        assert r.source == "git"

    def test_resolves_latest_alias_same_as_working(self, resolver: GitResolver):
        r_working = resolver.resolve("hello", "working")
        r_latest = resolver.resolve("hello", "latest")
        assert r_working.text == r_latest.text
        assert r_working.commit == r_latest.commit

    def test_resolves_unstaged_returns_working_tree(self, resolver: GitResolver):
        r = resolver.resolve("hello", "unstaged")
        assert isinstance(r, ResolvedPrompt)
        assert r.source == "git"
        # commit is intentionally None for working-tree state
        assert r.commit is None

    def test_unknown_prompt_raises(self, resolver: GitResolver):
        with pytest.raises(ValueError, match="not found"):
            resolver.resolve("nonexistent-prompt-id")

    def test_unknown_prompt_error_lists_available(self, resolver: GitResolver):
        with pytest.raises(ValueError) as excinfo:
            resolver.resolve("nonexistent-prompt-id")
        msg = str(excinfo.value)
        assert "Available prompts" in msg

    def test_invalid_prompt_id_rejected(self, resolver: GitResolver):
        # validate_prompt_id rejects path-traversal etc.
        with pytest.raises(ValueError):
            resolver.resolve("../../etc/passwd")

    def test_resolved_at_is_timezone_aware(self, resolver: GitResolver):
        r = resolver.resolve("hello", "working")
        assert r.resolved_at.tzinfo is not None


# ── PromptManager integration ───────────────────────────────────────


class TestPromptManagerWithResolver:
    """PromptManager accepts an optional resolver and exposes resolve()."""

    def test_default_resolver_is_git(self, promptops_repo: Path):
        m = PromptManager(str(promptops_repo))
        assert isinstance(m._resolver, GitResolver)

    def test_accepts_custom_resolver(self, promptops_repo: Path):
        class StubResolver:
            def __init__(self):
                self.calls = []

            def resolve(self, prompt_id, version=None):
                self.calls.append((prompt_id, version))
                return ResolvedPrompt(
                    text="prompt:\n  id: stub\n  template: STUBBED\n",
                    version="stub-v1",
                    commit="stub-sha",
                    resolved_at=datetime.now(timezone.utc),
                    source="stub",
                    prompt_id=prompt_id,
                )

        stub = StubResolver()
        m = PromptManager(str(promptops_repo), resolver=stub)
        assert m._resolver is stub

    def test_resolve_returns_resolved_prompt(self, promptops_repo: Path):
        m = PromptManager(str(promptops_repo))
        r = m.resolve("hello:working")
        assert isinstance(r, ResolvedPrompt)
        assert r.prompt_id == "hello"
        assert r.commit is not None

    def test_resolve_routes_through_custom_resolver(self, promptops_repo: Path):
        class StubResolver:
            def __init__(self):
                self.last_call = None

            def resolve(self, prompt_id, version=None):
                self.last_call = (prompt_id, version)
                return ResolvedPrompt(
                    text="prompt:\n  id: x\n  template: T\n",
                    version=version, commit=None,
                    resolved_at=datetime.now(timezone.utc),
                    source="stub", prompt_id=prompt_id,
                )

        stub = StubResolver()
        m = PromptManager(str(promptops_repo), resolver=stub)
        r = m.resolve("hello:v9")
        assert stub.last_call == ("hello", "v9")
        assert r.source == "stub"


class TestPromptManagerBackwardsCompat:
    """The pre-existing API surface must keep working unchanged."""

    def test_get_prompt_returns_string(self, promptops_repo: Path):
        # Existing v0.2.0 callers expect a rendered string from get_prompt().
        m = PromptManager(str(promptops_repo))
        result = m.get_prompt("hello", {"name": "World"})
        assert isinstance(result, str)
        assert "World" in result

    def test_git_versioning_attribute_still_present(self, promptops_repo: Path):
        # Some callers do manager.git_versioning.has_uncommitted_changes(...)
        m = PromptManager(str(promptops_repo))
        assert hasattr(m, "git_versioning")
        assert hasattr(m.git_versioning, "has_uncommitted_changes")

    def test_list_prompts_still_works(self, promptops_repo: Path):
        m = PromptManager(str(promptops_repo))
        prompts = m.list_prompts()
        assert isinstance(prompts, list)
        assert "hello" in prompts

    def test_init_without_git_raises_via_resolver(self, tmp_path: Path):
        # When no resolver is passed and the path is not a git repo,
        # GitResolver (the default) raises during construction.
        # First create .promptops/prompts/ so the directory check passes,
        # to confirm the failure is from GitResolver, not _validate_setup.
        (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
        with pytest.raises(ValueError, match="git repository"):
            PromptManager(str(tmp_path))
