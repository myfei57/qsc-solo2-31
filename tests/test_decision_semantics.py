"""判定语义：当前态与历史态、批次唯一、门限比较与查询过滤。"""

from __future__ import annotations

import pytest

from bwms.errors import (
    DuplicateBatchError,
    ThresholdError,
    ThresholdNotMetError,
    UnknownSubjectError,
)
from bwms.store.records import KIND_MEASUREMENT, RecordFilter


def test_current_tank_state_differs_from_historical_state(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 120.0)
    snapshot_tick = intake_line.clock.tick
    intake_line.tick(1)
    intake_line.load_tank("TB-01", 60.0)
    historical = intake_line.bay.as_of("TB-01", snapshot_tick)
    assert historical["volume_m3"] == 120.0
    assert intake_line.bay.volume("TB-01") == 180.0
    assert intake_line.bay.state("TB-01") == "filling"


def test_historical_query_before_any_load_reports_empty(line):
    history = line.bay.as_of("TB-02", 0)
    assert history["state"] == "empty"
    assert history["reconstructed"] is False


def test_duplicate_batch_id_is_rejected(line):
    line.batches.reserve("BATCH-0001", "TB-01")
    with pytest.raises(DuplicateBatchError):
        line.batches.reserve("BATCH-0001", "TB-02")


def test_duplicate_analysis_of_the_same_batch_is_rejected(line):
    line.batches.reserve("BATCH-0001", "TB-01")
    line.analyzer.analyze("BATCH-0001", 2.0, 1.0)
    with pytest.raises(DuplicateBatchError):
        line.analyzer.analyze("BATCH-0001", 2.0, 1.0)


def test_analysis_of_an_unknown_batch_is_rejected(line):
    with pytest.raises(UnknownSubjectError):
        line.analyze_sample("BATCH-MISSING", 1.0, 1.0)


def test_turbidity_above_the_limit_is_not_compliant(line):
    result = line.analyzer.analyze("BATCH-T", 8.5, 2.0)
    assert result.compliant is False
    assert any("turbidity" in reason or "浊度" in reason for reason in result.reasons)


def test_organism_count_above_the_limit_is_not_compliant(line):
    result = line.analyzer.analyze("BATCH-O", 2.0, 11.0)
    assert result.compliant is False
    assert len(result.reasons) == 1


def test_readings_exactly_at_the_limit_are_compliant(line):
    result = line.analyzer.analyze("BATCH-BOUND", 8.0, 10.0)
    assert result.compliant is True
    assert result.reasons == ()


def test_negative_reading_is_rejected(line):
    with pytest.raises(ThresholdError):
        line.analyzer.analyze("BATCH-NEG", -1.0, 1.0)


def test_permit_is_refused_for_a_non_compliant_batch(line):
    with pytest.raises(ThresholdNotMetError):
        line.permits.issue("BATCH-BAD", False, 1, "CF-NONE")


def test_window_interval_is_half_open(line):
    line.tick(10)
    window = line.windows.open("BATCH-0001")
    assert window.contains(10) is True
    assert window.contains(17) is True
    assert window.contains(18) is False
    assert line.windows.assign(17).window_id == window.window_id
    assert line.windows.assign(18) is None


def test_window_edge_sample_belongs_to_exactly_one_batch(line):
    line.tick(10)
    first = line.windows.open("BATCH-0001")
    line.windows.close(first.window_id)
    line.tick(8)
    second = line.windows.open("BATCH-0002")
    assert line.windows.assign(18).batch_id == second.batch_id
    assert line.windows.assign(17) is None
    assert line.windows.assign(19).batch_id == second.batch_id


def test_open_window_count_is_limited(line):
    line.windows.open("BATCH-0001")
    line.windows.open("BATCH-0002")
    with pytest.raises(ThresholdError):
        line.windows.open("BATCH-0003")


def test_records_filter_by_epoch(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"}, epoch=0)
    line.roll_epoch("segment closed")
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"}, epoch=1)
    assert {item.epoch for item in line.records(RecordFilter(epoch=1))} == {1}


def test_records_filter_by_generation(line):
    line.publish_parameters("dose", {"target_ppm": 5.0})
    selected = line.records(RecordFilter(subject="dose", generation=2))
    assert [item.generation for item in selected] == [2]
