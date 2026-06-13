"""Deploy event log for incident archaeology.

Phase 1.5a M4 introduces an append-only log at ``.promptops/deploys.jsonl``
recording every production deploy: which environment, which commit, when,
and by whom. The log is the bridge between the Resolver layer (M1, M3) and
the ``promptops blame --at <timestamp>`` hero feature (M5):

    blame --at T  →  DeployLog.find_at(T, env="prod")  →  ResolvedPrompt at that commit

The file is committed alongside prompt source so the audit trail moves
with the repo. Each line is one JSON object; reads tolerate malformed
or empty lines (they are skipped with a warning).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from .errors import (
    E016_INVALID_DEPLOY_EVENT,
    E017_NAIVE_TIMESTAMP,
    PromptOpsError,
)


logger = logging.getLogger(__name__)


_DEPLOY_LOG_FILENAME = "deploys.jsonl"

# POSIX guarantees O_APPEND writes below PIPE_BUF (4096 bytes) are atomic.
# Cap serialized events under that so concurrent CI deploys can never
# interleave half-written lines. 4000 leaves headroom for the newline.
# Enforced on the *append* path (where atomicity matters), NOT on read:
# a valid pre-cap event already on disk must still parse, not be
# silently reclassified as malformed.
MAX_EVENT_BYTES = 4000

# Hard ceiling on the whole deploy log for the read path. deploys.jsonl is
# committed to the repo, so any PR contributor can append to it; an
# unbounded file would be fully loaded + sorted into memory by every
# blame/list/find_at call (DoS in CI). 50 MB is ~250k normal events —
# far past any real deploy history, comfortably below an OOM.
MAX_DEPLOY_LOG_BYTES = 50 * 1024 * 1024

# Sentinel cache key meaning "the log file is absent". Distinct from any
# real (mtime_ns, size) tuple, so a previously-cached present-file read is
# invalidated the moment the file disappears (see read()).
_MISSING_LOG = object()

# A git commit SHA: 7-64 hex chars (40 for SHA-1, 64 for SHA-256, short
# forms down to 7). Deploy commits land in blame's resolver path, so a
# malformed value from an attacker-appendable log shouldn't reach git.
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


@dataclass(frozen=True)
class DeployEvent:
    """A single record in the deploy event log.

    ``timestamp`` is always timezone-aware UTC. ``commit`` is the full
    40-char SHA. ``metadata`` is an arbitrary flat map of strings (the
    log is not a structured event store; complex shapes should be encoded
    by the caller).
    """

    timestamp: datetime
    env: str
    commit: str
    deployed_by: str
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message="DeployEvent.timestamp must be timezone-aware (UTC).",
                hint=(
                    "Use datetime.now(timezone.utc), not datetime.utcnow()."
                ),
            )
        if not self.env or not self.env.strip():
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message="DeployEvent.env must not be empty.",
                hint="Pass the target environment, e.g. env='prod'.",
            )
        if not self.commit or not self.commit.strip():
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message="DeployEvent.commit must not be empty.",
                hint=(
                    "Pass the deployed commit SHA, e.g. from "
                    "'git rev-parse HEAD' in your CI step."
                ),
            )
        if not _SHA_RE.match(self.commit.strip()):
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message=(
                    f"DeployEvent.commit {self.commit!r} is not a git SHA "
                    f"(expected 7-64 hex chars)."
                ),
                hint=(
                    "Pass a real commit hash, e.g. from "
                    "'git rev-parse HEAD'. Short SHAs (>=7 chars) are fine."
                ),
            )
        # NOTE: the MAX_EVENT_BYTES atomicity cap is enforced in
        # DeployLog.append (the write path), NOT here. A DeployEvent is a
        # valid value object at any size; only *appending* it relies on
        # single-syscall atomicity. Enforcing here would make from_dict
        # reject valid pre-cap events on read.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "env": self.env,
            "commit": self.commit,
            "deployed_by": self.deployed_by,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeployEvent":
        ts_raw = data["timestamp"]
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.fromisoformat(ts_raw)
        if ts.tzinfo is None:
            # File-on-disk events are required to carry tz info, but be
            # lenient and assume UTC if a caller round-trips through a
            # tool that strips it.
            ts = ts.replace(tzinfo=timezone.utc)
        return cls(
            timestamp=ts,
            env=str(data["env"]),
            commit=str(data["commit"]),
            deployed_by=str(data.get("deployed_by", "")),
            metadata={
                str(k): str(v) for k, v in (data.get("metadata") or {}).items()
            },
        )

    def to_jsonl(self) -> str:
        """Serialize as one JSON-Lines line (terminating newline included)."""
        return json.dumps(self.to_dict(), separators=(",", ":")) + "\n"


@dataclass(frozen=True)
class DeployLogRead:
    """One parsed view of the deploy log.

    ``events`` is sorted by timestamp (stable: equal timestamps keep file
    order, so the later line wins ``find_at`` ties). ``skipped_lines``
    carries the 1-based line numbers that failed to parse — consumers like
    ``promptops blame`` surface the count so a corrupted log can never
    silently produce a wrong answer.
    """

    events: Tuple[DeployEvent, ...]
    skipped_lines: Tuple[int, ...]

    @property
    def skipped(self) -> int:
        return len(self.skipped_lines)


class DeployLog:
    """Append-only deploy event log at ``.promptops/deploys.jsonl``.

    The log is the canonical record of which commit was deployed to which
    environment at which time. ``append`` is atomic (POSIX O_APPEND);
    reads are tolerant of empty/malformed lines (skipped with a warning
    AND counted in ``read().skipped`` — production audit logs should keep
    flowing when one line is corrupted, but never silently).

    Reads are cached per ``(mtime_ns, size)`` of the underlying file, so
    repeated queries (``find_at``, ``iter_events``, ``read``) parse the
    file once until it changes. ``find_at`` binary-searches a per-env
    timestamp index instead of scanning every event.
    """

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"
        # Cache key is (mtime_ns, size) when the file is present, the
        # _MISSING_LOG sentinel when it is absent, or None before the first
        # read. Keying the absent state lets a stale present-file cache be
        # invalidated the instant the file disappears.
        self._cache_key: Union[Tuple[int, int], object, None] = None
        self._cache: Optional[DeployLogRead] = None
        # Per-env index built lazily from the cached read:
        # env (or None = all) -> (sorted events, parallel timestamps list)
        self._env_index: Dict[
            Optional[str], Tuple[List[DeployEvent], List[datetime]]
        ] = {}

    @property
    def path(self) -> Path:
        """Path to the deploys.jsonl file (may not exist if no events)."""
        return self.promptops_dir / _DEPLOY_LOG_FILENAME

    def exists(self) -> bool:
        return self.path.exists()

    def append(self, event: DeployEvent) -> None:
        """Atomically append an event to the log.

        Creates ``.promptops/`` if missing. Uses POSIX ``O_APPEND`` so
        concurrent appends from multiple processes serialize cleanly.
        """
        self.promptops_dir.mkdir(parents=True, exist_ok=True)
        line = event.to_jsonl().encode("utf-8")
        # Enforce the atomicity cap HERE (the write path), not in
        # DeployEvent.__post_init__: a single-syscall O_APPEND write is
        # atomic only below PIPE_BUF (~4096 bytes). An oversized line could
        # interleave with a concurrent CI deploy and corrupt the log.
        if len(line) > MAX_EVENT_BYTES:
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message=(
                    f"Deploy event serializes to {len(line)} bytes, "
                    f"exceeding the {MAX_EVENT_BYTES}-byte append limit."
                ),
                hint=(
                    "Trim the metadata map — the append-only log relies on "
                    "single-write atomicity (POSIX PIPE_BUF), which only "
                    "holds for lines under 4096 bytes. Store large payloads "
                    "elsewhere and reference them by id in metadata."
                ),
            )
        # Single-syscall write with O_APPEND is atomic for writes
        # < PIPE_BUF (typically 4096 bytes) — our lines are well under that.
        fd = os.open(
            self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644
        )
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _set_cache(
        self, read: DeployLogRead, key: Union[Tuple[int, int], object]
    ) -> DeployLogRead:
        """Store a read under ``key`` and invalidate the per-env index."""
        self._cache = read
        self._cache_key = key
        self._env_index = {}
        return read

    def read(self) -> DeployLogRead:
        """Parse the log (cached per file mtime+size) and return events
        sorted by timestamp plus the line numbers of any malformed lines.

        This is the one parse path — ``iter_events``, ``all_events``,
        ``events_for_env`` and ``find_at`` all consume its cache, so a
        thousand queries cost one file read until the log changes.

        The absent-file state is cached under a sentinel key, so a log that
        is deleted or rotated between calls invalidates any prior cached
        read (and its per-env index) instead of serving ghost events.
        """
        try:
            stat = self.path.stat()
        except (FileNotFoundError, NotADirectoryError):
            # File absent. If we previously cached a present-file read, this
            # transition must clear it so find_at can't answer from a ghost.
            if self._cache_key is _MISSING_LOG and self._cache is not None:
                return self._cache
            return self._set_cache(
                DeployLogRead(events=(), skipped_lines=()), _MISSING_LOG
            )

        if stat.st_size > MAX_DEPLOY_LOG_BYTES:
            raise PromptOpsError(
                code=E016_INVALID_DEPLOY_EVENT,
                message=(
                    f"Deploy log {self.path} is {stat.st_size} bytes, "
                    f"exceeding the {MAX_DEPLOY_LOG_BYTES}-byte read limit."
                ),
                hint=(
                    "deploys.jsonl has grown past the safety ceiling — this "
                    "usually means a runaway CI loop or a hand-edited file. "
                    "Rotate or truncate it; normal deploy history is tiny."
                ),
            )

        key = (stat.st_mtime_ns, stat.st_size)
        if self._cache is not None and self._cache_key == key:
            return self._cache

        events: List[DeployEvent] = []
        skipped: List[int] = []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for lineno, raw in enumerate(f, start=1):
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    # Guard the atomicity cap on read too: an over-long line
                    # can't have been written atomically, so treat it as
                    # suspect rather than feeding multi-MB blobs to json.
                    if len(stripped.encode("utf-8")) > MAX_EVENT_BYTES:
                        skipped.append(lineno)
                        logger.warning(
                            "Skipping oversized deploy event at %s:%d "
                            "(%d bytes > %d limit)",
                            self.path, lineno,
                            len(stripped.encode("utf-8")), MAX_EVENT_BYTES,
                        )
                        continue
                    try:
                        data = json.loads(stripped)
                        events.append(DeployEvent.from_dict(data))
                    except (
                        json.JSONDecodeError, KeyError, ValueError,
                        TypeError, RecursionError,
                    ) as exc:
                        skipped.append(lineno)
                        logger.warning(
                            "Skipping malformed deploy event at %s:%d: %s",
                            self.path, lineno, exc,
                        )
        except (FileNotFoundError, NotADirectoryError):
            # Deleted between stat() and open() — treat as absent.
            return self._set_cache(
                DeployLogRead(events=(), skipped_lines=()), _MISSING_LOG
            )

        # Stable sort: equal timestamps keep file order, so the later
        # line wins find_at ties (bisect_right lands after it).
        events.sort(key=lambda e: e.timestamp)

        return self._set_cache(
            DeployLogRead(events=tuple(events), skipped_lines=tuple(skipped)),
            key,
        )

    def iter_events(self) -> Iterator[DeployEvent]:
        """Yield events sorted by timestamp (oldest first).

        Empty lines and lines that fail to parse as ``DeployEvent`` are
        skipped with a warning; ``read().skipped`` carries the count.

        Note (v0.4.0): pre-0.4.0 this yielded file order. Events are now
        yielded in timestamp order — identical for normally-appended logs,
        and the documented contract for backfilled/merged ones.
        """
        yield from self.read().events

    def all_events(self) -> List[DeployEvent]:
        """All events as a list (oldest first). Convenience over iter_events."""
        return list(self.read().events)

    def events_for_env(self, env: str) -> List[DeployEvent]:
        """All events for a given env, in chronological order (oldest first)."""
        return [e for e in self.read().events if e.env == env]

    def _index_for_env(
        self, env: Optional[str]
    ) -> Tuple[List[DeployEvent], List[datetime]]:
        """(events, parallel timestamps) for binary search, built lazily.

        Returns a freshly-built local on a cache miss rather than reading
        it back out of ``self._env_index`` — another thread calling
        ``read()`` can reset that dict between the set and the get, so the
        check-then-act would raise ``KeyError``. The SDK is importable in
        multi-threaded servers; worst case under threads is redundant index
        builds, never a crash.
        """
        cached = self._env_index.get(env)
        if cached is not None:
            return cached
        all_events = self.read().events
        subset = (
            list(all_events)
            if env is None
            else [e for e in all_events if e.env == env]
        )
        built = (subset, [e.timestamp for e in subset])
        self._env_index[env] = built
        return built

    def find_at(
        self, timestamp: datetime, env: Optional[str] = None
    ) -> Optional[DeployEvent]:
        """Return the latest event with ``e.timestamp <= timestamp``.

        Optionally filtered by ``env``. This is the core lookup for
        ``promptops blame --at <ts>``: "what was deployed in env X at
        moment T?"  Returns ``None`` if no event matches — e.g. the
        timestamp predates any recorded deploy.

        O(log n) per call via a cached per-env timestamp index; the file
        is re-read only when its mtime or size changes.
        """
        if timestamp.tzinfo is None:
            raise PromptOpsError(
                code=E017_NAIVE_TIMESTAMP,
                message=(
                    "find_at(timestamp) requires a timezone-aware datetime."
                ),
                hint=(
                    "Use datetime.now(timezone.utc) or attach a tzinfo. "
                    "Bare dates in the CLI are interpreted as UTC midnight."
                ),
            )

        # read() refreshes the cache (and clears _env_index) if the file
        # changed since the index was built.
        self.read()
        events, timestamps = self._index_for_env(env)
        idx = bisect_right(timestamps, timestamp) - 1
        return events[idx] if idx >= 0 else None
