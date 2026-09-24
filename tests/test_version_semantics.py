"""版本语义：参数代际、确认单时效、基线过期与代际顶替。"""

from __future__ import annotations

import pytest

from bwms.errors import (
    ExpiredBaselineError,
    ExpiredConfirmationError,
    StaleGenerationError,
)
from bwms.store.records import KIND_PARAMETER, RecordFilter


def test_publishing_parameters_bumps_the_generation(line):
    first = line.generations.current("dose")
    second = line.publish_parameters("dose", {"target_ppm": 7.0, "max_ppm": 12.0})
    assert second.generation == first.generation + 1
    assert line.generations.current("dose").generation == second.generation


def test_generation_history_is_kept_for_audit(line):
    line.publish_parameters("dose", {"target_ppm": 7.0})
    history = line.generations.history("dose")
    assert [item.generation for item in history] == [1, 2]
    assert line.generations.get("dose", 1).value("target_ppm") == 6.5


def test_confirmation_sheet_for_current_generation_verifies(line):
    sheet = line.confirm_parameters("dose", "chief-officer", 30)
    verified = line.confirmations.verify(sheet.sheet_id, "dose", sheet.generation)
    assert verified.sheet_id == sheet.sheet_id
    assert verified.remaining(line.clock.tick) == 30


def test_expired_confirmation_rejects_dose_injection(intake_line):
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 2)
    intake_line.tick(3)
    with pytest.raises(ExpiredConfirmationError):
        intake_line.inject_dose("BATCH-EXPIRED", 60.0, sheet.sheet_id)


def test_sheet_for_superseded_generation_is_rejected(intake_line):
    sheet = intake_line.confirm_parameters("dose", "chief-officer", 60)
    intake_line.publish_parameters("dose", {"target_ppm": 5.0, "max_ppm": 12.0})
    with pytest.raises(StaleGenerationError):
        intake_line.inject_dose("BATCH-STALE", 60.0, sheet.sheet_id)


def test_require_current_rejects_older_generation(line):
    line.publish_parameters("dose", {"target_ppm": 5.0})
    with pytest.raises(StaleGenerationError):
        line.generations.require_current("dose", 1)


def test_captured_baseline_resolves_while_fresh(line):
    baseline = line.capture_baseline("dose", "BASE", 20)
    assert line.resolve_baseline(baseline.baseline_id).digest == baseline.digest


def test_expired_baseline_is_rejected(line):
    baseline = line.capture_baseline("dose", "BASE", 2)
    line.tick(5)
    with pytest.raises(ExpiredBaselineError):
        line.resolve_baseline(baseline.baseline_id)


def test_baseline_of_superseded_generation_is_rejected(line):
    baseline = line.capture_baseline("dose", "BASE", 60)
    line.publish_parameters("dose", {"target_ppm": 5.0})
    with pytest.raises(StaleGenerationError):
        line.resolve_baseline(baseline.baseline_id)


def test_parameter_release_is_recorded_in_the_stream(line):
    line.publish_parameters("dose", {"target_ppm": 5.0})
    parameters = line.records(RecordFilter(subject="dose"))
    released = [item for item in parameters if item.kind == KIND_PARAMETER]
    assert [item.generation for item in released] == [1, 2]
