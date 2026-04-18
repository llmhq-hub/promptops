"""Input validation utilities for PromptOps security."""

import re
from pathlib import Path

# Prompt IDs: alphanumeric, hyphens, underscores. Must start with alphanum.
_PROMPT_ID_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$')

# Version strings: v1.2.3 or semantic keywords
_VERSION_RE = re.compile(r'^v?\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$')
_VERSION_KEYWORDS = frozenset({
    'unstaged', 'working-dir', 'staged', 'working', 'latest', 'head'
})

# Max file size for prompt YAML files (1 MB)
MAX_PROMPT_FILE_SIZE = 1 * 1024 * 1024


def validate_prompt_id(prompt_id: str) -> str:
    """Validate and return prompt_id, or raise ValueError.

    Allowed: alphanumeric characters, hyphens, underscores.
    Must start with an alphanumeric character. Max 128 chars.
    """
    if not prompt_id or not isinstance(prompt_id, str):
        raise ValueError("prompt_id must be a non-empty string")
    if not _PROMPT_ID_RE.match(prompt_id):
        raise ValueError(
            f"Invalid prompt_id '{prompt_id}'. "
            "Must match [a-zA-Z0-9][a-zA-Z0-9_-]{{0,127}} "
            "(alphanumeric, hyphens, underscores; starts with alphanum)."
        )
    return prompt_id


def validate_version(version: str) -> str:
    """Validate a version string, or raise ValueError.

    Accepts semantic versions (v1.2.3) and special keywords
    (unstaged, working-dir, staged, working, latest, head).
    """
    if not version or not isinstance(version, str):
        raise ValueError("version must be a non-empty string")
    if version in _VERSION_KEYWORDS:
        return version
    if not _VERSION_RE.match(version):
        raise ValueError(
            f"Invalid version '{version}'. "
            "Must be a semantic version (e.g. v1.2.3) or one of: "
            f"{', '.join(sorted(_VERSION_KEYWORDS))}"
        )
    return version


def sanitize_path(path: Path, allowed_root: Path) -> Path:
    """Resolve a path and verify it's within allowed_root.

    Returns the resolved path if safe, raises ValueError otherwise.
    """
    resolved = path.resolve()
    root = allowed_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves outside allowed directory '{root}'"
        )
    return resolved


def check_file_size(path: Path, max_size: int = MAX_PROMPT_FILE_SIZE) -> None:
    """Check that a file is within the size limit. Raises ValueError if too large."""
    if path.exists():
        size = path.stat().st_size
        if size > max_size:
            raise ValueError(
                f"File '{path.name}' is {size} bytes, exceeding limit of {max_size} bytes"
            )
