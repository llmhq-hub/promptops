"""Tests for ``GitVersioning.version_at_commit`` and blame's version reporting.

The bug this closes (C3 from the v0.4.0 audit): ``promptops blame`` reported a
raw 40-char SHA where a version belongs, while ``promptops history`` reported
``v1.0.0`` for the same prompt in the same repo. The hero command gave a worse
answer than the secondary one.

The subtlety is that this is NOT an exact inverse of ``commit_for_version``. A
deploy commit usually did not touch the prompt being blamed, so asking "which
version is tagged AT this commit" finds nothing. The useful question is "which
version was IN EFFECT at this commit", answered by walking back to the newest
prompt-modifying commit that is an ancestor of the target.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llmhq_promptops.core.git_versioning import GitVersioning
from llmhq_promptops.core.resolver import GitResolver
from cli.main import app


def _yaml(version: str, body: str) -> str:
    return (
        "metadata:\n"
        "  id: policy\n"
        f'  version: "{version}"\n'
        "  description: Policy prompt\n"
        "template: |\n"
        f"  {body}\n"
        "variables:\n"
        "  threshold:\n"
        "    type: string\n"
        "    required: true\n"
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Timeline: unrelated commit, policy v1.0.0, unrelated commit, policy v2.0.0."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Dev")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    prompts = tmp_path / ".promptops" / "prompts"
    prompts.mkdir(parents=True)

    # c0: repo exists, policy does not
    (tmp_path / "README.md").write_text("start\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "chore: init")

    # c1: policy v1.0.0
    (prompts / "policy.yaml").write_text(_yaml("1.0.0", "Approve under {{ threshold }}."))
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "feat: policy v1")
    _git(tmp_path, "tag", "prompt-policy-v1.0.0")

    # c2: unrelated change, policy untouched. This is the shape of a deploy commit.
    (tmp_path / "README.md").write_text("more\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "docs: unrelated")

    # c3: policy v2.0.0
    (prompts / "policy.yaml").write_text(
        _yaml("2.0.0", "Escalate everything above {{ threshold }}.")
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "feat: policy v2")
    _git(tmp_path, "tag", "prompt-policy-v2.0.0")

    return tmp_path


def _sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref)


# ── version_at_commit ───────────────────────────────────────────────


class TestVersionAtCommit:
    def test_returns_the_tag_at_the_commit_that_introduced_it(self, repo: Path):
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("policy", _sha(repo, "HEAD~2")) == "v1.0.0"

    def test_returns_version_in_effect_at_an_unrelated_later_commit(self, repo: Path):
        """The whole point: a deploy commit that never touched the prompt.

        HEAD~1 is the 'docs: unrelated' commit. policy was last changed one
        commit earlier, so v1.0.0 was what was live.
        """
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("policy", _sha(repo, "HEAD~1")) == "v1.0.0"

    def test_returns_the_newer_version_after_it_lands(self, repo: Path):
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("policy", _sha(repo, "HEAD")) == "v2.0.0"

    def test_returns_none_before_the_prompt_existed(self, repo: Path):
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("policy", _sha(repo, "HEAD~3")) is None

    def test_accepts_a_short_sha(self, repo: Path):
        gv = GitVersioning(str(repo))
        short = _sha(repo, "HEAD~1")[:8]
        assert gv.version_at_commit("policy", short) == "v1.0.0"

    def test_unknown_prompt_returns_none(self, repo: Path):
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("ghost", _sha(repo, "HEAD")) is None

    def test_garbage_commit_returns_none_without_raising(self, repo: Path):
        gv = GitVersioning(str(repo))
        assert gv.version_at_commit("policy", "not-a-sha") is None

    def test_untagged_prompt_yields_the_commit_label(self, tmp_path: Path):
        """Untagged prompts get commit-<sha8>, the same label history shows."""
        _git(tmp_path, "init", "--quiet")
        _git(tmp_path, "config", "user.email", "t@e.com")
        _git(tmp_path, "config", "user.name", "Dev")
        _git(tmp_path, "config", "commit.gpgsign", "false")
        prompts = tmp_path / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "policy.yaml").write_text(_yaml("1.0.0", "Hi {{ threshold }}."))
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "--quiet", "-m", "feat: policy")

        gv = GitVersioning(str(tmp_path))
        result = gv.version_at_commit("policy", _sha(tmp_path, "HEAD"))
        assert result is not None
        assert result.startswith("commit-")
        assert len(result) == len("commit-") + 8


# ── GitResolver reports it ──────────────────────────────────────────


class TestResolverReportsVersionNotSha:
    def test_resolving_at_a_sha_reports_the_version(self, repo: Path):
        resolver = GitResolver(str(repo))
        resolved = resolver.resolve("policy", _sha(repo, "HEAD~1"))
        assert resolved.version == "v1.0.0"
        assert resolved.commit == _sha(repo, "HEAD~1")

    def test_explicit_semver_ref_still_echoes_that_version(self, repo: Path):
        resolver = GitResolver(str(repo))
        assert resolver.resolve("policy", "v1.0.0").version == "v1.0.0"

    def test_version_is_never_a_bare_40_char_sha(self, repo: Path):
        resolver = GitResolver(str(repo))
        version = resolver.resolve("policy", _sha(repo, "HEAD")).version
        assert len(version) != 40, f"reported a raw SHA as a version: {version}"


# ── blame CLI ───────────────────────────────────────────────────────


class TestBlameReportsVersion:
    def _record_deploy(self, repo: Path, ref: str) -> None:
        from datetime import datetime, timezone

        from llmhq_promptops.core.deploys import DeployEvent, DeployLog

        DeployLog(str(repo)).append(
            DeployEvent(
                timestamp=datetime.now(timezone.utc),
                env="prod",
                commit=_sha(repo, ref),
                deployed_by="ci",
            )
        )

    def test_blame_shows_semver_not_a_raw_sha(self, repo: Path, monkeypatch):
        self._record_deploy(repo, "HEAD~1")
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(
            app, ["blame", "--at", "now", "--prompt", "policy"]
        )

        assert result.exit_code == 0
        assert "version: v1.0.0" in result.output

    def test_blame_and_history_agree_on_the_version(self, repo: Path, monkeypatch):
        """The inconsistency that made this a bug worth fixing now."""
        self._record_deploy(repo, "HEAD")
        monkeypatch.chdir(repo)

        runner = CliRunner()
        blame = runner.invoke(app, ["blame", "--at", "now", "--prompt", "policy"])
        history = runner.invoke(app, ["history", "policy"])

        assert "version: v2.0.0" in blame.output
        assert "v2.0.0" in history.output
