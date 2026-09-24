"""取样与合规：吹扫顺序、取样前置、判定联动、许可时效与排放窗口。"""

from __future__ import annotations

import pytest

from bwms.errors import (
    InterlockError,
    PermitError,
    StageOrderError,
    ThresholdNotMetError,
)
from bwms.store.records import KIND_DISCHARGE, KIND_SAMPLE, RecordFilter


def test_purge_steps_must_follow_the_line_sequence(line):
    with pytest.raises(StageOrderError) as denied:
        line.line.advance("flush")
    assert denied.value.expected == "drain"


def test_purge_line_completes_all_three_steps(intake_line):
    intake_line.confirm_valve(intake_line.settings.treat.sample_valve)
    intake_line.start_purge()
    intake_line.finish_purge()
    status = intake_line.line.status()
    assert status["done"] == ["drain", "flush", "dwell"]
    assert status["completed"] is True
    assert intake_line.purge.clean() is True


def test_sampling_before_the_purge_finishes_is_denied(intake_line):
    intake_line.confirm_valve(intake_line.settings.treat.sample_valve)
    intake_line.start_purge()
    with pytest.raises(InterlockError) as denied:
        intake_line.take_sample("TB-01")
    assert "line_purged" in denied.value.unmet


def test_sampling_cannot_skip_the_purge_stage(intake_line):
    with pytest.raises(StageOrderError):
        intake_line.engine.step("AN-01", "sensor.sample")


def test_sample_after_purge_records_a_batch(intake_line):
    intake_line.confirm_valve(intake_line.settings.treat.sample_valve)
    intake_line.start_purge()
    intake_line.finish_purge()
    batch = intake_line.take_sample("TB-01")
    assert batch["batch_id"] == "BATCH-0001"
    assert intake_line.store.count(KIND_SAMPLE) == 1


def test_analysis_is_denied_when_no_sample_record_was_committed(intake_line):
    intake_line.confirm_valve(intake_line.settings.treat.sample_valve)
    intake_line.start_purge()
    intake_line.finish_purge()
    intake_line.engine.step("AN-01", "sensor.sample")
    with pytest.raises(InterlockError) as denied:
        intake_line.engine.step("AN-01", "sensor.analyze")
    assert "sample_drawn" in denied.value.unmet


def test_non_compliant_analysis_trips_the_sampling_latch(chain, line):
    context = chain(turbidity_ntu=40.0, organisms_per_m3=250.0, stop_after="analysis")
    assert context["analysis"]["compliant"] is False
    assert line.latches.is_set("sampling_dirty")


def test_permit_is_refused_after_a_non_compliant_verdict(chain, line):
    context = chain(turbidity_ntu=40.0, stop_after="analysis")
    sheet = line.confirm_parameters("compliance", "chief-officer", 240)
    with pytest.raises(ThresholdNotMetError):
        line.issue_permit(context["batch"]["batch_id"], sheet.sheet_id)


def test_discharge_is_denied_without_neutralization(chain, line):
    context = chain(stop_after="analysis")
    sheet = line.confirm_parameters("compliance", "chief-officer", 240)
    permit = line.issue_permit(context["batch"]["batch_id"], sheet.sheet_id)
    with pytest.raises(InterlockError) as denied:
        line.discharge(
            context["batch"]["batch_id"],
            context["tank_tag"],
            30.0,
            permit["permit_id"],
        )
    assert "neutralized_ready" in denied.value.unmet


def test_expired_permit_is_rejected_on_discharge(chain, line):
    context = chain()
    line.tick(line.settings.compliance.permit_valid_ticks + 5)
    with pytest.raises(InterlockError) as denied:
        line.discharge(
            context["batch"]["batch_id"],
            context["tank_tag"],
            30.0,
            context["permit"]["permit_id"],
        )
    assert "permit_expired" in denied.value.unmet


def test_permit_verification_rejects_expired_certificate(chain, line):
    context = chain()
    line.tick(line.settings.compliance.permit_valid_ticks + 1)
    with pytest.raises(PermitError):
        line.permits.verify(context["permit"]["permit_id"])


def test_discharge_is_denied_while_the_treatment_bypass_is_engaged(chain, line):
    context = chain()
    line.reverse_pump("discharge")
    with pytest.raises(InterlockError) as denied:
        line.discharge(
            context["batch"]["batch_id"],
            context["tank_tag"],
            30.0,
            context["permit"]["permit_id"],
        )
    assert "bypass_clear" in denied.value.unmet


def test_full_discharge_cycle_records_and_closes_the_window(chain, line):
    context = chain()
    release = line.discharge(
        context["batch"]["batch_id"],
        context["tank_tag"],
        60.0,
        context["permit"]["permit_id"],
    )
    assert release["volume_m3"] == 60.0
    assert line.releaser.releases() == 1
    assert line.store.count(KIND_DISCHARGE) == 1
    assert line.windows.open_windows() == ()


def test_discharge_record_carries_batch_permit_and_window(chain, line):
    context = chain()
    line.discharge(
        context["batch"]["batch_id"],
        context["tank_tag"],
        40.0,
        context["permit"]["permit_id"],
    )
    records = line.records(RecordFilter(kinds=(KIND_DISCHARGE,)))
    assert records[0].payload["permit_id"] == context["permit"]["permit_id"]
    assert records[0].payload["window_id"].startswith("WIN-")
