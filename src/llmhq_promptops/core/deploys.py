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
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


logger = logging.getLogger(__name__)


_DEPLOY_LOG_FILENAME = "deploys.jsonl"


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
            raise ValueError(
                "DeployEvent.timestamp must be timezone-aware (UTC). "
                "Use datetime.now(timezone.utc), not datetime.utcnow()."
            )
        if not self.env or not self.env.strip():
            raise ValueError("DeployEvent.env must not be empty.")
        if not self.commit or not self.commit.strip():
            raise ValueError("DeployEvent.commit must not be empty.")

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


class DeployLog:
    """Append-only deploy event log at ``.promptops/deploys.jsonl``.

    The log is the canonical record of which commit was deployed to which
    environment at which time. ``append`` is atomic (POSIX O_APPEND);
    ``iter_events`` is tolerant of empty/malformed lines (skipped with a
    warning, not a hard error — production audit logs should keep flowing
    even when one line is corrupted).
    """

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.promptops_dir = self.repo_path / ".promptops"

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

    def iter_events(self) -> Iterator[DeployEvent]:
        """Yield events in file order (oldest first).

        Empty lines and lines that fail to parse as ``DeployEvent`` are
        skipped with a warning. This keeps the audit log useful when a
        single line is corrupted — the rest still reads.
        """
        if not self.path.exists():
            return

        with self.path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    yield DeployEvent.from_dict(data)
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                    logger.warning(
                        "Skipping malformed deploy event at %s:%d: %s",
                        self.path, lineno, exc,
                    )

    def all_events(self) -> List[DeployEvent]:
        """All events as a list (oldest first). Convenience over iter_events."""
        return list(self.iter_events())

    def events_for_env(self, env: str) -> List[DeployEvent]:
        """All events for a given env, in chronological order (oldest first)."""
        return [e for e in self.iter_events() if e.env == env]

    def find_at(
        self, timestamp: datetime, env: Optional[str] = None
    ) -> Optional[DeployEvent]:
        """Return the latest event with ``e.timestamp <= timestamp``.

        Optionally filtered by ``env``. This is the core lookup for
        ``promptops blame --at <ts>``: "what was deployed in env X at
        moment T?"  Returns ``None`` if no event matches — e.g. the
        timestamp predates any recorded deploy.
        """
        if timestamp.tzinfo is None:
            raise ValueError(
                "find_at(timestamp) requires a timezone-aware datetime. "
                "Use datetime.now(timezone.utc) or attach a tzinfo."
            )

        best: Optional[DeployEvent] = None
        for event in self.iter_events():
            if env is not None and event.env != env:
                continue
            if event.timestamp <= timestamp:
                if best is None or event.timestamp > best.timestamp:
                    best = event
        return best
