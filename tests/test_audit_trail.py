"""审计留痕定级与合规汇总取数的语义。"""

from __future__ import annotations

from bwms.store.records import KIND_MEASUREMENT


def test_denied_action_is_recorded_with_its_source(line):
    line.deny("compliance.discharge")
    entries = [item for item in line.audit.entries() if item.action == "deny"]
    assert entries
    entry = entries[-1]
    assert entry.topic == "interlock"
    assert entry.severity == "warning"
    assert entry.detail["target"] == "compliance.discharge"


def test_recalibration_is_recorded_as_an_alarm(line):
    line.recalibrate_level(3.0, "年度校验")
    alarms = [item for item in line.audit.alarms() if item.topic == line.settings.level.tag]
    assert alarms
    assert alarms[-1].action == "recalibrate"


def test_bypass_engagement_is_recorded_as_an_alarm(settings, clock):
    from bwms.app import build_line

    active = build_line(settings, clock)
    active.confirm_valve(active.settings.pump.outlet_valve)
    active.start_pump("intake")
    active.reverse_pump("discharge")
    alarms = [item for item in active.audit.alarms() if item.action == "bypass"]
    assert alarms


def test_audit_entries_carry_the_event_tick(line):
    line.tick(4)
    line.recalibrate_level(1.0, "复核")
    assert line.audit.entries()[-1].tick == line.clock.tick


def test_report_excludes_tombstoned_records(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    before = line.report.build()["records"]["total_visible"]
    line.store.tombstone(record.seq, "operator retracted the entry")
    after = line.report.build()["records"]["total_visible"]
    assert after == before - 1


def test_report_counts_match_the_detail_query(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    report = line.report.build()
    assert report["records"]["total_visible"] == len(line.records())


def test_report_stays_consistent_with_the_replay_check(line):
    line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    assert line.report.build()["consistent"] is True
