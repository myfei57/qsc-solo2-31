"""液位计量与配额：标定时效、零点偏移闩锁、配额上限与纪元归属。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bwms.app import build_line
from bwms.errors import CalibrationError, LatchError, QuotaExceededError
from bwms.settings import QuotaSpec, default_settings
from bwms.store.records import KIND_ACTION, KIND_MEASUREMENT


def test_level_reading_follows_the_latest_calibration(line):
    line.tick(1)
    before = line.read_level(10.0)
    line.recalibrate_level(6.0, "检修后重新标定")
    after = line.read_level(10.0)
    assert after["offset_m3"] == 6.0
    assert after["volume_m3"] == pytest.approx(before["volume_m3"] + 6.0)


def test_calibration_history_keeps_the_previous_zero_point(line):
    line.recalibrate_level(4.0, "第一次标定")
    line.recalibrate_level(2.0, "第二次标定")
    history = line.calibrations.history()
    assert [item.offset_m3 for item in history] == [0.0, 4.0, 2.0]
    assert line.calibrations.offset_m3() == 2.0


def test_expired_calibration_blocks_level_reading(line):
    line.tick(line.settings.level.calibration_max_age_ticks + 1)
    assert line.calibrations.is_fresh() is False
    with pytest.raises(CalibrationError):
        line.read_level(10.0)


def test_offset_beyond_the_limit_trips_the_level_latch(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.recalibrate_level(40.0, "标定值异常")
    intake_line.read_level(1.0)
    assert intake_line.latches.is_set("level_offset")
    assert intake_line.calibrations.within_limit() is False


def test_level_latch_blocks_tank_loading(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.recalibrate_level(40.0, "标定值异常")
    intake_line.read_level(1.0)
    with pytest.raises(LatchError) as denied:
        intake_line.load_tank("TB-01", 10.0)
    assert "level_offset" in denied.value.latches


def test_recalibration_within_the_limit_clears_the_latch(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.recalibrate_level(40.0, "标定值异常")
    intake_line.read_level(1.0)
    intake_line.recalibrate_level(2.0, "复核后修正零点")
    assert not intake_line.latches.is_set("level_offset")
    assert intake_line.load_tank("TB-01", 10.0)["volume_m3"] == 10.0


def test_recalibration_is_recorded_as_a_calibration_record(line):
    line.recalibrate_level(3.0, "年度校验")
    calibrations = line.records()
    kinds = {item.kind for item in calibrations}
    assert "calibration" in kinds
    assert any(item.payload.get("offset_m3") == 3.0 for item in calibrations)


def test_quota_limit_blocks_further_record_writes(tmp_path, clock):
    settings = replace(default_settings(str(tmp_path / "state")), quota=QuotaSpec(3, 0.5))
    line = build_line(settings, clock)
    assert line.quota.used(0) == 2
    line.quota.require_room()
    line.store.write(KIND_ACTION, "TB-01", {"action": "seat_confirm"})
    with pytest.raises(QuotaExceededError):
        line.quota.require_room()


def test_quota_warning_is_raised_near_the_limit(tmp_path, clock):
    settings = replace(default_settings(str(tmp_path / "state")), quota=QuotaSpec(4, 0.5))
    line = build_line(settings, clock)
    line.quota.require_room()
    assert line.quota.policy()["warn_at"] == 2
    assert line.quota.warnings()
    assert line.quota.status()["warnings"] == 1


def test_quota_remaining_tracks_epoch_records(line):
    limit = line.settings.quota.max_records_per_epoch
    used = line.quota.used(0)
    assert line.quota.remaining(0) == limit - used
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"}, epoch=0)
    assert line.quota.used(0) == used + 1


def test_epoch_rollover_keeps_tail_records_in_the_previous_epoch(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"}, epoch=line.epoch.current())
    before = line.epoch.totals()["0"]
    entry = line.roll_epoch("航段收尾")
    assert entry["closed_records"] == before
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"}, epoch=line.epoch.current())
    totals = line.epoch.totals()
    assert totals["0"] == before
    assert totals["1"] == 2


def test_rollover_entry_belongs_to_the_new_epoch(line):
    line.roll_epoch("航段收尾")
    rolls = [
        record
        for record in line.records()
        if record.subject == "treatment-epoch"
    ]
    assert [record.epoch for record in rolls] == [1]
    assert line.epoch.current() == 1
