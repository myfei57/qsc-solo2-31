"""水流建立窗口、换向稳定与停机状态的语义。"""

from __future__ import annotations


def test_flow_stays_unavailable_until_the_last_settle_tick(line):
    line.confirm_valve(line.settings.pump.outlet_valve)
    line.start_pump("intake")
    line.tick(line.settings.pump.settle_ticks - 1)
    assert line.flow.ready() is False
    line.tick(1)
    assert line.flow.ready() is True


def test_flow_meter_reports_the_remaining_settle_ticks(line):
    line.confirm_valve(line.settings.pump.outlet_valve)
    line.start_pump("intake")
    assert line.flow.settle_remaining() == line.settings.pump.settle_ticks
    line.settle_flow()
    assert line.flow.settle_remaining() == 0


def test_flow_reading_returns_to_zero_after_a_drop(intake_line):
    intake_line.drop_flow("pump tripped")
    assert intake_line.flow.ready() is False
    assert intake_line.flow.read() == 0.0
    intake_line.settle_flow()
    assert intake_line.flow.ready() is True


def test_bypass_reports_settling_before_it_counts_as_engaged(intake_line):
    intake_line.bypass.engage("pump reversal")
    assert intake_line.bypass.engaged() is True
    assert intake_line.bypass.settled() is False
    intake_line.tick(intake_line.settings.treat.bypass_settle_ticks)
    assert intake_line.bypass.settled() is True


def test_direction_change_reports_settling_before_it_is_stable(intake_line):
    intake_line.direction.command("discharge")
    assert intake_line.direction.settled() is False
    intake_line.tick(intake_line.settings.pump.reverse_settle_ticks)
    assert intake_line.direction.settled() is True


def test_stopping_the_pump_clears_the_direction(intake_line):
    intake_line.pump.stop()
    assert intake_line.pump.running() is False
    assert intake_line.pump.direction() == "stopped"
