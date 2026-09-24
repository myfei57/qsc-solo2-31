"""舱容装载：按当前舱容规划、满舱拒绝、越限拒绝与舱容修订。"""

from __future__ import annotations

import pytest

from bwms.errors import InterlockError, StageOrderError, ThresholdError


def test_load_plan_uses_current_remaining_capacity(intake_line):
    first = intake_line.plan_load(500.0)
    assert [item["tag"] for item in first["allocations"]] == ["TB-01", "TB-02"]
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 420.0)
    second = intake_line.plan_load(500.0)
    assert [item["tag"] for item in second["allocations"]] == ["TB-02", "TB-03"]


def test_load_plan_never_allocates_a_full_tank(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 420.0)
    plan = intake_line.plan_load(420.0)
    assert "TB-01" not in [item["tag"] for item in plan["allocations"]]
    assert plan["allocations"][0]["tag"] == "TB-02"


def test_load_plan_reports_unallocated_volume_when_full(intake_line):
    plan = intake_line.plan_load(intake_line.settings.total_capacity_m3() + 100.0)
    assert plan["complete"] is False
    assert plan["unallocated_m3"] == 100.0


def test_load_plan_order_follows_capacity_descending(intake_line):
    plan = intake_line.plan_load(2000.0)
    assert [item["tag"] for item in plan["allocations"]] == ["TB-01", "TB-02", "TB-03"]
    capacities = [item["remaining_before_m3"] for item in plan["allocations"]]
    assert capacities == sorted(capacities, reverse=True)


def test_load_plan_snapshot_reflects_the_last_plan(intake_line):
    intake_line.plan_load(500.0)
    snapshot = intake_line.planner.last_snapshot()
    assert snapshot["remaining"]["TB-01"] == 420.0
    assert snapshot["tick"] == intake_line.clock.tick


def test_capacity_resize_bumps_revision_and_reaches_the_plan(intake_line):
    revision = intake_line.resize_tank("TB-03", 350.0, "加装隔板")
    assert revision["revision"] == 2
    plan = intake_line.plan_load(1200.0)
    revisions = {item["tag"]: item["capacity_revision"] for item in plan["allocations"]}
    assert revisions["TB-03"] == 2
    assert revisions["TB-01"] == 1


def test_load_beyond_remaining_capacity_is_rejected(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-02").inlet_valve)
    with pytest.raises(ThresholdError) as exceeded:
        intake_line.load_tank("TB-02", 500.0)
    assert exceeded.value.field == "load_volume_m3"
    assert exceeded.value.limit == 360.0


def test_loading_a_full_tank_is_rejected(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 420.0)
    with pytest.raises(InterlockError) as denied:
        intake_line.load_tank("TB-01", 10.0)
    assert "TB-01.room_available" in denied.value.unmet


def test_non_positive_load_volume_is_rejected(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    with pytest.raises(ThresholdError):
        intake_line.load_tank("TB-01", 0.0)


def test_discharge_beyond_stored_volume_is_rejected(intake_line):
    intake_line.bay.load("TB-01", 50.0)
    with pytest.raises(ThresholdError):
        intake_line.bay.discharge("TB-01", 60.0)


def test_loading_a_full_tank_is_rejected_by_the_state_machine(intake_line):
    intake_line.bay.load("TB-01", 420.0)
    assert intake_line.bay.state("TB-01") == "full"
    with pytest.raises(StageOrderError) as denied:
        intake_line.bay.load("TB-01", 1.0)
    assert denied.value.expected == "discharging"


def test_discharging_an_empty_tank_is_rejected_by_the_state_machine(intake_line):
    with pytest.raises(StageOrderError) as denied:
        intake_line.bay.discharge("TB-02", 1.0)
    assert denied.value.got == "discharging"


def test_load_writes_a_committed_measurement_record(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 60.0)
    loads = [
        record
        for record in intake_line.records()
        if record.subject == "TB-01" and record.payload.get("action") == "load"
    ]
    assert len(loads) == 1
    assert loads[0].seq <= intake_line.store.watermark()


def test_tank_totals_report_fleet_volume(intake_line):
    intake_line.confirm_valve(intake_line.settings.tank("TB-01").inlet_valve)
    intake_line.load_tank("TB-01", 420.0)
    totals = intake_line.bay.totals()
    assert totals["volume_m3"] == 420.0
    assert totals["full"] == ["TB-01"]
