"""压载泵本体。"""

from __future__ import annotations

from ..errors import ConfigurationError

INTAKE = "intake"
DISCHARGE = "discharge"
STOPPED = "stopped"
DIRECTIONS = (INTAKE, DISCHARGE)


class BallastPump:
    def __init__(self, spec, clock, bus, header) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._header = header
        self._running = False
        self._direction = STOPPED
        self._starts = 0

    @property
    def tag(self) -> str:
        return self._spec.tag

    def outlet_open(self) -> bool:
        return self._header.is_open(self._spec.outlet_valve)

    def can_start(self, direction: str) -> bool:
        return direction in DIRECTIONS and self.outlet_open()

    def running(self) -> bool:
        return self._running

    def direction(self) -> str:
        return self._direction

    def start(self, direction: str = INTAKE) -> dict:
        if not self.can_start(direction):
            raise ConfigurationError(f"{self.tag} 出口阀未开，不能启动")
        self._running = True
        self._direction = direction
        self._starts += 1
        entry = {
            "tag": self.tag,
            "action": "start",
            "direction": direction,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def stop(self) -> dict:
        self._running = False
        self._direction = STOPPED
        entry = {"tag": self.tag, "action": "stop", "tick": self._clock.tick}
        self._bus.publish(self.tag, entry)
        return entry

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "running": self._running,
            "direction": self._direction,
            "outlet_valve": self._spec.outlet_valve,
            "outlet_open": self.outlet_open(),
            "rated_flow_m3_per_tick": self._spec.rated_flow_m3_per_tick,
            "starts": self._starts,
        }
