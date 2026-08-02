"""In-process coverage of the hook entry points (v0.6.0).

``test_hooks_e2e.py`` drives real ``git commit`` calls, which is the only way
to catch the class of bug that made this release necessary. The cost is that
the hook runs in a subprocess, so ``coverage`` cannot see it and the modules
read as 39% and 45% covered while being thoroughly exercised.

These tests call ``run()`` and its collaborators directly, in-process. They are
the complement, not the replacement: a green suite here with a red suite there
would mean the units work and the feature does not, which is precisely the
state the project was in for six releases.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmhq_promptops.hooks.post_commit import PostCommitHook
from llmhq_promptops.hooks.pre_commit import PreCommitHook


PROMPT = """\
metadata:
  id: greeting
  version: v1.0.0
template: |
  Hello {{ name }}.
variables:
  name:
    type: string
    required: true
"""

WITH_TIER = """\
metadata:
  id: greeting
  version: v1.0.0
template: |
  Hello {{ name }}, on the {{ tier }} plan.
variables:
  name:
    type: string
    required: true
  tier:
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


def _stage_prompt(repo: Path, body: str = PROMPT) -> Path:
    prompts = repo / ".promptops" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    path = prompts / "greeting.yaml"
    path.write_text(body)
    _git(repo, "add", ".")
    return path


class TestPreCommitRun:
    def test_it_exits_quietly_when_no_prompts_are_staged(self, repo: Path, capsys):
        (repo / "app.py").write_text("print('x')\n")
        _git(repo, "add", ".")

        assert PreCommitHook(str(repo)).run() == 0
        assert capsys.readouterr().err == "", "the no-op path should stay silent"

    def test_it_versions_a_staged_prompt(self, repo: Path):
        path = _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        path.write_text(WITH_TIER)
        _git(repo, "add", ".")

        assert PreCommitHook(str(repo)).run() == 0
        assert "version: v2.0.0" in path.read_text()

    def test_it_restages_the_file_it_rewrote(self, repo: Path):
        """A bump the index does not see would be committed at the old version."""
        path = _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        path.write_text(WITH_TIER)
        _git(repo, "add", ".")
        PreCommitHook(str(repo)).run()

        staged = _git(repo, "show", ":.promptops/prompts/greeting.yaml")
        assert "version: v2.0.0" in staged

    def test_it_blocks_on_an_invalid_prompt(self, repo: Path):
        _stage_prompt(repo, PROMPT.replace("Hello {{ name }}.", "{% if name %}open"))

        assert PreCommitHook(str(repo)).run() == 1

    def test_it_does_not_block_when_configured_not_to(self, repo: Path):
        (repo / ".promptops").mkdir(exist_ok=True)
        (repo / ".promptops" / "config.yaml").write_text(
            "block_on_test_failure: false\n"
        )
        _stage_prompt(repo, PROMPT.replace("Hello {{ name }}.", "{% if name %}open"))

        assert PreCommitHook(str(repo)).run() == 0

    def test_an_unreadable_config_falls_back_loudly(self, repo: Path, capsys):
        (repo / ".promptops").mkdir(exist_ok=True)
        (repo / ".promptops" / "config.yaml").write_text("{[not: yaml\n")

        hook = PreCommitHook(str(repo))

        assert hook.config.get("block_on_test_failure") is True  # the default
        assert "Ignoring unreadable" in capsys.readouterr().err, (
            "silently ignoring a config the user wrote is how you lose their trust"
        )


class TestPostCommitRun:
    def test_it_skips_when_the_commit_touched_no_prompts(self, repo: Path):
        (repo / "app.py").write_text("print('x')\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "chore: app")

        assert PostCommitHook(str(repo)).run() == 0
        assert _git(repo, "tag", "-l") == ""

    def test_it_tags_the_committed_version(self, repo: Path):
        _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        assert PostCommitHook(str(repo)).run() == 0
        assert _git(repo, "tag", "-l") == "prompt-greeting-v1.0.0"

    def test_tagging_twice_is_not_an_error(self, repo: Path):
        _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")
        PostCommitHook(str(repo)).run()

        assert PostCommitHook(str(repo)).run() == 0
        assert _git(repo, "tag", "-l") == "prompt-greeting-v1.0.0"

    def test_reports_are_written_when_enabled(self, repo: Path):
        (repo / ".promptops").mkdir(exist_ok=True)
        (repo / ".promptops" / "config.yaml").write_text("generate_reports: true\n")
        _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        assert PostCommitHook(str(repo)).run() == 0

        reports = repo / ".promptops" / "reports"
        assert (reports / "index.md").exists()
        written = list(reports.glob("*/commit-*-version-changes.md"))
        assert written, "generate_reports was on and nothing was written"
        body = written[0].read_text()
        assert "greeting" in body
        assert "NEW" in body or "PATCH" in body or "MAJOR" in body

    def test_enabled_reports_are_still_not_staged(self, repo: Path):
        """Opting in to reports is not opting in to having them committed."""
        (repo / ".promptops").mkdir(exist_ok=True)
        (repo / ".promptops" / "config.yaml").write_text("generate_reports: true\n")
        _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")
        PostCommitHook(str(repo)).run()

        staged = _git(repo, "diff", "--cached", "--name-only")
        assert staged == "", f"the hook staged files on its own: {staged}"

    def test_the_reported_change_type_matches_the_grader(self, repo: Path):
        path = _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")
        path.write_text(WITH_TIER)
        _git(repo, "add", ".")
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: tier")

        hook = PostCommitHook(str(repo))

        assert hook._detect_change_type(".promptops/prompts/greeting.yaml") == "MAJOR"

    def test_a_prompt_with_no_version_is_not_tagged(self, repo: Path):
        _stage_prompt(repo, "metadata:\n  id: greeting\ntemplate: |\n  Hi.\n")
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")

        assert PostCommitHook(str(repo)).run() == 0
        assert _git(repo, "tag", "-l") == ""

    def test_it_reads_the_legacy_prompt_schema(self, repo: Path):
        _stage_prompt(
            repo,
            "prompt:\n  id: greeting\n  version: v3.1.0\n  template: 'Hi'\n",
        )
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: legacy")

        hook = PostCommitHook(str(repo))

        assert hook._get_prompt_version(".promptops/prompts/greeting.yaml") == "v3.1.0"

    def test_a_deleted_prompt_completes_the_run(self, repo: Path):
        """Nothing to tag and nothing to validate, but not a failure either."""
        _stage_prompt(repo)
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "feat: greeting")
        _git(repo, "rm", "--quiet", ".promptops/prompts/greeting.yaml")
        _git(repo, "commit", "--quiet", "--no-verify", "-m", "chore: drop")

        assert PostCommitHook(str(repo)).run() == 0


class TestVersionRewriteEdges:
    def test_staged_content_falls_back_to_the_working_directory(self, repo: Path):
        """An unstaged file still has content worth reading."""
        prompts = repo / ".promptops" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "greeting.yaml").write_text(PROMPT)  # deliberately not `git add`

        content = PreCommitHook(str(repo))._get_staged_content(
            ".promptops/prompts/greeting.yaml"
        )

        assert content is not None
        assert "id: greeting" in content

    def test_missing_files_report_nothing_rather_than_raising(self, repo: Path):
        assert (
            PreCommitHook(str(repo))._get_staged_content(
                ".promptops/prompts/absent.yaml"
            )
            is None
        )

    def test_a_document_with_no_metadata_section_gains_one(self, repo: Path):
        hook = PreCommitHook(str(repo))

        out = hook._update_version_in_yaml("template: |\n  Hello.\n", "v1.0.0")

        assert out is not None
        assert hook._extract_current_version(out) == "v1.0.0"
        assert "template: |" in out, "the original body must survive the append"

    def test_a_non_mapping_document_is_refused(self, repo: Path):
        assert PreCommitHook(str(repo))._update_version_in_yaml(
            "- just\n- a list\n", "v1.0.0"
        ) is None

    def test_unparseable_yaml_is_refused(self, repo: Path):
        assert PreCommitHook(str(repo))._update_version_in_yaml(
            "metadata: [unclosed\n", "v1.0.0"
        ) is None
