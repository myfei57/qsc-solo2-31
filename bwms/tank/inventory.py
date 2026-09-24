"""舱内状态机与液位账。

一个舱只有四种状态：空、装载中、满、排放中。装载只能在空舱或装载中的舱上
继续，装满之后必须先排放才能再装；跨过状态直接装载会被拒绝，而不是先装再报。
同时保留逐时刻读数，用来回答"当时舱里是多少"这种历史问题。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import StageOrderError, ThresholdError, UnknownSubjectError

EMPTY = "empty"
FILLING = "filling"
FULL = "full"
DISCHARGING = "discharging"

TRANSITIONS: dict[str, tuple[str, ...]] = {
    EMPTY: (FILLING,),
    FILLING: (FILLING, FULL, DISCHARGING),
    FULL: (DISCHARGING,),
    DISCHARGING: (DISCHARGING, EMPTY, FILLING),
}


@dataclass
class TankState:
    tag: str
    capacity_m3: float
    state: str = EMPTY
    volume_m3: float = 0.0
    loads: int = 0
    discharges: int = 0

    def remaining_m3(self) -> float:
        return round(max(0.0, self.capacity_m3 - self.volume_m3), 6)

    def ratio(self) -> float:
        if self.capacity_m3 <= 0:
            return 0.0
        return round(self.volume_m3 / self.capacity_m3, 6)

    def full(self) -> bool:
        return self.remaining_m3() <= 1e-9

    def empty(self) -> bool:
        return self.volume_m3 <= 1e-9

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "state": self.state,
            "volume_m3": round(self.volume_m3, 6),
            "capacity_m3": self.capacity_m3,
            "remaining_m3": self.remaining_m3(),
            "ratio": self.ratio(),
            "loads": self.loads,
            "discharges": self.discharges,
        }


class TankInventory:
    def __init__(self, capacities, clock, bus, order: tuple[str, ...]) -> None:
        self._capacities = capacities
        self._clock = clock
        self._bus = bus
        self._order = order
        self._tanks: dict[str, TankState] = {}
        for tag in order:
            self._tanks[tag] = TankState(tag=tag, capacity_m3=capacities.capacity(tag))
        self._log: dict[str, list[dict]] = {tag: [] for tag in order}

    def require(self, tag: str) -> TankState:
        tank = self._tanks.get(tag)
        if tank is None:
            raise UnknownSubjectError(f"没有这个舱: {tag}")
        return tank

    def tags(self) -> tuple[str, ...]:
        return tuple(self._order)

    def state(self, tag: str) -> str:
        return self.require(tag).state

    def volume(self, tag: str) -> float:
        return round(self.require(tag).volume_m3, 6)

    def remaining(self, tag: str) -> float:
        return self.require(tag).remaining_m3()

    def ratio(self, tag: str) -> float:
        return self.require(tag).ratio()

    def _require_transition(self, tag: str, target: str) -> TankState:
        tank = self.require(tag)
        if target in TRANSITIONS[tank.state]:
            return tank
        raise StageOrderError(tag, "/".join(TRANSITIONS[tank.state]), target)

    def _record(self, tag: str, action: str) -> dict:
        tank = self.require(tag)
        entry = {
            "tag": tag,
            "action": action,
            "tick": self._clock.tick,
            "volume_m3": round(tank.volume_m3, 6),
            "state": tank.state,
        }
        self._log[tag].append(entry)
        self._bus.publish(tag, {"action": action, **entry})
        return entry

    def load(self, tag: str, volume_m3: float) -> dict:
        volume = float(volume_m3)
        tank = self._require_transition(tag, FILLING)
        if volume <= 0:
            raise ThresholdError(tag, "load_volume_m3", volume, 0.0)
        if volume > tank.remaining_m3() + 1e-9:
            raise ThresholdError(tag, "load_volume_m3", volume, tank.remaining_m3())
        tank.state = FILLING
        tank.volume_m3 = round(tank.volume_m3 + volume, 6)
        tank.loads += 1
        if tank.full():
            tank.state = FULL
        return self._record(tag, "load")

    def discharge(self, tag: str, volume_m3: float) -> dict:
        volume = float(volume_m3)
        tank = self._require_transition(tag, DISCHARGING)
        if volume <= 0:
            raise ThresholdError(tag, "discharge_volume_m3", volume, 0.0)
        if volume > tank.volume_m3 + 1e-9:
            raise ThresholdError(tag, "discharge_volume_m3", volume, tank.volume_m3)
        tank.state = DISCHARGING
        tank.volume_m3 = round(max(0.0, tank.volume_m3 - volume), 6)
        tank.discharges += 1
        if tank.empty():
            tank.state = EMPTY
        return self._record(tag, "discharge")

    def apply_capacity_change(self, tag: str) -> dict:
        tank = self.require(tag)
        tank.capacity_m3 = self._capacities.capacity(tag)
        return self._record(tag, "capacity_change")

    def as_of(self, tag: str, tick: int) -> dict:
        entries = [item for item in self._log[tag] if item["tick"] <= int(tick)]
        if not entries:
            return {
                "tag": tag,
                "tick": int(tick),
                "state": EMPTY,
                "volume_m3": 0.0,
                "reconstructed": False,
            }
        last = entries[-1]
        return {
            "tag": tag,
            "tick": int(tick),
            "state": last["state"],
            "volume_m3": last["volume_m3"],
            "reconstructed": True,
        }

    def history(self, tag: str, limit: int | None = None) -> tuple[dict, ...]:
        entries = tuple(self._log[tag])
        if limit is None:
            return entries
        return entries[-int(limit) :]

    def snapshot(self) -> dict:
        return {tag: self.require(tag).to_dict() for tag in self._order}

    def totals(self) -> dict:
        return {
            "volume_m3": round(sum(tank.volume_m3 for tank in self._tanks.values()), 6),
            "capacity_m3": round(
                sum(tank.capacity_m3 for tank in self._tanks.values()), 6
            ),
            "full": [tag for tag in self._order if self.require(tag).full()],
        }
