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
