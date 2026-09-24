"""闩锁。

闩锁一旦置位就保持住，直到解除条件成立才放行；解除必须由显式动作完成，
不会因为瞬时状态恢复就自动消失。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnknownSubjectError


@dataclass
class Latch:
    name: str
    source: str
    tripped: bool = False
    reason: str = ""
    set_tick: int | None = None
    clear_tick: int | None = None
    trips: int = 0

    def trip(self, reason: str, tick: int) -> "Latch":
        self.tripped = True
        self.reason = reason
        self.set_tick = tick
        self.trips += 1
        return self

    def release(self, tick: int) -> "Latch":
        self.tripped = False
        self.clear_tick = tick
        return self

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "tripped": self.tripped,
            "reason": self.reason,
            "set_tick": self.set_tick,
            "clear_tick": self.clear_tick,
            "trips": self.trips,
        }


class LatchBank:
    def __init__(self) -> None:
        self._latches: dict[str, Latch] = {}

    def declare(self, name: str, source: str) -> Latch:
        latch = Latch(name=name, source=source)
        self._latches[name] = latch
        return latch

    def require(self, name: str) -> Latch:
        latch = self._latches.get(name)
        if latch is None:
            raise UnknownSubjectError(f"未声明的闩锁: {name}")
        return latch

    def trip(self, name: str, reason: str, tick: int) -> Latch:
        return self.require(name).trip(reason, tick)

    def clear(self, name: str, tick: int) -> Latch:
        return self.require(name).release(tick)

    def is_set(self, name: str) -> bool:
        return self.require(name).tripped

    def active(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, latch in self._latches.items() if latch.tripped))

    def blocked(self, names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in names if self.is_set(name))

    def detail(self, name: str) -> dict:
        return self.require(name).to_dict()

    def snapshot(self) -> list[dict]:
        return [latch.to_dict() for _, latch in sorted(self._latches.items())]
