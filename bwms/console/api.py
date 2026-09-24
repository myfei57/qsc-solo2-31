"""请求分发。

先把路径、方法与请求体映射成一个 (状态码, 响应体) 的决定，再由 HTTP 层负责
收发；这样一来控制台的每个接口都可以脱离网络直接调用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import ControlError, InterlockError, ThresholdError
from ..store.records import RecordFilter


@dataclass(frozen=True)
class Response:
    status: int
    payload: dict[str, Any] = field(default_factory=dict)

    def body(self) -> bytes:
        return (json.dumps(self.payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )


def _int_param(params: dict[str, list[str]], name: str, default: int | None) -> int | None:
    values = params.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError:
        return default


def _str_param(params: dict[str, list[str]], name: str, default: str | None) -> str | None:
    values = params.get(name)
    return values[0] if values else default


def _records(line, params: dict[str, list[str]]) -> Response:
    limit = _int_param(params, "limit", line.settings.console.page_size)
    criteria = RecordFilter(
        kinds=tuple(filter(None, (_str_param(params, "kind", "") or "").split(","))),
        subject=_str_param(params, "subject", None),
        since_tick=_int_param(params, "since", None),
        until_tick=_int_param(params, "until", None),
        epoch=_int_param(params, "epoch", None),
        include_tombstones=_str_param(params, "tombstones", "0") == "1",
        limit=limit,
    )
    return Response(
        200,
        {
            "watermark": line.store.watermark(),
            "digest": line.store.digest(),
            "filter": criteria.to_dict(),
            "records": [record.to_dict() for record in line.records(criteria)],
        },
    )


def _tanks(line, params: dict[str, list[str]]) -> Response:
    tick = _int_param(params, "tick", None)
    if tick is None:
        return Response(200, {"tanks": line.bay.snapshot(), "totals": line.bay.totals()})
    return Response(
        200,
        {
            "as_of": tick,
            "tanks": {
                tag: line.bay.as_of(tag, tick) for tag in line.settings.tank_tags()
            },
        },
    )


def _parameters(line, params: dict[str, list[str]]) -> Response:
    key = _str_param(params, "key", None)
    if key is None:
        return Response(
            200,
            {
                "keys": list(line.generations.keys()),
                "parameters": line.generations.snapshot(),
            },
        )
    return Response(
        200,
        {
            "key": key,
            "current": line.generations.current(key).to_dict(),
            "history": [item.to_dict() for item in line.generations.history(key)],
            "confirmations": [item.to_dict() for item in line.confirmations.sheets(key)],
        },
    )


def _actions(line) -> dict[str, Callable[[dict[str, Any]], Any]]:
    return {
        "pump_start": lambda body: line.start_pump(str(body.get("direction", "intake"))),
        "settle_flow": lambda body: line.settle_flow(),
        "drop_flow": lambda body: line.drop_flow(str(body.get("reason", "manual"))),
        "read_intensity": lambda body: line.read_intensity(float(body["value"])),
        "run_treatment": lambda body: line.run_treatment(float(body["volume_m3"])),
        "inject_dose": lambda body: line.inject_dose(
            str(body["batch_key"]), float(body["volume_m3"]), str(body["sheet_id"])
        ),
        "plan_load": lambda body: line.plan_load(float(body["volume_m3"])),
        "confirm_valve": lambda body: line.confirm_valve(str(body["tag"])),
        "load_tank": lambda body: line.load_tank(
            str(body["tag"]), float(body["volume_m3"])
        ),
        "read_level": lambda body: line.read_level(float(body["raw_units"])),
        "recalibrate_level": lambda body: line.recalibrate_level(
            float(body["offset_m3"]), str(body.get("note", ""))
        ),
        "start_purge": lambda body: line.start_purge(),
        "finish_purge": lambda body: line.finish_purge(),
        "take_sample": lambda body: line.take_sample(str(body["tag"])),
        "analyze_sample": lambda body: line.analyze_sample(
            str(body["batch_id"]),
            float(body["turbidity_ntu"]),
            float(body["organisms_per_m3"]),
        ),
        "neutralize": lambda body: line.neutralize(
            float(body["volume_m3"]), str(body["sheet_id"])
        ),
        "issue_permit": lambda body: line.issue_permit(
            str(body["batch_id"]), str(body["sheet_id"])
        ),
        "discharge": lambda body: line.discharge(
            str(body["batch_id"]),
            str(body["tag"]),
            float(body["volume_m3"]),
            str(body["permit_id"]),
        ),
        "reverse_pump": lambda body: line.reverse_pump(str(body.get("direction", "discharge"))),
        "resume_intake": lambda body: line.resume_intake(),
        "publish_parameters": lambda body: line.publish_parameters(
            str(body["key"]), dict(body.get("values", {}))
        ).to_dict(),
        "confirm_parameters": lambda body: line.confirm_parameters(
            str(body["key"]),
            str(body.get("operator", "operator")),
            int(body.get("validity_ticks", 60)),
            str(body.get("note", "")),
        ).to_dict(),
        "capture_baseline": lambda body: line.capture_baseline(
            str(body["key"]),
            str(body.get("label", "BASE")),
            int(body.get("valid_ticks", 120)),
        ).to_dict(),
        "roll_epoch": lambda body: line.roll_epoch(str(body.get("reason", "manual"))),
        "mark_sampling_dirty": lambda body: line.mark_sampling_dirty(
            str(body.get("reason", "manual"))
        ),
        "advance_clock": lambda body: {"tick": line.tick(int(body.get("steps", 1)))},
        "rollback": lambda body: line.rollback(
            int(body["seq"]), str(body.get("reason", "manual"))
        ).to_dict(),
        "resize_tank": lambda body: line.resize_tank(
            str(body["tag"]), float(body["capacity_m3"]), str(body.get("note", ""))
        ),
        "resolve_baseline": lambda body: line.resolve_baseline(
            str(body["baseline_id"])
        ).to_dict(),
    }


def dispatch(
    line,
    method: str,
    path: str,
    params: dict[str, list[str]] | None = None,
    body: dict[str, Any] | None = None,
) -> Response:
    params = params or {}
    body = body or {}
    method = method.upper()

    if method == "GET" and path in ("/healthz", "/health"):
        return Response(200, line.health())
    if method == "GET" and path == "/api/v1/state":
        return Response(200, line.status())
    if method == "GET" and path == "/api/v1/report":
        return Response(200, line.report.build())
    if method == "GET" and path == "/api/v1/tanks":
        return _tanks(line, params)
    if method == "GET" and path == "/api/v1/records":
        return _records(line, params)
    if method == "GET" and path == "/api/v1/record":
        seq = _int_param(params, "seq", None)
        if seq is None:
            return Response(400, {"code": "missing_seq"})
        try:
            return Response(200, {"record": line.store.get(seq).to_dict()})
        except ControlError as failed:
            return Response(409, failed.as_dict())
    if method == "GET" and path == "/api/v1/parameters":
        return _parameters(line, params)
    if method == "GET" and path == "/api/v1/audit":
        limit = _int_param(params, "limit", line.settings.console.page_size)
        topic = _str_param(params, "topic", None)
        if topic is None:
            entries = line.audit.entries(limit)
        elif _str_param(params, "mode", "entries") == "tail":
            entries = line.audit.tail(limit or 5)
        else:
            entries = line.audit.by_component(topic)
        return Response(
            200,
            {
                "topic": topic,
                "entries": [item.to_dict() for item in entries],
                "alarms": [item.to_dict() for item in line.audit.alarms()],
            },
        )
    if method == "GET" and path == "/api/v1/treatment":
        limit = _int_param(params, "limit", line.settings.console.page_size)
        return Response(
            200,
            {
                "reactor": line.reactor.status(),
                "verdicts": [item for item in line.reactor.verdicts(limit)],
                "intensity": [item.to_dict() for item in line.reactor.history(limit)],
            },
        )
    if method == "GET" and path == "/api/v1/batches":
        tick = _int_param(params, "tick", None)
        if tick is None:
            return Response(200, {"batches": line.batches.status()})
        batch = line.batches.of_tick(tick)
        return Response(
            200,
            {"tick": tick, "batch": None if batch is None else batch.to_dict()},
        )
    if method == "GET" and path == "/api/v1/interlocks":
        action = _str_param(params, "action", None)
        if action is None:
            return Response(200, {"interlocks": line.interlocks.snapshot()})
        return Response(200, line.interlocks.describe(action))
    if method == "GET" and path == "/api/v1/sequences":
        return Response(200, {"sequences": line.engine.snapshot()})
    if method == "POST" and path.startswith("/api/v1/actions/"):
        name = path.rsplit("/", 1)[-1]
        handler = _actions(line).get(name)
        if handler is None:
            return Response(404, {"code": "unknown_action", "action": name})
        try:
            return Response(200, {"action": name, "result": handler(body)})
        except InterlockError as denied:
            line.deny(name)
            return Response(409, denied.as_dict())
        except ThresholdError as exceeded:
            return Response(422, exceeded.as_dict())
        except ControlError as failed:
            return Response(400, failed.as_dict())
    return Response(404, {"code": "not_found", "path": path})
