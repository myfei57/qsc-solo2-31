"""强度采集。

采集侧只负责把读数交给处理侧，并在本地留一份带时刻的读数序列；判定标准归
处理侧，采集侧不自己下结论。
"""

from __future__ import annotations


class IntensitySensor:
    def __init__(self, spec, clock, bus, reactor) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._reactor = reactor
        self._values: list[dict] = []

    @property
    def tag(self) -> str:
        return self._spec.tag

    def sample(self, value: float) -> dict:
        reading = self._reactor.record(value)
        entry = reading.to_dict()
        self._values.append(entry)
        self._bus.publish("intensity", {"action": "sample", "source": self.tag, **entry})
        return entry

    def last(self) -> dict | None:
        return self._values[-1] if self._values else None

    def readings(self, limit: int | None = None) -> tuple[dict, ...]:
        items = tuple(self._values)
        if limit is None:
            return items
        return items[-int(limit) :]

    def below_limit(self) -> int:
        return len([item for item in self._values if not item["acceptable"]])

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "samples": len(self._values),
            "below_limit": self.below_limit(),
            "reactor": self._reactor.status(),
        }
