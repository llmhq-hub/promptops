"""Resolver Protocol and implementations for prompt resolution.

Phase 1.5a introduces a pluggable resolver layer between PromptManager and
the underlying source of prompt content. Today, GitResolver wraps the existing
GitVersioning class. Phase 1.5a's M3 will add SnapshotResolver (reads
snapshot.json for production runtime) and AutoResolver (auto-detects env).

The Resolver Protocol is the single integration point. Consumers needing
provenance metadata (which version, which commit, when resolved) call
`resolver.resolve()` and receive a `ResolvedPrompt`. Consumers needing only
the rendered string still go through `PromptManager.get_prompt()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from .errors import (
    E003_PROMPT_NOT_FOUND,
    E005_GIT_REQUIRED,
    PromptOpsError,
)
from .git_versioning import GitVersioning
from .validation import validate_prompt_id


@dataclass(frozen=True)
class ResolvedPrompt:
    """A prompt resolved to its content + provenance metadata.

    `text` is the raw YAML content (NOT rendered). Callers needing a rendered
    string should use `PromptManager.get_prompt()` which renders via Jinja2.

    Provenance fields enable the incident archaeology hero use case:
    knowing which version + commit was active at a given moment.
    """

    text: str
    version: Optional[str]
    commit: Optional[str]
    resolved_at: datetime
    source: str
    prompt_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "version": self.version,
            "commit": self.commit,
            "resolved_at": self.resolved_at.isoformat(),
            "source": self.source,
            "prompt_id": self.prompt_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolvedPrompt":
        return cls(
            text=data["text"],
            version=data.get("version"),
            commit=data.get("commit"),
            resolved_at=datetime.fromisoformat(data["resolved_at"]),
            source=data["source"],
            prompt_id=data["prompt_id"],
        )


@runtime_checkable
class Resolver(Protocol):
    """Resolves a prompt_id (+ optional version) to a ResolvedPrompt.

    Implementations:
        GitResolver: reads from git history. Requires .git/.
        SnapshotResolver: reads from .promptops/snapshot.json (Phase 1.5a M3).
        AutoResolver: auto-detects which to use (Phase 1.5a M3).
    """

    def resolve(self, prompt_id: str, version: Optional[str] = None) -> ResolvedPrompt:
        ...


class GitResolver:
    """Resolver that reads prompt content from git history.

    Wraps the existing GitVersioning class. Requires .git/ to be present.
    Raises ValueError on initialization if the path is not a git repo.
    """

    # Working-tree versions (None/unstaged/staged) read mutable disk
    # state — PromptManager bypasses its template cache for them.
    reads_working_tree = True

    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path).resolve()
        self._git = GitVersioning(repo_path)
        if not self._git.is_git_repo():
            raise PromptOpsError(
                code=E005_GIT_REQUIRED,
                message=(
                    f"GitResolver requires a git repository. "
                    f"{self.repo_path} is not one."
                ),
                hint=(
                    "Initialize git first ('git init'), or use "
                    "SnapshotResolver/AutoResolver in environments without "
                    ".git/ (e.g. production containers shipping snapshot.json)."
                ),
            )

    def resolve(self, prompt_id: str, version: Optional[str] = None) -> ResolvedPrompt:
        validate_prompt_id(prompt_id)

        text = self._git.get_prompt_at_version(prompt_id, version)
        if text is None:
            available = self._git.list_available_prompts()
            raise PromptOpsError(
                code=E003_PROMPT_NOT_FOUND,
                message=(
                    f"Prompt '{prompt_id}' not found at version "
                    f"'{version or 'default'}'. Available prompts: {available}"
                ),
                hint=(
                    "Check the prompt id spelling, or see available prompts "
                    "with 'promptops test status'. If the prompt is new and "
                    "uncommitted, resolve it with version ':unstaged'."
                ),
            )

        commit_sha: Optional[str] = None
        resolved_version: Optional[str] = version

        if version is None or version in ("unstaged", "working-dir"):
            # Working tree state — no clean commit reference.
            commit_sha = None
            resolved_version = version
        elif version in ("working", "latest", "head"):
            try:
                commit_sha = self._git.repo.head.commit.hexsha
            except Exception:
                commit_sha = None
            resolved_version = self._git.get_latest_version(prompt_id)
        elif version == "staged":
            commit_sha = None
            resolved_version = "staged"
        else:
            # Specific version (v1.2.3 etc.) via the public lookup
            # (promoted from a private method in v0.4.0).
            commit_sha = self._git.commit_for_version(prompt_id, version)

            # Report a version label, not whatever ref the caller happened to
            # pass. When `version` is already a semver this returns the same
            # string; when it is a commit SHA (which is what `promptops blame`
            # passes, straight from the deploy log) this turns it into the
            # version that was actually live at that commit. Without this,
            # blame printed a bare 40-char SHA under "version:" while
            # `promptops history` printed v1.2.3 for the same prompt.
            resolved_version = version
            if commit_sha:
                label = self._git.version_at_commit(prompt_id, commit_sha)
                if label:
                    resolved_version = label

        return ResolvedPrompt(
            text=text,
            version=resolved_version,
            commit=commit_sha,
            resolved_at=datetime.now(timezone.utc),
            source="git",
            prompt_id=prompt_id,
        )
