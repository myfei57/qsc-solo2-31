"""写入语义：只追加记录流、提交水位、按水位重放、未提交不可见、墓碑作废。"""

from __future__ import annotations

import pytest

from bwms.errors import StreamError, UncommittedRecordError, UnknownRecordError
from bwms.store import Watermark
from bwms.store.records import (
    KIND_ACTION,
    KIND_MEASUREMENT,
    KIND_TOMBSTONE,
    RecordFilter,
)


def test_staged_record_is_uncommitted_and_invisible(line):
    visible_before = len(line.store.visible())
    record = line.store.stage(KIND_ACTION, "TB-01", {"action": "staged"})
    assert record.seq > line.store.watermark()
    assert len(line.store.visible()) == visible_before
    assert line.store.buffered() == 1


def test_uncommitted_record_is_not_on_disk_before_flush(line):
    record = line.store.stage(KIND_ACTION, "TB-01", {"action": "staged"})
    assert record.seq not in {item.seq for item in line.store.durable()}
    line.store.flush()
    assert record.seq in {item.seq for item in line.store.durable()}
    assert record.seq not in {item.seq for item in line.store.visible()}


def test_commit_watermark_makes_record_visible(line):
    record = line.store.stage(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.commit(record)
    assert line.store.watermark() == record.seq
    assert record.seq in {item.seq for item in line.store.visible()}
    assert line.store.buffered() == 0


def test_get_rejects_uncommitted_record(line):
    record = line.store.stage(KIND_ACTION, "TB-01", {"action": "staged"})
    with pytest.raises(UncommittedRecordError):
        line.store.get(record.seq)


def test_restart_replays_from_watermark_and_ignores_uncommitted_tail(line):
    committed = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    visible_before = len(line.store.visible())
    digest_before = line.store.digest()
    tail = line.store.stage(KIND_ACTION, "TB-01", {"action": "tail"})
    report = line.store.restart()
    assert report["watermark"] == committed.seq
    assert report["pending"] == 1
    assert tail.seq not in {item.seq for item in line.store.visible()}
    assert len(line.store.visible()) == visible_before
    assert line.store.digest() == digest_before


def test_restart_keeps_snapshot_consistent_with_replay(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.restart()
    verification = line.store.verify()
    assert verification["consistent"] is True
    assert verification["pending_durable"] == 0
    assert verification["stored_digest"] == verification["replayed_digest"]


def test_tombstone_hides_superseded_record(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.tombstone(record.seq, "operator retracted the entry")
    assert record.seq not in {item.seq for item in line.store.visible()}
    assert line.store.projection.is_superseded(record.seq)


def test_tombstone_keeps_the_stream_append_only(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    before = line.store.allocated()
    tombstone = line.store.tombstone(record.seq, "rollback")
    assert tombstone.kind == KIND_TOMBSTONE
    assert tombstone.supersedes == record.seq
    assert line.store.allocated() == before + 1
    assert line.store.get(record.seq).seq == record.seq


def test_tombstone_reduces_projection_count(line):
    first = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    counted = line.store.count(KIND_MEASUREMENT)
    line.store.tombstone(first.seq, "rollback")
    assert line.store.count(KIND_MEASUREMENT) == counted - 1


def test_tombstone_records_remain_queryable_when_asked_for(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.tombstone(record.seq, "rollback")
    tombstones = line.store.visible(
        RecordFilter(kinds=(KIND_TOMBSTONE,), include_tombstones=True)
    )
    assert [item.supersedes for item in tombstones] == [record.seq]


def test_commit_of_already_committed_seq_is_idempotent(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    assert line.store.commit(record) == record.seq
    assert line.store.commit(record) == record.seq
    assert len(line.store.pending()) == 0


def test_unknown_record_sequence_is_rejected(line):
    with pytest.raises(UnknownRecordError):
        line.store.get(999999)


def test_watermark_cannot_move_backwards(tmp_path):
    watermark = Watermark(tmp_path / "watermark.json")
    watermark.advance(5)
    with pytest.raises(StreamError):
        watermark.advance(3)


def test_visible_filter_returns_only_matching_kind(line):
    line.store.write(KIND_ACTION, "TB-01", {"action": "seat"})
    line.store.write(KIND_MEASUREMENT, "TB-02", {"action": "load"})
    measurements = line.records(RecordFilter(kinds=(KIND_MEASUREMENT,)))
    assert measurements
    assert {item.kind for item in measurements} == {KIND_MEASUREMENT}


def test_visible_filter_matches_subject_and_tick_window(line):
    line.tick(3)
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.tick(5)
    line.store.write(KIND_MEASUREMENT, "TB-02", {"action": "load"})
    selected = line.records(
        RecordFilter(subject="TB-01", since_tick=0, until_tick=4)
    )
    assert [item.subject for item in selected] == ["TB-01"]


def test_visible_limit_caps_the_result_set(line):
    for _ in range(4):
        line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    assert len(line.records(RecordFilter(kinds=(KIND_MEASUREMENT,), limit=2))) == 2


def test_truncate_clears_stream_and_watermark(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    line.store.truncate()
    assert line.store.watermark() == 0
    assert line.store.visible() == ()
    assert line.store.allocated() == 0
