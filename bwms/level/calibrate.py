"""零点标定。

标定带时刻，超过允许龄期就作废。重新标定是一条新记录，历史标定仍然查得到，
但读数只认最近一次。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import CalibrationError


@dataclass(frozen=True)
class CalibrationRecord:
    tag: str
    offset_m3: float
    tick: int
    note: str

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "offset_m3": self.offset_m3,
            "tick": self.tick,
            "note": self.note,
        }


class CalibrationBook:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._history: list[CalibrationRecord] = [
            CalibrationRecord(
                tag=spec.tag, offset_m3=0.0, tick=clock.tick, note="出厂零点"
            )
        ]

    @property
    def tag(self) -> str:
        return self._spec.tag

    def recalibrate(self, offset_m3: float, note: str = "") -> CalibrationRecord:
        record = CalibrationRecord(
            tag=self.tag,
            offset_m3=float(offset_m3),
            tick=self._clock.tick,
            note=note,
        )
        self._history.append(record)
        self._bus.publish(
            self.tag, {"action": "recalibrate", **record.to_dict()}
        )
        return record

    def latest(self) -> CalibrationRecord:
        return self._history[-1]

    def offset_m3(self) -> float:
        return self.latest().offset_m3

    def age(self) -> int:
        return self._clock.tick - self.latest().tick

    def is_fresh(self) -> bool:
        return self.age() <= int(self._spec.calibration_max_age_ticks)

    def require_fresh(self) -> CalibrationRecord:
        record = self.latest()
        if not self.is_fresh():
            raise CalibrationError(
                f"{self.tag} 零点标定已过期 {self.age()} 拍，上限 "
                f"{self._spec.calibration_max_age_ticks} 拍"
            )
        return record

    def within_limit(self) -> bool:
        return abs(self.offset_m3()) <= self._spec.offset_limit_m3

    def history(self) -> tuple[CalibrationRecord, ...]:
        return tuple(self._history)

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "offset_m3": self.offset_m3(),
            "age": self.age(),
            "max_age": self._spec.calibration_max_age_ticks,
            "fresh": self.is_fresh(),
            "within_limit": self.within_limit(),
            "calibrations": len(self._history),
        }
