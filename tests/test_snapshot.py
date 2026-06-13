"""Tests for ``core/snapshot.py`` (Phase 1.5a M3).

Covers:
- ``write_snapshot``: produces a valid JSON file with expected shape
- ``SnapshotResolver``: load + schema validation, resolve() for every
  documented version reference, all error paths
- Round-trip: write_snapshot → SnapshotResolver.resolve returns the same
  text / version / commit that GitResolver would have at that commit
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llmhq_promptops import (
    GitResolver,
    ResolvedPrompt,
    SnapshotResolver,
    write_snapshot,
)
from llmhq_promptops.core.snapshot import (
    SNAPSHOT_FILENAME,
    SNAPSHOT_SCHEMA_VERSION,
)


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt for tests
  id: hello
  model: gpt-4-turbo
  template: 'Hello, {{ name }}!'
variables:
  name:
    type: string
    required: true
"""

SECOND_PROMPT_YAML = """\
prompt:
  description: Farewell prompt
  id: goodbye
  model: gpt-4-turbo
  template: 'Goodbye, {{ name }}.'
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
def promptops_repo(tmp_path: Path) -> Path:
    """Two committed prompts (hello, goodbye), untagged."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts = tmp_path / ".promptops" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "hello.yaml").write_text(SAMPLE_PROMPT_YAML)
    (prompts / "goodbye.yaml").write_text(SECOND_PROMPT_YAML)

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial: two prompts")

    return tmp_path


@pytest.fixture
def tagged_repo(promptops_repo: Path) -> Path:
    """promptops_repo with a v1.0.0 tag on HEAD for cleaner version assertions."""
    _git(promptops_repo, "tag", "v1.0.0")
    return promptops_repo


# ── write_snapshot ──────────────────────────────────────────────────


class TestWriteSnapshot:
    def test_writes_under_default_path(self, promptops_repo: Path):
        path = write_snapshot(str(promptops_repo))
        assert path == promptops_repo / ".promptops" / SNAPSHOT_FILENAME
        assert path.exists()

    def test_writes_to_custom_output(self, promptops_repo: Path, tmp_path: Path):
        out = tmp_path / "alt" / "snap.json"
        path = write_snapshot(str(promptops_repo), output_path=out)
        assert path == out.resolve()
        assert out.exists()

    def test_snapshot_has_expected_top_level_fields(self, promptops_repo: Path):
        path = write_snapshot(str(promptops_repo))
        data = json.loads(path.read_text())
        assert data["schema_version"] == SNAPSHOT_SCHEMA_VERSION
        assert "generated_at" in data
        # tz-aware ISO string
        assert datetime.fromisoformat(data["generated_at"]).tzinfo is not None
        assert "generated_from_commit" in data
        assert len(data["generated_from_commit"]) == 40
        assert "promptops_version" in data
        assert "prompts" in data

    def test_snapshot_includes_every_prompt_under_promptops_prompts(
        self, promptops_repo: Path
    ):
        path = write_snapshot(str(promptops_repo))
        data = json.loads(path.read_text())
        assert set(data["prompts"].keys()) == {"hello", "goodbye"}

    def test_snapshot_entry_shape(self, tagged_repo: Path):
        path = write_snapshot(str(tagged_repo))
        data = json.loads(path.read_text())
        entry = data["prompts"]["hello"]
        assert set(entry.keys()) == {"text", "version", "commit"}
        # Tagged repo → version is the tag, commit is full sha
        assert entry["version"] == "v1.0.0"
        assert entry["commit"] is not None
        assert len(entry["commit"]) == 40
        assert "Hello, {{ name }}!" in entry["text"]

    def test_pretty_is_indented(self, promptops_repo: Path):
        path_pretty = write_snapshot(
            str(promptops_repo),
            output_path=promptops_repo / "pretty.json",
            pretty=True,
        )
        path_packed = write_snapshot(
            str(promptops_repo),
            output_path=promptops_repo / "packed.json",
            pretty=False,
        )
        # Pretty form is larger because of whitespace
        assert path_pretty.stat().st_size > path_packed.stat().st_size
        # Pretty form contains a newline followed by space (indentation)
        assert "\n  " in path_pretty.read_text()

    def test_can_snapshot_specific_commit(self, promptops_repo: Path):
        # Add a second commit so HEAD != initial commit
        (promptops_repo / ".promptops" / "prompts" / "hello.yaml").write_text(
            SAMPLE_PROMPT_YAML.replace("Hello", "Hi")
        )
        _git(promptops_repo, "add", ".")
        _git(promptops_repo, "commit", "--quiet", "-m", "tweak greeting")
        old_sha = _git(promptops_repo, "rev-parse", "HEAD~1")

        path = write_snapshot(str(promptops_repo), commit=old_sha)
        data = json.loads(path.read_text())

        # Snapshot at the older commit should have the original "Hello", not "Hi"
        assert "Hello, {{ name }}!" in data["prompts"]["hello"]["text"]
        assert "Hi, {{ name }}!" not in data["prompts"]["hello"]["text"]

    def test_non_git_repo_rejected(self, tmp_path: Path):
        # Bare directory with .promptops/ but no .git/
        (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
        with pytest.raises(ValueError, match="git repository"):
            write_snapshot(str(tmp_path))


# ── SnapshotResolver: construction + schema validation ──────────────


class TestSnapshotResolverConstruction:
    def test_missing_file_rejected_with_helpful_message(self, tmp_path: Path):
        (tmp_path / ".promptops").mkdir()
        with pytest.raises(ValueError, match="snapshot build"):
            SnapshotResolver(repo_path=str(tmp_path))

    def test_invalid_json_rejected(self, tmp_path: Path):
        (tmp_path / ".promptops").mkdir()
        (tmp_path / ".promptops" / SNAPSHOT_FILENAME).write_text("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            SnapshotResolver(repo_path=str(tmp_path))

    def test_wrong_schema_version_rejected(self, tmp_path: Path):
        (tmp_path / ".promptops").mkdir()
        (tmp_path / ".promptops" / SNAPSHOT_FILENAME).write_text(
            json.dumps({"schema_version": 99, "prompts": {}})
        )
        with pytest.raises(ValueError, match="schema_version=99"):
            SnapshotResolver(repo_path=str(tmp_path))

    def test_missing_prompts_object_rejected(self, tmp_path: Path):
        (tmp_path / ".promptops").mkdir()
        (tmp_path / ".promptops" / SNAPSHOT_FILENAME).write_text(
            json.dumps({"schema_version": SNAPSHOT_SCHEMA_VERSION})
        )
        with pytest.raises(ValueError, match="prompts"):
            SnapshotResolver(repo_path=str(tmp_path))

    def test_accepts_explicit_snapshot_path(self, promptops_repo: Path, tmp_path: Path):
        snap = tmp_path / "snap.json"
        write_snapshot(str(promptops_repo), output_path=snap)
        # Constructor accepts the explicit path even though it lives outside .promptops/
        resolver = SnapshotResolver(snapshot_path=str(snap))
        assert resolver.snapshot_path == snap.resolve()


# ── SnapshotResolver.resolve ────────────────────────────────────────


@pytest.fixture
def tagged_snapshot_resolver(tagged_repo: Path) -> SnapshotResolver:
    write_snapshot(str(tagged_repo))
    return SnapshotResolver(repo_path=str(tagged_repo))


class TestSnapshotResolverResolve:
    def test_returns_resolved_prompt_with_source_snapshot(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello")
        assert isinstance(r, ResolvedPrompt)
        assert r.source == "snapshot"
        assert r.prompt_id == "hello"

    def test_no_version_returns_snapshotted_version(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello")
        assert r.version == "v1.0.0"
        assert "Hello, {{ name }}!" in r.text

    def test_working_alias_returns_snapshotted_version(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello", "working")
        assert r.version == "v1.0.0"

    def test_latest_alias_returns_snapshotted_version(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello", "latest")
        assert r.version == "v1.0.0"

    def test_head_alias_returns_snapshotted_version(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello", "head")
        assert r.version == "v1.0.0"

    def test_matching_specific_version_returns_content(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello", "v1.0.0")
        assert r.version == "v1.0.0"
        assert "Hello" in r.text

    def test_resolved_at_is_timezone_aware(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello")
        assert r.resolved_at.tzinfo is not None
        assert r.resolved_at <= datetime.now(timezone.utc)

    def test_commit_is_full_40_char_sha(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        r = tagged_snapshot_resolver.resolve("hello")
        assert r.commit is not None
        assert len(r.commit) == 40

    def test_untagged_repo_returns_commit_sha_form(
        self, promptops_repo: Path
    ):
        write_snapshot(str(promptops_repo))
        resolver = SnapshotResolver(repo_path=str(promptops_repo))
        r = resolver.resolve("hello")
        assert r.version is not None
        assert r.version.startswith("commit-")


class TestSnapshotResolverErrors:
    def test_unknown_prompt_rejected_with_available_list(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        with pytest.raises(ValueError, match="Available prompts"):
            tagged_snapshot_resolver.resolve("nonexistent")

    def test_invalid_prompt_id_rejected(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        with pytest.raises(ValueError):
            tagged_snapshot_resolver.resolve("../../etc/passwd")

    def test_non_matching_specific_version_rejected_with_snapshotted_version(
        self, tagged_snapshot_resolver: SnapshotResolver
    ):
        with pytest.raises(ValueError, match="v1.0.0"):
            tagged_snapshot_resolver.resolve("hello", "v2.0.0")

    @pytest.mark.parametrize("git_only_ref", ["unstaged", "working-dir", "staged"])
    def test_git_only_version_references_rejected(
        self, tagged_snapshot_resolver: SnapshotResolver, git_only_ref: str
    ):
        with pytest.raises(ValueError, match="git working-tree concept"):
            tagged_snapshot_resolver.resolve("hello", git_only_ref)


# ── Round-trip parity with GitResolver ──────────────────────────────


class TestSnapshotRoundTripWithGit:
    """Build a snapshot, then assert SnapshotResolver returns the same shape
    that GitResolver would have for the same prompt at the same commit.
    """

    def test_text_and_commit_match_git_resolver(self, tagged_repo: Path):
        write_snapshot(str(tagged_repo))
        snap = SnapshotResolver(repo_path=str(tagged_repo))
        git = GitResolver(str(tagged_repo))

        sr = snap.resolve("hello")
        gr = git.resolve("hello", "working")

        assert sr.text == gr.text
        assert sr.commit == gr.commit
        # Versions: both should return v1.0.0 (the tag)
        assert sr.version == gr.version == "v1.0.0"
        # But source identifies which backend resolved it
        assert sr.source == "snapshot"
        assert gr.source == "git"


# ── v0.4.0 security hardening: read-side caps + RecursionError ──────


class TestSnapshotReadSafety:
    """S1 + S4 (v0.4.0): the production-runtime snapshot read path must
    reject oversized and pathologically-nested files cleanly (E007),
    never load multi-MB blobs into memory, never escape as a raw
    traceback."""

    def _write(self, d: Path, text: str) -> Path:
        (d / ".promptops").mkdir(parents=True, exist_ok=True)
        p = d / ".promptops" / SNAPSHOT_FILENAME
        p.write_text(text)
        return p

    def test_oversized_snapshot_rejected(self, tmp_path: Path, monkeypatch):
        from llmhq_promptops import PromptOpsError
        from llmhq_promptops.core import snapshot as snap_mod

        self._write(tmp_path, '{"schema_version": 1, "prompts": {}}')
        # Shrink the ceiling rather than writing 25MB.
        monkeypatch.setattr(snap_mod, "MAX_SNAPSHOT_BYTES", 5)
        with pytest.raises(PromptOpsError, match="byte limit") as exc:
            SnapshotResolver(repo_path=str(tmp_path))
        assert exc.value.code == "PROMPTOPS_E007"

    def test_deeply_nested_json_raises_clean_e007(self, tmp_path: Path):
        from llmhq_promptops import PromptOpsError

        # Deep nesting trips RecursionError inside json.loads; it must be
        # caught and re-raised as E007, not crash with a raw traceback.
        self._write(tmp_path, "[" * 100000 + "]" * 100000)
        with pytest.raises(PromptOpsError) as exc:
            SnapshotResolver(repo_path=str(tmp_path))
        assert exc.value.code == "PROMPTOPS_E007"
