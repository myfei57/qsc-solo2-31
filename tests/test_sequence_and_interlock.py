"""状态机与联锁：阶段顺序、闩锁置位/解除、跨组件前置门控。"""

from __future__ import annotations

import pytest

from bwms.errors import InterlockError, LatchError, SequenceError, StageOrderError


def test_stage_out_of_order_is_rejected(line):
    with pytest.raises(StageOrderError) as denied:
        line.engine.step("TB-01", "TB-01.load")
    assert denied.value.expected == "TB-01.seat"
    assert denied.value.got == "TB-01.load"


def test_stage_order_error_leaves_the_device_where_it_was(line):
    line.engine.arm("TB-01")
    with pytest.raises(StageOrderError):
        line.engine.step("TB-01", "TB-01.settle")
    assert line.engine.current("TB-01") is None
    assert line.engine.next_stage("TB-01") == "TB-01.seat"


def test_sequence_cannot_advance_past_the_last_stage(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 60.0)
    assert intake_line.engine.status("TB-01")["complete"] is True
    with pytest.raises(SequenceError) as denied:
        intake_line.engine.step("TB-01", "TB-01.settle")
    assert denied.value.code == "sequence_error"


def test_tank_load_is_denied_without_inlet_seat_confirmation(intake_line):
    with pytest.raises(InterlockError) as denied:
        intake_line.load_tank("TB-01", 30.0)
    assert "TB-01.inlet_seated" in denied.value.unmet


def test_load_is_denied_while_flow_is_not_established(line):
    line.confirm_valve(line.settings.tank("TB-01").inlet_valve)
    with pytest.raises(InterlockError) as denied:
        line.load_tank("TB-01", 30.0)
    assert "TB-01.flow_ready" in denied.value.unmet


def test_dose_injection_is_denied_before_flow_settles(line):
    line.confirm_valve(line.settings.pump.outlet_valve)
    line.confirm_valve(line.settings.dose.inlet_valve)
    line.confirm_valve(line.settings.treat.inlet_valve)
    line.start_pump("intake")
    sheet = line.confirm_parameters("dose", "chief-officer", 60)
    with pytest.raises(InterlockError) as denied:
        line.inject_dose("BATCH-EARLY", 60.0, sheet.sheet_id)
    assert "flow_established" in denied.value.unmet


def test_permit_request_is_denied_before_the_analysis_verdict(line):
    with pytest.raises(InterlockError) as denied:
        line.engine.step("PM-01", "compliance.permit")
    assert "analysis_verdict_ready" in denied.value.unmet


def test_uv_low_intensity_trips_the_latch(line):
    line.read_intensity(40.0)
    assert line.latches.is_set("uv_low")
    assert line.latches.detail("uv_low")["trips"] == 1


def test_uv_latch_blocks_the_treatment_stage(line):
    line.confirm_valve(line.settings.treat.inlet_valve)
    line.read_intensity(40.0)
    line.engine.arm("TU-01")
    line.engine.step("TU-01", "treat.prepare")
    with pytest.raises(LatchError) as denied:
        line.engine.step("TU-01", "treat.uv")
    assert "uv_low" in denied.value.latches


def test_uv_latch_needs_a_full_clear_streak_to_release(line):
    line.read_intensity(40.0)
    line.tick(4)
    line.read_intensity(60.0)
    line.read_intensity(60.0)
    assert line.latches.is_set("uv_low")
    line.read_intensity(60.0)
    assert not line.latches.is_set("uv_low")


def test_uv_stage_runs_after_recovery_in_a_fresh_window(line):
    line.confirm_valve(line.settings.treat.inlet_valve)
    line.read_intensity(40.0)
    line.tick(4)
    for _ in range(3):
        line.read_intensity(60.0)
    line.engine.arm("TU-01")
    line.engine.step("TU-01", "treat.prepare")
    assert line.engine.step("TU-01", "treat.uv")["stage"] == "treat.uv"


def test_interlock_snapshot_reports_each_gate_state(line):
    snapshot = line.interlocks.snapshot()
    assert "TB-01.load" in snapshot
    gates = {item["name"]: item["satisfied"] for item in snapshot["TB-01.load"]}
    assert gates["TB-01.flow_ready"] is False


def test_denied_action_is_written_to_audit(line):
    line.deny("compliance.discharge")
    denied = [entry for entry in line.audit.entries() if entry.action == "deny"]
    assert denied
    assert denied[-1].severity == "warning"


def test_latch_keeps_blocking_until_explicitly_cleared(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.mark_sampling_dirty("line residue suspected")
    assert intake_line.latches.active() == ("sampling_dirty",)
    assert intake_line.latches.blocked(("sampling_dirty", "uv_low")) == ("sampling_dirty",)
