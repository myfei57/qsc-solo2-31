"""审计留痕。

审计只订阅事件总线，不主动问任何组件要数据。每条事件按动作性质定级，告警、
拒绝与写入各自成类，方便按组件和级别回看。
"""

from __future__ import annotations

from dataclasses import dataclass

ALARM_ACTIONS = {"trip", "bypass", "recalibrate", "truncate"}
WARNING_ACTIONS = {"deny", "warn", "window"}


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    tick: int
    topic: str
    action: str
    severity: str
    detail: dict

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "topic": self.topic,
            "action": self.action,
            "severity": self.severity,
            "detail": dict(self.detail),
        }


class AuditTrail:
    def __init__(self, bus, clock) -> None:
        self._bus = bus
        self._clock = clock
        self._entries: list[AuditEntry] = []

    def attach(self) -> AuditTrail:
        self._bus.subscribe("*", self.capture)
        return self

    def classify(self, action: str) -> str:
        if action in ALARM_ACTIONS:
            return "alarm"
        if action in WARNING_ACTIONS:
            return "warning"
        return "info"

    def capture(self, topic: str, event: dict) -> AuditEntry:
        action = str(event.get("action", "event"))
        entry = AuditEntry(
            seq=len(self._entries) + 1,
            tick=int(event.get("tick", self._clock.tick)),
            topic=topic,
            action=action,
            severity=self.classify(action),
            detail=dict(event),
        )
        self._entries.append(entry)
        return entry

    def entries(self, limit: int | None = None) -> tuple[AuditEntry, ...]:
        items = tuple(self._entries)
        if limit is None:
            return items
        return items[-int(limit) :]

    def tail(self, count: int = 5) -> tuple[AuditEntry, ...]:
        return self.entries(limit=count)

    def by_component(self, topic: str) -> tuple[AuditEntry, ...]:
        return tuple(item for item in self._entries if item.topic == topic)

    def alarms(self) -> tuple[AuditEntry, ...]:
        return tuple(item for item in self._entries if item.severity == "alarm")

    def warnings(self) -> tuple[AuditEntry, ...]:
        return tuple(item for item in self._entries if item.severity == "warning")

    def count(self) -> int:
        return len(self._entries)

    def status(self) -> dict:
        return {
            "entries": len(self._entries),
            "alarms": len(self.alarms()),
            "warnings": len(self.warnings()),
            "topics": sorted({item.topic for item in self._entries}),
            "wildcard_subscribers": self._bus.subscribers("*"),
        }
