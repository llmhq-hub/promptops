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
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from .errors import (
    E003_PROMPT_NOT_FOUND,
    E004_VERSION_NOT_FOUND,
    E005_GIT_REQUIRED,
    E006_SNAPSHOT_MISSING,
    E007_SNAPSHOT_INVALID,
    E008_SNAPSHOT_SCHEMA_MISMATCH,
    E009_RESOLVER_UNAVAILABLE,
    E012_TEMPLATE_INCLUDE_UNSUPPORTED,
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


# Jinja2 tags that need a template loader. PromptOps renders inside a
# SandboxedEnvironment constructed without one (see core/template.py), so a
# template using any of these cannot render at runtime no matter what. The
# scan below catches them at build time instead of in production.
_UNSUPPORTED_JINJA_TAGS = ("include", "import", "from", "extends")

# Matches a Jinja block tag whose FIRST token is one of the unsupported
# keywords: '{%' plus optional whitespace-control '-', whitespace, keyword,
# then a word boundary. Requiring real block syntax is what keeps the words
# 'include' / 'import' / 'from' / 'extends' in ordinary prose from tripping it.
_UNSUPPORTED_TAG_RE = re.compile(
    r"\{%-?\s*(" + "|".join(_UNSUPPORTED_JINJA_TAGS) + r")\b"
)

# Jinja comments. Stripped before scanning so a tag shown as an example inside
# {# ... #} is not reported. Non-greedy and DOTALL so multi-line comments go too.
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def find_unsupported_includes(text: str) -> List[Tuple[int, str]]:
    """Find Jinja tags that require a template loader.

    Args:
        text: Raw prompt file content (the same string stored as a snapshot
            entry's ``text``).

    Returns:
        A list of ``(line_number, keyword)`` pairs, 1-based, in file order.
        Empty when the text is clean.
    """
    # Blank out comments in place so surviving line numbers stay accurate:
    # replace each comment with its own newlines rather than deleting it.
    def _blank(match: re.Match) -> str:
        return "\n" * match.group(0).count("\n")

    scrubbed = _JINJA_COMMENT_RE.sub(_blank, text)

    findings: List[Tuple[int, str]] = []
    for line_number, line in enumerate(scrubbed.splitlines(), start=1):
        for match in _UNSUPPORTED_TAG_RE.finditer(line):
            findings.append((line_number, match.group(1)))
    return findings


def _check_includes(prompt_id: str, text: str, allow_includes: bool) -> None:
    """Raise E012 for unsupported Jinja tags, or warn when explicitly allowed."""
    findings = find_unsupported_includes(text)
    if not findings:
        return

    where = ", ".join(f"line {line} ({{% {kw} %}})" for line, kw in findings)
    detail = (
        f"Prompt '{prompt_id}' uses a Jinja tag that requires a template "
        f"loader: {where}. PromptOps renders in a sandboxed environment with "
        f"no loader, so this cannot render at runtime."
    )

    if allow_includes:
        logger.warning(
            "[%s] %s Building anyway because --allow-includes was passed; "
            "the resulting snapshot will fail at render time.",
            E012_TEMPLATE_INCLUDE_UNSUPPORTED,
            detail,
        )
        return

    raise PromptOpsError(
        code=E012_TEMPLATE_INCLUDE_UNSUPPORTED,
        message=detail,
        hint=(
            "Inline the included content directly into the template. "
            "If you need to build the snapshot anyway (it will fail at "
            "render time), pass --allow-includes."
        ),
    )


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
    allow_includes: bool = False,
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
        allow_includes: If True, downgrade the E012 unsupported-Jinja-tag
            check from an error to a warning and build anyway. The resulting
            snapshot is known-broken at render time; the flag exists as an
            escape hatch, not a supported configuration.

    Returns:
        The path the snapshot was written to.

    Raises:
        ValueError: If ``repo_path`` is not a git repo. (Snapshots are built
            FROM git; runtime use of the snapshot doesn't need it.)
        PromptOpsError: E012 if any prompt uses a Jinja tag requiring a
            template loader and ``allow_includes`` is False. Nothing is
            written in that case.
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
        # Scan before any file is written, so a rejected build leaves no
        # partial or stale snapshot behind.
        _check_includes(prompt_id, resolved.text, allow_includes)
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
