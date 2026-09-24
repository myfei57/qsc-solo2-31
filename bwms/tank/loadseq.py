"""装载顺序规划。

规划一次装载时按舱容从大到小的顺序取当前剩余舱容，取满一个舱再进下一个；
每次规划都重新读当前剩余，不用上一次规划留下的账。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ThresholdError


@dataclass(frozen=True)
class Allocation:
    tag: str
    volume_m3: float
    remaining_before_m3: float
    capacity_revision: int

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "volume_m3": self.volume_m3,
            "remaining_before_m3": self.remaining_before_m3,
            "capacity_revision": self.capacity_revision,
        }


class LoadPlanner:
    def __init__(self, bay, capacities, clock, bus) -> None:
        self._bay = bay
        self._capacities = capacities
        self._clock = clock
        self._bus = bus
        self._last_snapshot: dict[str, float] = {}
        self._last_snapshot_tick: int | None = None

    def order(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                self._bay.tags(),
                key=lambda tag: (-self._capacities.capacity(tag), tag),
            )
        )

    def snapshot(self) -> dict[str, float]:
        """当前各舱剩余舱容。"""

        return {tag: self._bay.remaining(tag) for tag in self._bay.tags()}

    def refresh(self) -> dict[str, float]:
        self._last_snapshot = self.snapshot()
        self._last_snapshot_tick = self._clock.tick
        self._bus.publish("loadplan", {"action": "refresh", "tick": self._clock.tick})
        return dict(self._last_snapshot)

    def last_snapshot(self) -> dict:
        return {
            "remaining": dict(self._last_snapshot),
            "tick": self._last_snapshot_tick,
        }

    def plan(self, volume_m3: float) -> dict:
        volume = float(volume_m3)
        if volume <= 0:
            raise ThresholdError("loadplan", "volume_m3", volume, 0.0)
        remaining = self.refresh()
        left = volume
        allocations: list[Allocation] = []
        for tag in self.order():
            if left <= 1e-9:
                break
            room = remaining[tag]
            if room <= 1e-9:
                continue
            take = min(room, left)
            allocations.append(
                Allocation(
                    tag=tag,
                    volume_m3=round(take, 6),
                    remaining_before_m3=round(room, 6),
                    capacity_revision=self._capacities.revision(tag),
                )
            )
            left = round(left - take, 6)
        report = {
            "tick": self._clock.tick,
            "requested_m3": round(volume, 6),
            "allocated_m3": round(volume - left, 6),
            "unallocated_m3": round(max(0.0, left), 6),
            "allocations": [item.to_dict() for item in allocations],
            "complete": left <= 1e-9,
        }
        self._bus.publish("loadplan", {"action": "plan", "tick": report["tick"]})
        return report
