"""流向控制。

换向是一次明确的动作，带稳定拍数：换向动作结束后还要等够稳定拍数，处理侧
的旁路才算挂上，方向未稳定之前不允许按新方向取水。
"""

from __future__ import annotations

from ..errors import ConfigurationError
from .machine import DIRECTIONS


class DirectionController:
    def __init__(self, spec, clock, bus, pump) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._pump = pump
        self._settled_at: int | None = None
        self._changes = 0

    def command(self, direction: str) -> dict:
        if direction not in DIRECTIONS:
            raise ConfigurationError(f"未知流向: {direction}")
        if not self._pump.running():
            raise ConfigurationError("泵未运行，不能换向")
        self._settled_at = self._clock.tick + int(self._spec.reverse_settle_ticks)
        self._changes += 1
        entry = {
            "tag": self._spec.tag,
            "action": "direction",
            "direction": direction,
            "settled_at": self._settled_at,
            "tick": self._clock.tick,
        }
        self._bus.publish("direction", entry)
        return entry

    def settled(self) -> bool:
        if self._settled_at is None:
            return False
        return self._clock.tick >= self._settled_at

    def settle_remaining(self) -> int:
        if self._settled_at is None:
            return int(self._spec.reverse_settle_ticks)
        return max(0, self._settled_at - self._clock.tick)

    def changes(self) -> int:
        return self._changes

    def status(self) -> dict:
        return {
            "direction": self._pump.direction(),
            "settled": self.settled(),
            "settled_at": self._settled_at,
            "settle_remaining": self.settle_remaining(),
            "changes": self._changes,
        }
