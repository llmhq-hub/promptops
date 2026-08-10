"""Regression tests for package-level metadata invariants.

History: through v0.1.x and v0.2.0, ``llmhq_promptops.__version__`` was
stuck at ``"0.1.0"`` while the package itself shipped under newer numbers
on PyPI (the v0.3.0 CHANGELOG owns the fix). The desync was invisible
because nothing tested it.

This file pins the invariants that would have caught that drift:
``__version__`` agrees with installed package metadata, and the public
API surface stays exported.
"""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _repo_file(*parts: str) -> Path:
    """A path in the source checkout, skipping the test if it is absent.

    The sdist ships ``tests/`` but not the repository's top-level files, so
    these checks cannot run from an unpacked tarball. They guard the
    repository against drift, which is not a property of the installed
    package.
    """
    path = REPO_ROOT.joinpath(*parts)
    if not path.exists():
        pytest.skip(f"{'/'.join(parts)} is not shipped in the sdist; repo-only check")
    return path


def _pyproject_version() -> str:
    """The version declared in ``[project]``, read without installing."""
    text = _repo_file("pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 has no tomllib
        project = re.search(r"^\[project\]$(.*?)^\[", text, re.MULTILINE | re.DOTALL)
        assert project, "no [project] table in pyproject.toml"
        match = re.search(r'^version\s*=\s*"([^"]+)"', project.group(1), re.MULTILINE)
        assert match, "no version in [project]"
        return match.group(1)
    return tomllib.loads(text)["project"]["version"]


def test_version_string_matches_installed_metadata():
    """``__version__`` must equal the version PyPI/pip reports.

    If you bump one, bump the other. Catches the v0.1.0→0.2.0 desync
    class of bugs at test time.
    """
    import llmhq_promptops

    installed = importlib.metadata.version("llmhq-promptops")
    assert llmhq_promptops.__version__ == installed, (
        f"__version__ ({llmhq_promptops.__version__!r}) does not match "
        f"installed package metadata ({installed!r}). Bump both: "
        f"src/llmhq_promptops/__init__.py AND pyproject.toml."
    )


def test_version_string_matches_pyproject():
    """``__version__`` must equal ``pyproject.toml``, independent of install state.

    The installed-metadata check above cannot force a release bump: with both
    files at the old version and an install to match, it passes, and it only
    fires once you bump one file and forget to reinstall. This one reads the
    source of truth off disk, so a half-finished bump fails immediately.
    """
    import llmhq_promptops

    declared = _pyproject_version()
    assert llmhq_promptops.__version__ == declared, (
        f"__version__ ({llmhq_promptops.__version__!r}) does not match "
        f"pyproject.toml ({declared!r}). Bump both."
    )


@pytest.mark.parametrize(
    "path",
    [
        (".pre-commit-hooks.yaml",),
        ("examples", "github-actions", "README.md"),
    ],
)
def test_documented_precommit_rev_matches_this_version(path):
    """A documented ``rev:`` must name a tag where these hooks exist.

    The pre-0.5.0 snippets pinned ``rev: v0.4.0``, a tag at which neither
    ``.pre-commit-hooks.yaml`` nor ``promptops doctor`` existed, so copying
    the documented config gave a hard pre-commit failure. Pinning the pin to
    ``__version__`` means the release bump cannot leave it behind.
    """
    import llmhq_promptops

    text = _repo_file(*path).read_text(encoding="utf-8")
    revs = set(re.findall(r"^\s*#?\s*rev:\s*(\S+)", text, re.MULTILINE))
    assert revs, f"no rev: pin found in {'/'.join(path)}"
    expected = f"v{llmhq_promptops.__version__}"
    assert revs == {expected}, (
        f"{'/'.join(path)} documents rev {sorted(revs)} but this is "
        f"{expected}. A rev older than the release does not have these hooks."
    )


def test_public_api_surface_is_exported():
    """Pin the public API. If we ever remove a name accidentally,
    adopters' imports break — this test catches it before release.
    """
    import llmhq_promptops

    expected = {
        "PromptManager",
        "get_prompt",
        "get_template",
        "get_prompt_manager",
        "PromptTemplate",
        "PromptMetadata",
        "VariableDefinition",
        "GitVersioning",
        "Resolver",
        "ResolvedPrompt",
        "GitResolver",
        "DeployEvent",
        "DeployLog",
        "SnapshotResolver",
        "AutoResolver",
        "write_snapshot",
    }
    missing = expected - set(llmhq_promptops.__all__)
    assert not missing, f"Public API names missing from __all__: {missing}"

    # Every name in __all__ must be importable.
    for name in llmhq_promptops.__all__:
        assert hasattr(llmhq_promptops, name), (
            f"__all__ advertises {name!r} but the attribute is not present"
        )


def test_the_cli_can_report_its_own_version():
    """A user upgrading has to be able to confirm what they are running.

    There was no way to ask: no `promptops version` command and no
    `--version` flag, so "did the upgrade take" could only be answered from
    outside the tool. That is a poor answer for a tool whose whole job is
    telling you which version of something is in effect.
    """
    from typer.testing import CliRunner

    import llmhq_promptops
    from cli.main import app

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert llmhq_promptops.__version__ in result.output


def test_the_short_version_flag_works_too():
    from typer.testing import CliRunner

    import llmhq_promptops
    from cli.main import app

    result = CliRunner().invoke(app, ["-V"])

    assert result.exit_code == 0, result.output
    assert llmhq_promptops.__version__ in result.output
