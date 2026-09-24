"""泵与投加：水流建立时序、投加窗口、越限与流向换向旁路。"""

from __future__ import annotations

import pytest

from bwms.errors import InterlockError, LatchError, ThresholdError
from bwms.store.records import KIND_MEASUREMENT, RecordFilter


def test_flow_is_not_ready_before_settle_ticks(line):
    line.confirm_valve(line.settings.pump.outlet_valve)
    line.start_pump("intake")
    assert line.flow.ready() is False
    assert line.flow.read() == 0.0
    line.settle_flow()
    assert line.flow.ready() is True
    assert line.flow.read() == line.settings.pump.rated_flow_m3_per_tick


def test_pump_cannot_start_before_the_outlet_valve_is_seated(line):
    with pytest.raises(InterlockError) as denied:
        line.start_pump("intake")
    assert "outlet_open" in denied.value.unmet


def test_pump_rejects_an_unknown_direction(intake_line):
    intake_line.pump.stop()
    with pytest.raises(Exception) as denied:
        intake_line.pump.start("sideways")
    assert denied.value.code == "configuration_error"


def test_dose_after_flow_established_records_a_measurement(intake_line):
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    result = intake_line.inject_dose("BATCH-OK", 120.0, sheet.sheet_id)
    assert result.ppm == pytest.approx(intake_line.settings.dose.target_ppm)
    assert result.generation == sheet.generation
    measurements = intake_line.records(RecordFilter(kinds=(KIND_MEASUREMENT,)))
    assert any(item.payload.get("action") == "dose" for item in measurements)


def test_dose_verification_matches_the_recomputed_ratio(intake_line):
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    intake_line.inject_dose("BATCH-VERIFY", 120.0, sheet.sheet_id)
    verification = intake_line.verify_dose("BATCH-VERIFY")
    assert verification["match"] is True
    assert verification["window_elapsed"] is True
    assert verification["scheduled_ppm"] == verification["recomputed_ppm"]


def test_dose_above_max_ppm_is_rejected(intake_line):
    intake_line.publish_parameters("dose", {"target_ppm": 20.0, "max_ppm": 12.0})
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    with pytest.raises(ThresholdError) as exceeded:
        intake_line.inject_dose("BATCH-OVER", 60.0, sheet.sheet_id)
    assert exceeded.value.limit == 12.0


def test_flow_drop_trips_latch_and_blocks_later_injection(intake_line):
    intake_line.drop_flow("pump tripped")
    assert intake_line.latches.is_set("flow_lost")
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    with pytest.raises(LatchError) as denied:
        intake_line.inject_dose("BATCH-LOST", 60.0, sheet.sheet_id)
    assert "flow_lost" in denied.value.latches


def test_settling_the_flow_again_clears_the_latch_and_allows_dosing(intake_line):
    intake_line.drop_flow("pump tripped")
    intake_line.settle_flow()
    assert not intake_line.latches.is_set("flow_lost")
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    assert intake_line.inject_dose("BATCH-BACK", 60.0, sheet.sheet_id).ppm > 0


def test_reversing_the_pump_engages_the_treatment_bypass(intake_line):
    result = intake_line.reverse_pump("discharge")
    assert intake_line.bypass.engaged() is True
    assert result["bypass_settled"] is True
    assert result["settled"] is True
    assert intake_line.bypass.engagements() == 1


def test_reversal_closes_the_treatment_inlet_valve(intake_line):
    intake_line.reverse_pump("discharge")
    assert intake_line.header.is_open(intake_line.settings.treat.inlet_valve) is False
    intake_line.resume_intake()
    assert intake_line.header.is_open(intake_line.settings.treat.inlet_valve) is True
    assert intake_line.bypass.engaged() is False


def test_reversal_without_a_running_pump_is_rejected(line):
    with pytest.raises(Exception) as denied:
        line.reverse_pump("discharge")
    assert denied.value.code == "configuration_error"


def test_pump_status_reports_flow_and_direction(intake_line):
    status = intake_line.pump.status()
    assert status["running"] is True
    assert status["direction"] == "intake"
    assert status["outlet_open"] is True
    assert intake_line.flow.status()["ready"] is True
