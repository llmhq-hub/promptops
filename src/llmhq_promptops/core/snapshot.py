"""Build-time prompt snapshot for production runtime without ``.git/``.

Phase 1.5a M3 introduces a pinned, JSON-encoded snapshot of every prompt at a
specific commit. Production deployments (Docker images, serverless bundles,
read-only filesystems) can ship this single file and resolve prompts without
needing a git working tree.

Three pieces live in this module:

- ``write_snapshot``  — writes ``.promptops/snapshot.json`` for a given commit.
- ``SnapshotResolver``— implements the ``Resolver`` Protocol by reading from
  the snapshot. No git required at runtime.
- ``AutoResolver``    — auto-picks ``SnapshotResolver`` when the file exists,
  otherwise falls back to ``GitResolver``. The recommended production setup
  is ``PromptManager(resolver=AutoResolver(repo_path))`` so the same code
  works in dev (with .git/) and prod (snapshot-only).

Snapshot file shape (schema_version=1):

    {
      "schema_version": 1,
      "generated_at": "2026-05-27T12:00:00+00:00",
      "generated_from_commit": "abc...",   (or null if working tree)
      "promptops_version": "0.3.0",
      "prompts": {
        "<prompt_id>": {
          "text": "<raw yaml content>",
          "version": "v1.2.3" | "commit-abc12345" | "working",
          "commit": "abc..." | null
        },
        ...
      }
    }

Note on naming: ``version`` in each prompt entry is the *resolved* version
returned by the underlying resolver at build time (a real semver if tagged,
``commit-<sha>`` otherwise — same string the GitResolver would have produced
for that commit).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .resolver import GitResolver, ResolvedPrompt
from .validation import validate_prompt_id


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_FILENAME = "snapshot.json"


def _promptops_version() -> str:
    """Best-effort lookup of the running package version. Falls back gracefully."""
    try:
        from .. import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def write_snapshot(
    repo_path: str = ".",
    output_path: Optional[Path] = None,
    commit: Optional[str] = None,
    pretty: bool = False,
) -> Path:
    """Build and write a snapshot of every prompt under ``.promptops/prompts/``.

    Args:
        repo_path: Path to the repository root.
        output_path: Where to write the snapshot file. Defaults to
            ``<repo>/.promptops/snapshot.json``.
        commit: Resolve each prompt at this commit. Defaults to ``"working"``
            (HEAD content). Pass an explicit SHA or tag to pin to that point.
        pretty: If True, write with 2-space indentation. Default packs the
            output for smaller production images.

    Returns:
        The path the snapshot was written to.

    Raises:
        ValueError: If ``repo_path`` is not a git repo. (Snapshots are built
            FROM git; runtime use of the snapshot doesn't need it.)
    """
    repo = Path(repo_path).resolve()
    if output_path is None:
        output_path = repo / ".promptops" / SNAPSHOT_FILENAME
    else:
        output_path = Path(output_path).resolve()

    git_resolver = GitResolver(str(repo))

    # The resolver version string GitResolver expects: "working" means HEAD
    # working tree content (which is the natural "build snapshot from now"
    # default). Callers can pin to a specific commit/tag by passing it
    # through ``commit``; the resolver accepts both tag versions and SHAs.
    version_ref = commit if commit is not None else "working"

    prompts_dict: Dict[str, Dict[str, Any]] = {}
    for prompt_id in sorted(git_resolver._git.list_available_prompts()):
        resolved = git_resolver.resolve(prompt_id, version_ref)
        prompts_dict[prompt_id] = {
            "text": resolved.text,
            "version": resolved.version,
            "commit": resolved.commit,
        }

    # Capture the build-time commit explicitly so the snapshot is
    # self-describing even when version_ref was "working" (which doesn't
    # carry a commit in ResolvedPrompt). Use HEAD as the source of truth.
    try:
        generated_from_commit: Optional[str] = git_resolver._git.repo.head.commit.hexsha
    except Exception:
        generated_from_commit = None

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_from_commit": generated_from_commit,
        "promptops_version": _promptops_version(),
        "prompts": prompts_dict,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp file + os.replace. Matches the pattern used elsewhere
    # in this codebase (see hooks/pre_commit.py:_write_file) so concurrent
    # readers never see a half-written snapshot.
    fd, tmp_path = tempfile.mkstemp(
        dir=output_path.parent, prefix=".snapshot_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(snapshot, f, indent=2, sort_keys=False)
            else:
                json.dump(snapshot, f, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_path


class SnapshotResolver:
    """Resolver that reads from a pre-built ``.promptops/snapshot.json``.

    Production-runtime resolver. No git required. Pair with
    ``promptops snapshot build`` at CI time.

    Version reference semantics:

    - ``None``, ``"working"``, ``"latest"``, ``"head"``: return the pinned
      snapshot version. (At snapshot build time these were equivalent to
      "the working tree", so we honour that mapping at runtime.)
    - ``"unstaged"``, ``"working-dir"``, ``"staged"``: these are git-only
      concepts. Raises ``ValueError`` — a snapshot is a frozen artifact.
    - Specific version (e.g. ``"v1.2.3"``): returns the prompt only if the
      pinned version matches. Otherwise raises with the snapshotted
      version mentioned, so callers know what they have.
    """

    _GIT_ONLY_VERSIONS = {"unstaged", "working-dir", "staged"}
    _ALIAS_VERSIONS = {"working", "latest", "head"}

    def __init__(
        self,
        snapshot_path: Optional[str] = None,
        repo_path: str = ".",
    ):
        if snapshot_path is None:
            self.snapshot_path = (
                Path(repo_path).resolve() / ".promptops" / SNAPSHOT_FILENAME
            )
        else:
            self.snapshot_path = Path(snapshot_path).resolve()

        if not self.snapshot_path.exists():
            raise ValueError(
                f"SnapshotResolver requires {self.snapshot_path} to exist. "
                f"Generate one at build time with 'promptops snapshot build'."
            )

        self._data = self._load_and_validate(self.snapshot_path)

    @staticmethod
    def _load_and_validate(path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Snapshot at {path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(f"Snapshot at {path} must be a JSON object.")

        schema = data.get("schema_version")
        if schema != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"Snapshot at {path} has schema_version={schema!r}, "
                f"expected {SNAPSHOT_SCHEMA_VERSION}. Rebuild with the "
                f"matching promptops version."
            )

        if not isinstance(data.get("prompts"), dict):
            raise ValueError(
                f"Snapshot at {path} is missing a 'prompts' object."
            )

        return data

    def resolve(
        self, prompt_id: str, version: Optional[str] = None
    ) -> ResolvedPrompt:
        validate_prompt_id(prompt_id)

        if version in self._GIT_ONLY_VERSIONS:
            raise ValueError(
                f"SnapshotResolver cannot resolve '{version}' — that is a "
                f"git working-tree concept and the snapshot is a frozen "
                f"artifact. Use GitResolver if you need it, or rebuild the "
                f"snapshot."
            )

        prompts = self._data["prompts"]
        if prompt_id not in prompts:
            available = sorted(prompts.keys())
            raise ValueError(
                f"Prompt '{prompt_id}' not found in snapshot. "
                f"Available prompts: {available}"
            )

        entry = prompts[prompt_id]
        snapshotted_version = entry.get("version")

        if version is None or version in self._ALIAS_VERSIONS:
            chosen_version = snapshotted_version
        elif version == snapshotted_version:
            chosen_version = version
        else:
            raise ValueError(
                f"Snapshot does not contain version '{version}' for "
                f"prompt '{prompt_id}'. Snapshotted version: "
                f"'{snapshotted_version}'. Rebuild the snapshot at the "
                f"desired commit, or fall back to GitResolver."
            )

        return ResolvedPrompt(
            text=entry["text"],
            version=chosen_version,
            commit=entry.get("commit"),
            resolved_at=datetime.now(timezone.utc),
            source="snapshot",
            prompt_id=prompt_id,
        )


class AutoResolver:
    """Auto-detects ``SnapshotResolver`` vs ``GitResolver`` at construction time.

    The recommended runtime entry point:

        from llmhq_promptops import PromptManager, AutoResolver

        manager = PromptManager(resolver=AutoResolver(repo_path="."))

    Detection (when ``prefer="auto"``):

    1. If ``.promptops/snapshot.json`` exists → ``SnapshotResolver``.
    2. Else if ``.git/`` exists → ``GitResolver``.
    3. Else: raise ``ValueError`` with both options spelled out.

    Override the auto behaviour by passing ``prefer="snapshot"`` or
    ``prefer="git"``. The chosen mode is exposed via ``self.mode``.
    """

    _VALID_PREFER = {"auto", "snapshot", "git"}

    def __init__(self, repo_path: str = ".", prefer: str = "auto"):
        if prefer not in self._VALID_PREFER:
            raise ValueError(
                f"AutoResolver(prefer={prefer!r}) is invalid. "
                f"Use one of: {sorted(self._VALID_PREFER)}."
            )

        repo = Path(repo_path).resolve()
        snapshot_path = repo / ".promptops" / SNAPSHOT_FILENAME
        has_snapshot = snapshot_path.exists()
        has_git = (repo / ".git").exists()

        if prefer == "snapshot":
            if not has_snapshot:
                raise ValueError(
                    f"AutoResolver(prefer='snapshot') but no snapshot at "
                    f"{snapshot_path}. Run 'promptops snapshot build' first."
                )
            self._inner = SnapshotResolver(repo_path=str(repo))
        elif prefer == "git":
            if not has_git:
                raise ValueError(
                    f"AutoResolver(prefer='git') but {repo} is not a git "
                    f"repository (no .git/). Initialize git or switch "
                    f"to prefer='snapshot'."
                )
            self._inner = GitResolver(repo_path=str(repo))
        else:  # auto
            if has_snapshot:
                self._inner = SnapshotResolver(repo_path=str(repo))
            elif has_git:
                self._inner = GitResolver(repo_path=str(repo))
            else:
                raise ValueError(
                    f"AutoResolver could not detect a resolver backend at "
                    f"{repo}. Expected either {snapshot_path} or "
                    f"{repo / '.git'} to exist."
                )

        self.repo_path = repo
        self.mode = "snapshot" if isinstance(self._inner, SnapshotResolver) else "git"

    def resolve(
        self, prompt_id: str, version: Optional[str] = None
    ) -> ResolvedPrompt:
        return self._inner.resolve(prompt_id, version)
