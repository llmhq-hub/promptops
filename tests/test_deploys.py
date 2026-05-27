"""Tests for ``core/deploys.py`` (Phase 1.5a M4).

Covers:
- DeployEvent: construction validation, to/from_dict roundtrip, JSONL format
- DeployLog: append (atomic), iter_events (tolerant of empty + malformed lines),
  find_at semantics (env filter, before-first-event → None, naive tz rejection),
  events_for_env filter
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from llmhq_promptops import DeployEvent, DeployLog


UTC = timezone.utc


def _ev(ts: datetime, env: str = "prod", commit: str = "a" * 40, by: str = "alice", **meta) -> DeployEvent:
    return DeployEvent(timestamp=ts, env=env, commit=commit, deployed_by=by, metadata=meta)


# ── DeployEvent ─────────────────────────────────────────────────────


class TestDeployEventConstruction:
    def test_assigns_all_fields(self):
        ts = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
        e = DeployEvent(
            timestamp=ts, env="prod", commit="abc1234", deployed_by="alice",
            metadata={"release": "v1.2.3"},
        )
        assert e.timestamp == ts
        assert e.env == "prod"
        assert e.commit == "abc1234"
        assert e.deployed_by == "alice"
        assert e.metadata == {"release": "v1.2.3"}

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            DeployEvent(
                timestamp=datetime(2026, 5, 26),
                env="prod", commit="abc", deployed_by="x",
            )

    def test_empty_env_rejected(self):
        with pytest.raises(ValueError, match="env"):
            DeployEvent(
                timestamp=datetime.now(UTC), env="", commit="abc", deployed_by="x",
            )

    def test_whitespace_env_rejected(self):
        with pytest.raises(ValueError, match="env"):
            DeployEvent(
                timestamp=datetime.now(UTC), env="   ", commit="abc", deployed_by="x",
            )

    def test_empty_commit_rejected(self):
        with pytest.raises(ValueError, match="commit"):
            DeployEvent(
                timestamp=datetime.now(UTC), env="prod", commit="", deployed_by="x",
            )


class TestDeployEventSerialization:
    def test_to_dict_roundtrip(self):
        original = _ev(datetime(2026, 5, 26, 12, 0, tzinfo=UTC), release="v1")
        restored = DeployEvent.from_dict(original.to_dict())
        assert restored == original

    def test_to_dict_serializes_timestamp_as_iso(self):
        ts = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        d = _ev(ts).to_dict()
        assert d["timestamp"] == ts.isoformat()

    def test_to_jsonl_one_line_terminated_by_newline(self):
        line = _ev(datetime.now(UTC)).to_jsonl()
        assert line.endswith("\n")
        assert line.count("\n") == 1
        parsed = json.loads(line)
        assert parsed["env"] == "prod"

    def test_from_dict_accepts_datetime_object(self):
        ts = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        restored = DeployEvent.from_dict({
            "timestamp": ts, "env": "prod", "commit": "abc", "deployed_by": "x",
        })
        assert restored.timestamp == ts

    def test_from_dict_normalizes_naive_iso_string_to_utc(self):
        """Lenient read path: ISO strings without tz get assumed UTC."""
        restored = DeployEvent.from_dict({
            "timestamp": "2026-05-26T12:00:00",
            "env": "prod", "commit": "abc", "deployed_by": "x",
        })
        assert restored.timestamp.tzinfo is not None
        assert restored.timestamp.utcoffset() == timedelta(0)

    def test_from_dict_handles_missing_metadata(self):
        restored = DeployEvent.from_dict({
            "timestamp": datetime.now(UTC).isoformat(),
            "env": "prod", "commit": "abc", "deployed_by": "x",
        })
        assert restored.metadata == {}


# ── DeployLog.append + iter_events ──────────────────────────────────


class TestDeployLogAppend:
    def test_append_creates_promptops_dir_and_file(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        assert not log.exists()

        log.append(_ev(datetime.now(UTC)))

        assert log.exists()
        assert log.path == tmp_path / ".promptops" / "deploys.jsonl"

    def test_append_writes_one_jsonl_line(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 26, tzinfo=UTC)))
        content = log.path.read_text()
        assert content.count("\n") == 1
        parsed = json.loads(content.strip())
        assert parsed["env"] == "prod"

    def test_multiple_appends_preserve_order(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        t0 = datetime(2026, 5, 26, 10, tzinfo=UTC)
        log.append(_ev(t0, env="dev"))
        log.append(_ev(t0 + timedelta(hours=1), env="staging"))
        log.append(_ev(t0 + timedelta(hours=2), env="prod"))

        events = log.all_events()
        assert [e.env for e in events] == ["dev", "staging", "prod"]


class TestDeployLogIter:
    def test_iter_events_empty_when_no_file(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        assert list(log.iter_events()) == []

    def test_iter_events_skips_empty_lines(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 26, tzinfo=UTC), env="dev"))

        # Inject blank lines into the log
        with log.path.open("a") as f:
            f.write("\n\n   \n")
        log.append(_ev(datetime(2026, 5, 27, tzinfo=UTC), env="prod"))

        events = log.all_events()
        assert len(events) == 2
        assert [e.env for e in events] == ["dev", "prod"]

    def test_iter_events_skips_malformed_lines(self, tmp_path: Path, caplog):
        """A corrupted line must not stop iteration — just log a warning."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 26, tzinfo=UTC), env="dev"))

        with log.path.open("a") as f:
            f.write("not json at all\n")
            f.write('{"env": "missing-fields"}\n')

        log.append(_ev(datetime(2026, 5, 27, tzinfo=UTC), env="prod"))

        events = log.all_events()
        # Two well-formed events; two malformed lines skipped.
        assert len(events) == 2
        assert [e.env for e in events] == ["dev", "prod"]


# ── DeployLog.find_at + events_for_env ──────────────────────────────


@pytest.fixture
def populated_log(tmp_path: Path) -> DeployLog:
    """A log with 4 events across two envs, ordered in time."""
    log = DeployLog(str(tmp_path))
    base = datetime(2026, 5, 26, 0, 0, tzinfo=UTC)
    log.append(_ev(base + timedelta(hours=0), env="staging", commit="s" * 40))
    log.append(_ev(base + timedelta(hours=1), env="prod",    commit="p1" * 20))
    log.append(_ev(base + timedelta(hours=2), env="staging", commit="s2" * 20))
    log.append(_ev(base + timedelta(hours=3), env="prod",    commit="p2" * 20))
    return log


class TestFindAt:
    def test_returns_none_before_any_event(self, populated_log: DeployLog):
        ts = datetime(2026, 5, 25, 23, 0, tzinfo=UTC)
        assert populated_log.find_at(ts) is None

    def test_returns_latest_at_or_before_timestamp(self, populated_log: DeployLog):
        # 90 minutes in → 1-hour-event is the answer (the 2-hour one is later)
        ts = datetime(2026, 5, 26, 1, 30, tzinfo=UTC)
        e = populated_log.find_at(ts)
        assert e is not None
        assert e.timestamp == datetime(2026, 5, 26, 1, 0, tzinfo=UTC)

    def test_env_filter_narrows_results(self, populated_log: DeployLog):
        ts = datetime(2026, 5, 26, 2, 30, tzinfo=UTC)
        # Without env filter: the staging event at hour 2 is most recent
        unfiltered = populated_log.find_at(ts)
        assert unfiltered is not None and unfiltered.env == "staging"

        # With env=prod: the hour-1 prod event is the most recent prod event ≤ ts
        prod = populated_log.find_at(ts, env="prod")
        assert prod is not None
        assert prod.env == "prod"
        assert prod.timestamp == datetime(2026, 5, 26, 1, 0, tzinfo=UTC)

    def test_exact_timestamp_match_is_included(self, populated_log: DeployLog):
        """``<=`` semantics: an event at exactly the queried ts qualifies."""
        ts = datetime(2026, 5, 26, 1, 0, tzinfo=UTC)
        e = populated_log.find_at(ts, env="prod")
        assert e is not None
        assert e.timestamp == ts

    def test_naive_timestamp_rejected(self, populated_log: DeployLog):
        with pytest.raises(ValueError, match="timezone-aware"):
            populated_log.find_at(datetime(2026, 5, 26, 1, 0))

    def test_env_filter_returning_none_when_no_match(self, populated_log: DeployLog):
        # Before any prod event, even though staging exists
        ts = datetime(2026, 5, 26, 0, 30, tzinfo=UTC)
        assert populated_log.find_at(ts, env="prod") is None


class TestEventsForEnv:
    def test_chronological_order(self, populated_log: DeployLog):
        prods = populated_log.events_for_env("prod")
        assert len(prods) == 2
        assert prods[0].timestamp < prods[1].timestamp

    def test_empty_when_no_matching_env(self, populated_log: DeployLog):
        assert populated_log.events_for_env("nonexistent") == []
