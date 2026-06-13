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
            "timestamp": ts, "env": "prod", "commit": "abc1234", "deployed_by": "x",
        })
        assert restored.timestamp == ts

    def test_from_dict_normalizes_naive_iso_string_to_utc(self):
        """Lenient read path: ISO strings without tz get assumed UTC."""
        restored = DeployEvent.from_dict({
            "timestamp": "2026-05-26T12:00:00",
            "env": "prod", "commit": "abc1234", "deployed_by": "x",
        })
        assert restored.timestamp.tzinfo is not None
        assert restored.timestamp.utcoffset() == timedelta(0)

    def test_from_dict_handles_missing_metadata(self):
        restored = DeployEvent.from_dict({
            "timestamp": datetime.now(UTC).isoformat(),
            "env": "prod", "commit": "abc1234", "deployed_by": "x",
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
    log.append(_ev(base + timedelta(hours=0), env="staging", commit="a1" * 20))
    log.append(_ev(base + timedelta(hours=1), env="prod",    commit="b2" * 20))
    log.append(_ev(base + timedelta(hours=2), env="staging", commit="c3" * 20))
    log.append(_ev(base + timedelta(hours=3), env="prod",    commit="d4" * 20))
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


# ── v0.4.0 Lane C: read cache, size limit, skipped-line accounting ──


class TestEventSizeLimit:
    """P2.6 (v0.4.0 refined): the PIPE_BUF atomicity cap is enforced on
    the *append* path, not at construction — so a valid pre-cap event
    already on disk still parses on read (C1)."""

    def test_oversized_event_constructs_fine(self):
        # Construction is size-agnostic: a DeployEvent is a valid value
        # object at any size. Only appending relies on atomicity.
        e = DeployEvent(
            timestamp=datetime.now(UTC),
            env="prod",
            commit="a" * 40,
            deployed_by="ci",
            metadata={"changelog": "x" * 5000},
        )
        assert e.metadata["changelog"] == "x" * 5000

    def test_oversized_event_rejected_on_append(self, tmp_path: Path):
        from llmhq_promptops import PromptOpsError

        log = DeployLog(str(tmp_path))
        big = DeployEvent(
            timestamp=datetime.now(UTC),
            env="prod",
            commit="a" * 40,
            deployed_by="ci",
            metadata={"changelog": "x" * 5000},
        )
        with pytest.raises(PromptOpsError, match="append limit") as exc:
            log.append(big)
        assert exc.value.code == "PROMPTOPS_E016"

    def test_legacy_oversized_line_parses_on_read_but_is_skipped(
        self, tmp_path: Path, caplog
    ):
        """C1: an over-long line on disk is skipped (can't have been atomic)
        but does NOT crash the read — and it's counted, not silent."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        # Hand-write an oversized but otherwise valid JSON line.
        with log.path.open("a") as f:
            f.write(json.dumps({
                "timestamp": "2026-05-21T10:00:00+00:00",
                "env": "prod", "commit": "b" * 40, "deployed_by": "ci",
                "metadata": {"blob": "y" * 5000},
            }) + "\n")
        read = log.read()
        assert len(read.events) == 1   # only the small one
        assert read.skipped == 1       # the oversized one, counted

    def test_normal_event_well_under_limit(self):
        e = _ev(datetime.now(UTC), release="v1.2.3", region="eu-west-1")
        assert len(e.to_jsonl().encode("utf-8")) < 1000


class TestCommitShaValidation:
    """S3: deploy commits must look like git SHAs before they reach git."""

    def test_non_hex_commit_rejected(self):
        from llmhq_promptops import PromptOpsError

        with pytest.raises(PromptOpsError, match="not a git SHA") as exc:
            DeployEvent(
                timestamp=datetime.now(UTC),
                env="prod", commit="not-a-sha", deployed_by="ci",
            )
        assert exc.value.code == "PROMPTOPS_E016"

    def test_too_short_commit_rejected(self):
        from llmhq_promptops import PromptOpsError

        with pytest.raises(PromptOpsError, match="not a git SHA"):
            DeployEvent(
                timestamp=datetime.now(UTC),
                env="prod", commit="abc", deployed_by="ci",  # 3 chars
            )

    def test_short_and_full_hex_shas_accepted(self):
        for sha in ("abc1234", "a" * 40, "f" * 64):
            e = DeployEvent(
                timestamp=datetime.now(UTC),
                env="prod", commit=sha, deployed_by="ci",
            )
            assert e.commit == sha


class TestDeployLogReadSafety:
    """B1 + C8 + S1: cache invalidation, TOCTOU, whole-file size ceiling."""

    def test_find_at_returns_none_after_log_deleted(self, tmp_path: Path):
        """B1: a deleted log must not answer from a ghost cache."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        ts = datetime(2026, 5, 22, 0, 0, tzinfo=UTC)
        assert log.find_at(ts) is not None  # warm the cache + index

        log.path.unlink()  # delete the log out from under the instance

        assert log.all_events() == []
        assert log.find_at(ts) is None  # must NOT be the ghost event
        assert log.read().events == ()

    def test_oversized_whole_log_rejected(self, tmp_path: Path, monkeypatch):
        from llmhq_promptops import PromptOpsError
        from llmhq_promptops.core import deploys as deploys_mod

        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        # Shrink the ceiling instead of writing 50MB.
        monkeypatch.setattr(deploys_mod, "MAX_DEPLOY_LOG_BYTES", 10)
        with pytest.raises(PromptOpsError, match="read limit") as exc:
            log.read()
        assert exc.value.code == "PROMPTOPS_E016"


class TestReadCacheAndSkippedLines:
    """P2.5 + P2.7: cached reads, binary-search find_at, skip accounting."""

    def test_read_reports_skipped_line_numbers(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        # Corrupt the middle of the file by hand
        with log.path.open("a") as f:
            f.write("{corrupted line\n")
        log.append(_ev(datetime(2026, 5, 21, 10, 0, tzinfo=UTC)))

        read = log.read()
        assert read.skipped == 1
        assert read.skipped_lines == (2,)
        assert len(read.events) == 2

    def test_clean_log_reports_zero_skipped(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        assert log.read().skipped == 0

    def test_cache_hit_returns_same_object(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        first = log.read()
        second = log.read()
        assert first is second  # cache hit, no re-parse

    def test_cache_invalidated_by_append(self, tmp_path: Path):
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))
        first = log.read()
        log.append(_ev(datetime(2026, 5, 21, 10, 0, tzinfo=UTC)))
        second = log.read()
        assert second is not first
        assert len(second.events) == 2

    def test_find_at_correct_after_append_on_same_instance(self, tmp_path: Path):
        """The cache must never serve stale answers across appends."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC), commit="a" * 40))
        ts = datetime(2026, 5, 22, 0, 0, tzinfo=UTC)
        assert log.find_at(ts).commit == "a" * 40

        log.append(_ev(datetime(2026, 5, 21, 10, 0, tzinfo=UTC), commit="b" * 40))
        assert log.find_at(ts).commit == "b" * 40

    def test_iter_events_sorted_by_timestamp_even_when_backfilled(
        self, tmp_path: Path
    ):
        """Backfilled logs can be appended out of order; reads sort."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 25, 10, 0, tzinfo=UTC)))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC)))  # earlier!
        timestamps = [e.timestamp for e in log.iter_events()]
        assert timestamps == sorted(timestamps)

    def test_find_at_with_out_of_order_file(self, tmp_path: Path):
        """Binary search must hold on backfilled (file-unordered) logs."""
        log = DeployLog(str(tmp_path))
        log.append(_ev(datetime(2026, 5, 25, 10, 0, tzinfo=UTC), commit="c" * 40))
        log.append(_ev(datetime(2026, 5, 20, 10, 0, tzinfo=UTC), commit="a" * 40))
        log.append(_ev(datetime(2026, 5, 22, 10, 0, tzinfo=UTC), commit="b" * 40))

        hit = log.find_at(datetime(2026, 5, 23, 0, 0, tzinfo=UTC))
        assert hit.commit == "b" * 40  # the 05-22 deploy, not 05-25 or 05-20

    def test_find_at_many_events_scale_sanity(self, tmp_path: Path):
        """1000 events: still answers correctly (and via one parse)."""
        log = DeployLog(str(tmp_path))
        base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        for i in range(1000):
            log.append(_ev(base + timedelta(hours=i), commit=f"{i:040d}"))

        hit = log.find_at(base + timedelta(hours=499, minutes=30))
        assert hit.commit == f"{499:040d}"
        # Cached: second query must not re-parse
        assert log.read() is log.read()
