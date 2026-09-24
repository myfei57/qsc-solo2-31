"""标识登记、阀位落位与连接方向的语义。"""

from __future__ import annotations

import pytest

from bwms.errors import UnknownDeviceError


def test_unknown_device_tag_is_rejected(line):
    with pytest.raises(UnknownDeviceError):
        line.registry.require("NOPE-99")
    with pytest.raises(UnknownDeviceError):
        line.header.require("V-NOPE-99")


def test_unknown_device_tag_is_not_silently_registered(line):
    before = line.registry.summary()["count"]
    with pytest.raises(UnknownDeviceError):
        line.registry.require("NOPE-98")
    assert line.registry.summary()["count"] == before


def test_seat_confirmation_is_bound_to_a_single_valve(line):
    line.confirm_valve(line.settings.tank("TB-01").inlet_valve)
    assert line.header.is_seated(line.settings.tank("TB-01").inlet_valve) is True
    assert line.header.is_seated(line.settings.tank("TB-02").inlet_valve) is False
    assert line.header.is_seated(line.settings.tank("TB-03").inlet_valve) is False


def test_closing_a_valve_clears_its_seat_confirmation(line):
    valve = line.settings.tank("TB-01").inlet_valve
    line.confirm_valve(valve)
    assert line.header.is_seated(valve) is True
    line.header.close(valve)
    assert line.header.is_seated(valve) is False
    assert line.header.is_open(valve) is False


def test_open_valves_only_lists_confirmed_valves(line):
    line.confirm_valve(line.settings.pump.outlet_valve)
    assert line.header.open_tags() == (line.settings.pump.outlet_valve,)


def test_load_path_is_directional(line):
    path = line.topology.route(line.settings.pump.tag, "TB-01")
    assert path[0] == line.settings.pump.tag
    assert path[-1] == "TB-01"
    with pytest.raises(UnknownDeviceError):
        line.topology.route("TB-01", line.settings.pump.tag)


def test_each_valve_reports_its_own_medium_and_seat_tick(line):
    valve = line.settings.pump.outlet_valve
    line.confirm_valve(valve)
    snapshot = {item["tag"]: item for item in line.header.snapshot()}
    assert snapshot[valve]["medium"] == "sea water"
    assert snapshot[valve]["seated"] is True
    assert snapshot[valve]["seated_tick"] == line.clock.tick
    assert [device.tag for device in line.registry.by_kind("valve")]
