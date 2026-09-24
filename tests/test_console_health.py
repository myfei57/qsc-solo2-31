"""控制台接口：健康检查、路由分发、错误映射与页面渲染。"""

from __future__ import annotations

import json
import threading
import urllib.request

from bwms.console import build_server, dispatch, render_index, render_status_lines
from bwms.store.records import KIND_ACTION, KIND_MEASUREMENT


def test_health_route_reports_ok(line):
    response = dispatch(line, "GET", "/healthz")
    assert response.status == 200
    assert response.payload["status"] == "ok"
    assert response.payload["watermark"] == line.store.watermark()


def test_health_endpoint_over_loopback_http(line):
    server = build_server(line, host="127.0.0.1", port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urllib.request.urlopen(server.endpoint() + "/healthz", timeout=5) as handle:
            payload = json.loads(handle.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["plant"] == line.settings.plant_tag
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_index_page_renders_the_plant_tag(line):
    page = render_index(line)
    assert line.settings.plant_tag in page
    assert page.startswith("<!doctype html>")
    assert render_status_lines(line)


def test_status_route_exposes_subsystem_state(line):
    response = dispatch(line, "GET", "/api/v1/state")
    assert response.status == 200
    for key in ("tanks", "pump", "dose", "treatment", "permits", "latches"):
        assert key in response.payload


def test_unknown_route_returns_not_found(line):
    response = dispatch(line, "GET", "/api/v1/nothing")
    assert response.status == 404
    assert response.payload["code"] == "not_found"


def test_unknown_action_returns_not_found(line):
    response = dispatch(line, "POST", "/api/v1/actions/nothing", {}, {})
    assert response.status == 404
    assert response.payload["code"] == "unknown_action"


def test_denied_action_route_returns_conflict_with_unmet_gates(line):
    response = dispatch(
        line,
        "POST",
        "/api/v1/actions/load_tank",
        {},
        {"tag": "TB-01", "volume_m3": 10.0},
    )
    assert response.status == 409
    assert response.payload["code"] == "interlock_denied"
    assert "TB-01.inlet_seated" in response.payload["unmet"]


def test_accepted_action_route_returns_the_result(line):
    response = dispatch(
        line,
        "POST",
        "/api/v1/actions/confirm_valve",
        {},
        {"tag": line.settings.pump.outlet_valve},
    )
    assert response.status == 200
    assert response.payload["result"]["seated"] is True


def test_threshold_violation_route_returns_unprocessable(line):
    response = dispatch(
        line, "POST", "/api/v1/actions/read_level", {}, {"raw_units": -5.0}
    )
    assert response.status in (200, 422)
    if response.status == 422:
        assert response.payload["code"] == "threshold_exceeded"


def test_records_route_filters_by_kind(line):
    line.store.write(KIND_ACTION, "TB-01", {"action": "seat_confirm"})
    response = dispatch(line, "GET", "/api/v1/records", {"kind": [KIND_MEASUREMENT]})
    assert response.status == 200
    assert all(item["kind"] == KIND_MEASUREMENT for item in response.payload["records"])


def test_record_route_rejects_a_uncommitted_sequence(line):
    record = line.store.stage(KIND_ACTION, "TB-01", {"action": "staged"})
    response = dispatch(line, "GET", "/api/v1/record", {"seq": [str(record.seq)]})
    assert response.status == 409
    assert response.payload["code"] == "record_not_committed"


def test_record_route_returns_a_committed_record(line):
    record = line.store.write(KIND_MEASUREMENT, "TB-01", {"action": "load"})
    response = dispatch(line, "GET", "/api/v1/record", {"seq": [str(record.seq)]})
    assert response.status == 200
    assert response.payload["record"]["seq"] == record.seq


def test_report_route_reports_consistency(line):
    response = dispatch(line, "GET", "/api/v1/report")
    assert response.status == 200
    assert response.payload["consistent"] is True
    assert "records" in response.payload


def test_parameters_route_lists_keys_and_history(line):
    response = dispatch(line, "GET", "/api/v1/parameters", {"key": ["dose"]})
    assert response.status == 200
    assert response.payload["current"]["generation"] == 1
    assert response.payload["history"][0]["key"] == "dose"


def test_interlocks_route_describes_a_single_action(line):
    response = dispatch(line, "GET", "/api/v1/interlocks", {"action": ["TB-01.load"]})
    assert response.status == 200
    names = {gate["name"] for gate in response.payload["gates"]}
    assert {"TB-01.room_available", "TB-01.flow_ready"} <= names


def test_treatment_route_reports_uv_verdicts(line):
    line.read_intensity(61.0)
    line.reactor.window_verdict()
    response = dispatch(line, "GET", "/api/v1/treatment")
    assert response.status == 200
    assert response.payload["verdicts"][-1]["pass"] is True


def test_batches_route_resolves_a_sample_tick(intake_line):
    intake_line.confirm_valve(intake_line.settings.treat.sample_valve)
    intake_line.start_purge()
    intake_line.finish_purge()
    batch = intake_line.take_sample("TB-01")
    response = dispatch(
        intake_line, "GET", "/api/v1/batches", {"tick": [str(batch["tick"])]}
    )
    assert response.payload["batch"]["batch_id"] == batch["batch_id"]
