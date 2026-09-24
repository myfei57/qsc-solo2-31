"""检测周期窗口、中和保持期与处理状态的语义。"""

from __future__ import annotations

import pytest

from bwms.errors import StageOrderError
from bwms.treat.neutralize import STANDBY, TREATING


def test_uv_window_is_aligned_to_the_detection_cycle(line):
    line.tick(5)
    assert line.reactor.window_bounds() == (4, 8)
    assert line.reactor.cycle_of() == 1


def test_uv_window_covers_a_reading_taken_at_the_cycle_start(line):
    line.tick(line.settings.treat.uv_window_ticks)
    line.read_intensity(60.0)
    assert line.reactor.readings_in_window()
    assert line.reactor.intensity_ok() is True


def test_uv_window_ignores_readings_from_the_previous_cycle(line):
    line.read_intensity(60.0)
    line.tick(line.settings.treat.uv_window_ticks)
    assert line.reactor.readings_in_window() == ()
    assert line.reactor.intensity_ok() is False


def test_uv_window_does_not_carry_a_low_reading_into_the_next_cycle(line):
    line.read_intensity(70.0)
    line.read_intensity(40.0)
    line.tick(line.settings.treat.uv_window_ticks)
    line.read_intensity(70.0)
    verdict = line.reactor.window_verdict()
    assert verdict["min_value"] == 70.0
    assert verdict["pass"] is True


def test_neutralizer_refuses_to_run_before_treatment(line):
    assert line.treat.state() == STANDBY
    with pytest.raises(StageOrderError):
        line.treat.neutralize(10.0, 3.0)


def test_neutralizer_reports_the_remaining_hold_ticks(line):
    line.treat.start_treatment(20.0)
    assert line.treat.state() == TREATING
    line.treat.neutralize(20.0, line.settings.treat.neutralizer_ppm)
    assert line.treat.hold_remaining() == line.settings.treat.neutralizer_hold_ticks
    assert line.treat.ready() is False
    line.tick(line.settings.treat.neutralizer_hold_ticks)
    assert line.treat.hold_remaining() == 0
    assert line.treat.ready() is True
