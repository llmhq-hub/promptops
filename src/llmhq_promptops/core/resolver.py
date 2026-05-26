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

    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path).resolve()
        self._git = GitVersioning(repo_path)
        if not self._git.is_git_repo():
            raise ValueError(
                f"GitResolver requires a git repository. "
                f"{self.repo_path} is not one. "
                f"Initialize git first or use a different resolver."
            )

    def resolve(self, prompt_id: str, version: Optional[str] = None) -> ResolvedPrompt:
        validate_prompt_id(prompt_id)

        text = self._git.get_prompt_at_version(prompt_id, version)
        if text is None:
            available = self._git.list_available_prompts()
            raise ValueError(
                f"Prompt '{prompt_id}' not found at version '{version or 'default'}'. "
                f"Available prompts: {available}"
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
            # Specific version (v1.2.3 etc.). Private access to existing API;
            # promote to public in a follow-up if more resolvers need it.
            commit_sha = self._git._resolve_version_to_commit(prompt_id, version)
            resolved_version = version

        return ResolvedPrompt(
            text=text,
            version=resolved_version,
            commit=commit_sha,
            resolved_at=datetime.now(timezone.utc),
            source="git",
            prompt_id=prompt_id,
        )
