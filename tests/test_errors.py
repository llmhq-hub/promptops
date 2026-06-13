"""Tests for the Tier 2 error system (M9, v0.4.0).

Three layers:

1. ``PromptOpsError`` class contract — fields, rendering, ValueError
   compatibility, doc_url derivation.
2. Raise-site integration — the upgraded sites actually raise
   ``PromptOpsError`` with the documented code.
3. Registry doc sync — every code constant defined in ``core/errors.py``
   has a section in ``docs/error-codes.md`` (and vice versa), so the doc
   can't silently drift from the code.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llmhq_promptops import PromptOpsError
from llmhq_promptops.core import errors as errors_module
from llmhq_promptops.core.errors import (
    DOC_BASE_URL,
    E001_NOT_INITIALIZED,
    E003_PROMPT_NOT_FOUND,
    E004_VERSION_NOT_FOUND,
    E005_GIT_REQUIRED,
    E006_SNAPSHOT_MISSING,
    E007_SNAPSHOT_INVALID,
    E008_SNAPSHOT_SCHEMA_MISMATCH,
    E009_RESOLVER_UNAVAILABLE,
    E010_INVALID_PROMPT_ID,
    E013_INVALID_VERSION_SPEC,
    E016_INVALID_DEPLOY_EVENT,
    E017_NAIVE_TIMESTAMP,
)


# ── Layer 1: class contract ─────────────────────────────────────────


class TestPromptOpsErrorClass:
    def test_is_a_value_error(self):
        """Backwards compat: pre-v0.4.0 `except ValueError` keeps working."""
        err = PromptOpsError(code="PROMPTOPS_E999", message="boom")
        assert isinstance(err, ValueError)

    def test_fields_accessible(self):
        err = PromptOpsError(
            code="PROMPTOPS_E999",
            message="something broke",
            hint="try the other thing",
            doc_url="https://example.com/custom",
        )
        assert err.code == "PROMPTOPS_E999"
        assert err.message == "something broke"
        assert err.hint == "try the other thing"
        assert err.doc_url == "https://example.com/custom"

    def test_str_renders_code_message_hint_docs(self):
        err = PromptOpsError(
            code="PROMPTOPS_E999", message="something broke", hint="do X"
        )
        rendered = str(err)
        assert "[PROMPTOPS_E999]" in rendered
        assert "something broke" in rendered
        assert "Hint: do X" in rendered
        assert "Docs: " in rendered

    def test_str_omits_hint_line_when_no_hint(self):
        err = PromptOpsError(code="PROMPTOPS_E999", message="something broke")
        assert "Hint:" not in str(err)

    def test_doc_url_derived_from_code(self):
        err = PromptOpsError(code="PROMPTOPS_E003", message="x")
        assert err.doc_url == f"{DOC_BASE_URL}#promptops_e003"

    def test_to_dict_shape(self):
        err = PromptOpsError(
            code="PROMPTOPS_E999", message="m", hint="h"
        )
        d = err.to_dict()
        assert d == {
            "code": "PROMPTOPS_E999",
            "message": "m",
            "hint": "h",
            "doc_url": err.doc_url,
        }

    def test_pytest_raises_match_still_works(self):
        """The pattern every pre-v0.4.0 test relies on."""
        with pytest.raises(ValueError, match="something broke"):
            raise PromptOpsError(code="PROMPTOPS_E999", message="something broke")


# ── Layer 2: raise-site integration ─────────────────────────────────


SAMPLE_PROMPT_YAML = """\
prompt:
  description: Greeting prompt for error tests
  id: hello
  model: gpt-4-turbo
  template: 'Hello, {{ name }}!'
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
def git_repo_with_prompt(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    (tmp_path / ".promptops" / "prompts" / "hello.yaml").write_text(
        SAMPLE_PROMPT_YAML
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


def _assert_code(excinfo, code: str):
    assert isinstance(excinfo.value, PromptOpsError)
    assert excinfo.value.code == code
    assert excinfo.value.hint  # every upgraded site ships a hint


class TestRaiseSites:
    def test_e001_not_initialized(self, tmp_path: Path):
        # Needs a git repo: in a bare directory the default GitResolver
        # raises E005 before _validate_setup ever runs. E001 is the
        # "git repo, but promptops never initialized" case.
        from llmhq_promptops import PromptManager

        _git(tmp_path, "init", "--quiet")
        with pytest.raises(PromptOpsError) as exc:
            PromptManager(str(tmp_path))
        _assert_code(exc, E001_NOT_INITIALIZED)

    def test_e003_prompt_not_found_git(self, git_repo_with_prompt: Path):
        from llmhq_promptops import GitResolver

        resolver = GitResolver(str(git_repo_with_prompt))
        with pytest.raises(PromptOpsError) as exc:
            resolver.resolve("nonexistent", "working")
        _assert_code(exc, E003_PROMPT_NOT_FOUND)

    def test_e003_prompt_not_found_snapshot(self, git_repo_with_prompt: Path):
        from llmhq_promptops import SnapshotResolver, write_snapshot

        write_snapshot(str(git_repo_with_prompt))
        resolver = SnapshotResolver(repo_path=str(git_repo_with_prompt))
        with pytest.raises(PromptOpsError) as exc:
            resolver.resolve("nonexistent")
        _assert_code(exc, E003_PROMPT_NOT_FOUND)

    def test_e004_git_only_version_on_snapshot(self, git_repo_with_prompt: Path):
        from llmhq_promptops import SnapshotResolver, write_snapshot

        write_snapshot(str(git_repo_with_prompt))
        resolver = SnapshotResolver(repo_path=str(git_repo_with_prompt))
        with pytest.raises(PromptOpsError) as exc:
            resolver.resolve("hello", "unstaged")
        _assert_code(exc, E004_VERSION_NOT_FOUND)

    def test_e004_pinned_version_mismatch(self, git_repo_with_prompt: Path):
        from llmhq_promptops import SnapshotResolver, write_snapshot

        write_snapshot(str(git_repo_with_prompt))
        resolver = SnapshotResolver(repo_path=str(git_repo_with_prompt))
        with pytest.raises(PromptOpsError) as exc:
            resolver.resolve("hello", "v99.99.99")
        _assert_code(exc, E004_VERSION_NOT_FOUND)

    def test_e005_git_required(self, tmp_path: Path):
        from llmhq_promptops import GitResolver

        with pytest.raises(PromptOpsError) as exc:
            GitResolver(str(tmp_path))
        _assert_code(exc, E005_GIT_REQUIRED)

    def test_e006_snapshot_missing(self, tmp_path: Path):
        from llmhq_promptops import SnapshotResolver

        with pytest.raises(PromptOpsError) as exc:
            SnapshotResolver(repo_path=str(tmp_path))
        _assert_code(exc, E006_SNAPSHOT_MISSING)

    def test_e007_snapshot_invalid_json(self, tmp_path: Path):
        from llmhq_promptops import SnapshotResolver

        (tmp_path / ".promptops").mkdir()
        (tmp_path / ".promptops" / "snapshot.json").write_text("{not json")
        with pytest.raises(PromptOpsError) as exc:
            SnapshotResolver(repo_path=str(tmp_path))
        _assert_code(exc, E007_SNAPSHOT_INVALID)

    def test_e008_schema_mismatch(self, tmp_path: Path):
        from llmhq_promptops import SnapshotResolver

        (tmp_path / ".promptops").mkdir()
        (tmp_path / ".promptops" / "snapshot.json").write_text(
            '{"schema_version": 999, "prompts": {}}'
        )
        with pytest.raises(PromptOpsError) as exc:
            SnapshotResolver(repo_path=str(tmp_path))
        _assert_code(exc, E008_SNAPSHOT_SCHEMA_MISMATCH)

    def test_e009_resolver_unavailable(self, tmp_path: Path):
        from llmhq_promptops import AutoResolver

        with pytest.raises(PromptOpsError) as exc:
            AutoResolver(repo_path=str(tmp_path))
        _assert_code(exc, E009_RESOLVER_UNAVAILABLE)

    def test_e010_invalid_prompt_id(self):
        from llmhq_promptops.core.validation import validate_prompt_id

        with pytest.raises(PromptOpsError) as exc:
            validate_prompt_id("../etc/passwd")
        _assert_code(exc, E010_INVALID_PROMPT_ID)

    def test_e013_invalid_version_spec(self):
        from llmhq_promptops.core.validation import validate_version

        with pytest.raises(PromptOpsError) as exc:
            validate_version("not-a-version")
        _assert_code(exc, E013_INVALID_VERSION_SPEC)

    def test_e016_invalid_deploy_event_naive_timestamp(self):
        from llmhq_promptops import DeployEvent

        with pytest.raises(PromptOpsError) as exc:
            DeployEvent(
                timestamp=datetime(2026, 5, 20, 14, 0),  # naive
                env="prod",
                commit="a" * 40,
                deployed_by="ci",
            )
        _assert_code(exc, E016_INVALID_DEPLOY_EVENT)

    def test_e016_invalid_deploy_event_empty_env(self):
        from llmhq_promptops import DeployEvent

        with pytest.raises(PromptOpsError) as exc:
            DeployEvent(
                timestamp=datetime.now(timezone.utc),
                env="",
                commit="a" * 40,
                deployed_by="ci",
            )
        _assert_code(exc, E016_INVALID_DEPLOY_EVENT)

    def test_e017_naive_timestamp_in_find_at(self, tmp_path: Path):
        from llmhq_promptops import DeployLog

        log = DeployLog(str(tmp_path))
        with pytest.raises(PromptOpsError) as exc:
            log.find_at(datetime(2026, 5, 20, 14, 0))  # naive
        _assert_code(exc, E017_NAIVE_TIMESTAMP)


class TestBlameCliE011:
    """The eng-review-reserved code: blame on an empty deploy log."""

    def test_blame_without_deploy_log_shows_e011(
        self, git_repo_with_prompt: Path, monkeypatch
    ):
        from typer.testing import CliRunner
        from cli.main import app

        monkeypatch.chdir(git_repo_with_prompt)
        runner = CliRunner()
        result = runner.invoke(
            app, ["blame", "--at", "2026-05-20T10:00:00Z"]
        )
        assert result.exit_code == 1
        assert "PROMPTOPS_E011" in result.output
        assert "backfill-deploys" in result.output  # the hint surfaced


# ── Layer 3: registry doc sync ──────────────────────────────────────


class TestRegistryDocSync:
    """docs/error-codes.md and core/errors.py can't silently drift."""

    @pytest.fixture
    def doc_text(self) -> str:
        doc = Path(__file__).parent.parent / "docs" / "error-codes.md"
        assert doc.exists(), "docs/error-codes.md is missing"
        return doc.read_text(encoding="utf-8")

    def _registry_codes(self) -> set:
        return {
            value
            for name, value in vars(errors_module).items()
            if name.startswith("E0") or re.match(r"^E\d{3}_", name)
        }

    def test_every_constant_documented(self, doc_text: str):
        for code in self._registry_codes():
            assert f"## {code}" in doc_text, (
                f"{code} is defined in core/errors.py but has no section "
                f"in docs/error-codes.md"
            )

    def test_every_documented_code_exists_in_registry(self, doc_text: str):
        documented = set(re.findall(r"^## (PROMPTOPS_E\d{3})", doc_text, re.M))
        registry = self._registry_codes()
        orphans = documented - registry
        assert not orphans, (
            f"docs/error-codes.md documents codes missing from "
            f"core/errors.py: {orphans}"
        )

    def test_no_duplicate_code_values(self):
        codes = [
            value
            for name, value in vars(errors_module).items()
            if re.match(r"^E\d{3}_", name)
        ]
        assert len(codes) == len(set(codes)), "duplicate code values in registry"
