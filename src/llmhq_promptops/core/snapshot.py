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
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


from .errors import (
    E003_PROMPT_NOT_FOUND,
    E004_VERSION_NOT_FOUND,
    E005_GIT_REQUIRED,
    E006_SNAPSHOT_MISSING,
    E007_SNAPSHOT_INVALID,
    E008_SNAPSHOT_SCHEMA_MISMATCH,
    E009_RESOLVER_UNAVAILABLE,
    PromptOpsError,
)
from .resolver import GitResolver, ResolvedPrompt
from .validation import validate_prompt_id


logger = logging.getLogger(__name__)


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_FILENAME = "snapshot.json"

# Read-side size ceiling for snapshot.json. It is parsed whole into memory
# at construction, in production runtime — the most constrained context.
# 25 MB holds thousands of fat prompt entries; past it the file is almost
# certainly poisoned or corrupted. Mirrors the 1MB single-prompt cap.
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


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

    # A snapshot is a frozen artifact — nothing it serves can change
    # under the caller's feet, so PromptManager may cache everything.
    reads_working_tree = False

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
            raise PromptOpsError(
                code=E006_SNAPSHOT_MISSING,
                message=(
                    f"SnapshotResolver requires {self.snapshot_path} to exist."
                ),
                hint=(
                    "Generate one at build time with 'promptops snapshot "
                    "build' and ship it inside your production image."
                ),
            )

        self._data = self._load_and_validate(self.snapshot_path)

    @staticmethod
    def _load_and_validate(path: Path) -> Dict[str, Any]:
        # Size ceiling BEFORE read: SnapshotResolver runs in production
        # runtime (Docker/serverless), the most resource-constrained
        # context. A poisoned/oversized snapshot must not be loaded whole
        # into memory. Mirrors the 1MB prompt-file cap.
        try:
            size = path.stat().st_size
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise PromptOpsError(
                code=E006_SNAPSHOT_MISSING,
                message=f"Snapshot at {path} disappeared before it could be read.",
                hint="Rebuild it with 'promptops snapshot build'.",
            ) from exc
        if size > MAX_SNAPSHOT_BYTES:
            raise PromptOpsError(
                code=E007_SNAPSHOT_INVALID,
                message=(
                    f"Snapshot at {path} is {size} bytes, exceeding the "
                    f"{MAX_SNAPSHOT_BYTES}-byte limit."
                ),
                hint=(
                    "A snapshot this large is almost certainly corrupted or "
                    "hand-edited. Rebuild it with 'promptops snapshot build'."
                ),
            )

        # Catch RecursionError too: deeply-nested JSON (e.g. [[[...]]])
        # raises it from json.loads, and it would otherwise escape as a raw
        # traceback instead of a clean E007.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise PromptOpsError(
                code=E007_SNAPSHOT_INVALID,
                message=f"Snapshot at {path} is not valid JSON: {exc}",
                hint=(
                    "The file is corrupted or was hand-edited. Rebuild it "
                    "with 'promptops snapshot build'."
                ),
            ) from exc

        if not isinstance(data, dict):
            raise PromptOpsError(
                code=E007_SNAPSHOT_INVALID,
                message=f"Snapshot at {path} must be a JSON object.",
                hint="Rebuild it with 'promptops snapshot build'.",
            )

        schema = data.get("schema_version")
        if schema != SNAPSHOT_SCHEMA_VERSION:
            raise PromptOpsError(
                code=E008_SNAPSHOT_SCHEMA_MISMATCH,
                message=(
                    f"Snapshot at {path} has schema_version={schema!r}, "
                    f"expected {SNAPSHOT_SCHEMA_VERSION}."
                ),
                hint=(
                    "Rebuild the snapshot with the promptops version that "
                    "matches your runtime: 'promptops snapshot build'."
                ),
            )

        if not isinstance(data.get("prompts"), dict):
            raise PromptOpsError(
                code=E007_SNAPSHOT_INVALID,
                message=f"Snapshot at {path} is missing a 'prompts' object.",
                hint="Rebuild it with 'promptops snapshot build'.",
            )

        return data

    def resolve(
        self, prompt_id: str, version: Optional[str] = None
    ) -> ResolvedPrompt:
        validate_prompt_id(prompt_id)

        if version in self._GIT_ONLY_VERSIONS:
            raise PromptOpsError(
                code=E004_VERSION_NOT_FOUND,
                message=(
                    f"SnapshotResolver cannot resolve '{version}' — that is a "
                    f"git working-tree concept and the snapshot is a frozen "
                    f"artifact."
                ),
                hint=(
                    "Use GitResolver in dev for working-tree versions, or "
                    "rebuild the snapshot to pin the content you need."
                ),
            )

        prompts = self._data["prompts"]
        if prompt_id not in prompts:
            available = sorted(prompts.keys())
            raise PromptOpsError(
                code=E003_PROMPT_NOT_FOUND,
                message=(
                    f"Prompt '{prompt_id}' not found in snapshot. "
                    f"Available prompts: {available}"
                ),
                hint=(
                    "The snapshot predates this prompt, or the id is "
                    "misspelled. Rebuild with 'promptops snapshot build'."
                ),
            )

        entry = prompts[prompt_id]
        snapshotted_version = entry.get("version")

        if version is None or version in self._ALIAS_VERSIONS:
            chosen_version = snapshotted_version
        elif version == snapshotted_version:
            chosen_version = version
        else:
            raise PromptOpsError(
                code=E004_VERSION_NOT_FOUND,
                message=(
                    f"Snapshot does not contain version '{version}' for "
                    f"prompt '{prompt_id}'. Snapshotted version: "
                    f"'{snapshotted_version}'."
                ),
                hint=(
                    "Rebuild the snapshot at the desired commit "
                    "('promptops snapshot build --commit <ref>'), or fall "
                    "back to GitResolver where any version resolves."
                ),
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
                raise PromptOpsError(
                    code=E006_SNAPSHOT_MISSING,
                    message=(
                        f"AutoResolver(prefer='snapshot') but no snapshot at "
                        f"{snapshot_path}."
                    ),
                    hint="Run 'promptops snapshot build' first.",
                )
            self._inner = SnapshotResolver(repo_path=str(repo))
        elif prefer == "git":
            if not has_git:
                raise PromptOpsError(
                    code=E005_GIT_REQUIRED,
                    message=(
                        f"AutoResolver(prefer='git') but {repo} is not a git "
                        f"repository (no .git/)."
                    ),
                    hint="Initialize git or switch to prefer='snapshot'.",
                )
            self._inner = GitResolver(repo_path=str(repo))
        else:  # auto
            if has_snapshot:
                self._inner = SnapshotResolver(repo_path=str(repo))
            elif has_git:
                self._inner = GitResolver(repo_path=str(repo))
            else:
                raise PromptOpsError(
                    code=E009_RESOLVER_UNAVAILABLE,
                    message=(
                        f"AutoResolver could not detect a resolver backend at "
                        f"{repo}. Expected either {snapshot_path} or "
                        f"{repo / '.git'} to exist."
                    ),
                    hint=(
                        "In dev: run inside a git repo. In prod: ship "
                        ".promptops/snapshot.json in the image "
                        "('promptops snapshot build' at CI time)."
                    ),
                )

        self.repo_path = repo
        self.mode = "snapshot" if isinstance(self._inner, SnapshotResolver) else "git"
        # Delegate cache-safety to the backend actually chosen.
        self.reads_working_tree = getattr(self._inner, "reads_working_tree", True)

        # One INFO line naming the chosen backend (S5 / D12 from the DX
        # review). When AutoResolver picks the "wrong" backend — a stale
        # snapshot in dev, an unexpected git fallback in prod — this line
        # is the first thing that explains why. Snapshot mode includes
        # build provenance so staleness is visible at a glance.
        if self.mode == "snapshot":
            meta = self._inner._data
            logger.info(
                "promptops resolver: snapshot mode (%s, built %s from commit %s)",
                self._inner.snapshot_path,
                meta.get("generated_at", "unknown"),
                (meta.get("generated_from_commit") or "unknown")[:12],
            )
        else:
            logger.info(
                "promptops resolver: git mode (%s)", repo
            )

    def resolve(
        self, prompt_id: str, version: Optional[str] = None
    ) -> ResolvedPrompt:
        return self._inner.resolve(prompt_id, version)
