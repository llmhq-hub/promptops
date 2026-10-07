"""The installed hooks import PromptOps from one place: the interpreter that
installed them (v0.6.1).

Through v0.6.0 the script that ``promptops hooks install`` wrote into
``.git/hooks/`` began ``#!/usr/bin/env python3`` and, when that interpreter
could not import ``llmhq_promptops``, went looking for it: ``<repo>/src``,
``<repo>/../src`` and ``$PWD/src`` were each pushed onto ``sys.path`` and
whatever ``llmhq_promptops`` package turned up there was imported. The
repository being committed to is not a trusted place to load code from on
every commit (CWE-427), and the fallback fired in exactly the setup
``core/health.py`` documents as common: PromptOps installed in a venv, the
hooks installed from inside it, commits made from a shell where it is not
active.

Two things change. The shebang is now the absolute path of the interpreter
that ran ``hooks install``, so a hook never resolves to a different Python
than the one PromptOps was installed into. And the fallback search is gone:
when that interpreter cannot import PromptOps, the hook says so and stops.

These tests drive the generated script itself, under an interpreter that
genuinely cannot import PromptOps (``python -I -S``: no site-packages, no
PYTHONPATH), because that is the condition the attack needed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cli.commands.hooks import _install_post_commit_hook, _install_pre_commit_hook
from llmhq_promptops.core.health import CheckStatus, run_all_checks


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
    (tmp_path / ".promptops" / "prompts").mkdir(parents=True)
    return tmp_path


def _install(repo: Path) -> Path:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    _install_pre_commit_hook(hooks_dir)
    _install_post_commit_hook(hooks_dir)
    return hooks_dir


def _run_hook_without_promptops(repo: Path, hook: Path) -> subprocess.CompletedProcess:
    """Execute the generated hook under a Python that cannot import PromptOps.

    ``-I`` ignores PYTHONPATH and the user site, ``-S`` skips site-packages,
    so the real install is out of reach and only the standard library and
    whatever the script itself adds to ``sys.path`` are importable. The
    working directory is the repository root, as it is when git runs a hook.
    """
    return subprocess.run(
        [sys.executable, "-I", "-S", str(hook)],
        cwd=repo, capture_output=True, text=True,
    )


def _plant_fake_promptops(repo: Path, marker: Path) -> None:
    """A ``src/llmhq_promptops`` package that proves it ran."""
    pkg = repo / "src" / "llmhq_promptops"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('planted package executed')\n"
    )
    # The hook imports ``llmhq_promptops.hooks.<name>`` after the package, so
    # give it something to find there too; the marker is already written by
    # the time this matters.
    (pkg / "hooks").mkdir()
    (pkg / "hooks" / "__init__.py").write_text("")
    (pkg / "hooks" / "pre_commit.py").write_text("def main():\n    pass\n")
    (pkg / "hooks" / "post_commit.py").write_text("def main():\n    pass\n")


# ── the hook is bound to the interpreter that installed it ──────────


class TestHookInterpreter:
    @pytest.mark.parametrize("name", ["pre-commit", "post-commit"])
    def test_shebang_is_the_installing_interpreter(self, repo: Path, name: str):
        hooks_dir = _install(repo)

        first_line = (hooks_dir / name).read_text().splitlines()[0]

        assert first_line == f"#!{sys.executable}", first_line

    @pytest.mark.parametrize("name", ["pre-commit", "post-commit"])
    def test_hook_does_not_search_the_repository_for_promptops(
        self, repo: Path, name: str
    ):
        hooks_dir = _install(repo)

        script = (hooks_dir / name).read_text()

        assert "sys.path.insert" not in script
        assert "Path.cwd()" not in script

    @pytest.mark.parametrize("name", ["pre-commit", "post-commit"])
    def test_hook_still_carries_the_markers_the_cli_recognizes(
        self, repo: Path, name: str
    ):
        """``hooks status`` / ``uninstall`` identify our hooks by content."""
        from cli.commands.hooks import _is_promptops_hook, _test_hook_installation

        hooks_dir = _install(repo)

        assert _is_promptops_hook(hooks_dir / name)
        assert _test_hook_installation(hooks_dir / name)


# ── repository content is not a code source ─────────────────────────


class TestRepositoryContentIsNeverImported:
    @pytest.mark.parametrize("name", ["pre-commit", "post-commit"])
    def test_a_planted_src_package_is_not_imported(
        self, repo: Path, tmp_path: Path, name: str
    ):
        """The reproduced exploit, as a regression test.

        Through v0.6.0 this imported ``<repo>/src/llmhq_promptops`` and ran
        its ``__init__`` as the committing user.
        """
        hooks_dir = _install(repo)
        marker = tmp_path / "marker"
        _plant_fake_promptops(repo, marker)

        _run_hook_without_promptops(repo, hooks_dir / name)

        assert not marker.exists(), "the hook imported code from the repository"

    def test_pre_commit_without_promptops_blocks_the_commit_and_says_how_to_fix_it(
        self, repo: Path
    ):
        """The not-found branch used to raise NameError on an undefined ``cwd``
        before it reached the recovery steps, so the user saw a traceback and
        never the fix."""
        hooks_dir = _install(repo)

        result = _run_hook_without_promptops(repo, hooks_dir / "pre-commit")

        assert result.returncode == 1
        assert "NameError" not in result.stderr
        assert "pip install llmhq-promptops" in result.stderr
        assert "promptops hooks install" in result.stderr

    def test_pre_commit_names_the_interpreter_it_could_not_import_from(
        self, repo: Path
    ):
        """The one fact that explains the failure, since the shebang decides it."""
        hooks_dir = _install(repo)

        result = _run_hook_without_promptops(repo, hooks_dir / "pre-commit")

        assert sys.executable in result.stderr

    def test_post_commit_without_promptops_warns_and_does_not_fail(
        self, repo: Path
    ):
        """Post-commit work (tags, reports) is best-effort: the commit already
        happened, so a missing install is reported, not fatal."""
        hooks_dir = _install(repo)

        result = _run_hook_without_promptops(repo, hooks_dir / "post-commit")

        assert result.returncode == 0
        assert "NameError" not in result.stderr
        assert "PromptOps" in result.stderr


# ── doctor refuses the old script ───────────────────────────────────


def _check(repo: Path, name: str):
    return next(c for c in run_all_checks(str(repo)) if c.name == name)


class TestDoctorRejectsHooksThatSearchTheRepository:
    def test_a_pre_0_6_1_hook_fails_the_hooks_check(self, repo: Path):
        """A hook installed by an earlier release still runs, so an
        existence-and-interpreter check would call it healthy. It loads code
        from the working tree on every commit; that is broken, not a choice."""
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        old_style = (
            f"#!{sys.executable}\n"
            "# PromptOps pre-commit hook\n"
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))\n"
            "import llmhq_promptops\n"
        )
        (hooks_dir / "pre-commit").write_text(old_style)
        (hooks_dir / "pre-commit").chmod(0o755)

        check = _check(repo, "hooks")

        assert check.status is CheckStatus.FAIL, check.message
        assert "hooks install" in (check.hint or "")

    def test_a_freshly_installed_hook_passes_the_hooks_check(self, repo: Path):
        _install(repo)

        check = _check(repo, "hooks")

        assert check.status is CheckStatus.OK, check.message
