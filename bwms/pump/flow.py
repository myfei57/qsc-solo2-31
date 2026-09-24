"""流量计与水流建立。

泵启动之后水流不是立刻可用：要等水流稳定够规定拍数才算建立。这之前流量读作
零，任何依赖水流的动作都不满足前置。
"""

from __future__ import annotations


class FlowMeter:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._flow = 0.0
        self._ready_tick: int | None = None
        self._drops = 0

    def establish(self, flow: float | None = None) -> dict:
        self._flow = float(self._spec.rated_flow_m3_per_tick if flow is None else flow)
        self._ready_tick = self._clock.tick + int(self._spec.settle_ticks)
        entry = {
            "tag": self._spec.tag,
            "action": "establish",
            "flow": self._flow,
            "ready_tick": self._ready_tick,
            "tick": self._clock.tick,
        }
        self._bus.publish("flow", entry)
        return entry

    def read(self) -> float:
        return 0.0 if not self.ready() else self._flow

    def established(self) -> bool:
        return self._flow > 0.0 and self._ready_tick is not None

    def ready(self) -> bool:
        if self._ready_tick is None:
            return False
        return self._clock.tick >= self._ready_tick

    def settle_remaining(self) -> int:
        if self._ready_tick is None:
            return int(self._spec.settle_ticks)
        return max(0, self._ready_tick - self._clock.tick)

    def within_rating(self) -> bool:
        return 0.0 < self._flow <= self._spec.rated_flow_m3_per_tick

    def drop(self, reason: str) -> dict:
        self._flow = 0.0
        self._ready_tick = None
        self._drops += 1
        entry = {
            "tag": self._spec.tag,
            "action": "drop",
            "reason": reason,
            "tick": self._clock.tick,
        }
        self._bus.publish("flow", entry)
        return entry

    def status(self) -> dict:
        return {
            "flow_m3_per_tick": self.read(),
            "ready": self.ready(),
            "ready_tick": self._ready_tick,
            "settle_remaining": self.settle_remaining(),
            "drops": self._drops,
        }
