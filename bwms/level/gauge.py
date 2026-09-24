"""液位计读数换算。

原始计数乘增益再加上零点偏移才是舱容。零点由标定决定，标定过期或缺失时
读数不可用——按旧零点算出来的舱容会把装载判定带偏。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelReading:
    tag: str
    raw_units: float
    offset_m3: float
    volume_m3: float
    tick: int
    calibrated: bool

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "raw_units": self.raw_units,
            "offset_m3": self.offset_m3,
            "volume_m3": self.volume_m3,
            "tick": self.tick,
            "calibrated": self.calibrated,
        }


class LevelGauge:
    def __init__(self, spec, clock, bus, calibrations) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._calibrations = calibrations
        self._readings: list[LevelReading] = []

    @property
    def tag(self) -> str:
        return self._spec.tag

    def read(self, raw_units: float, require_fresh: bool = True) -> LevelReading:
        if require_fresh:
            self._calibrations.require_fresh()
        offset = self._calibrations.offset_m3()
        reading = LevelReading(
            tag=self.tag,
            raw_units=float(raw_units),
            offset_m3=offset,
            volume_m3=round(float(raw_units) * self._spec.gain_m3_per_unit + offset, 6),
            tick=self._clock.tick,
            calibrated=self._calibrations.is_fresh(),
        )
        self._readings.append(reading)
        self._bus.publish(
            self.tag, {"action": "level", **reading.to_dict()}
        )
        return reading

    def last(self) -> LevelReading | None:
        return self._readings[-1] if self._readings else None

    def history(self, limit: int | None = None) -> tuple[LevelReading, ...]:
        items = tuple(self._readings)
        if limit is None:
            return items
        return items[-int(limit) :]

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "sensor_tag": self._spec.sensor_tag,
            "gain_m3_per_unit": self._spec.gain_m3_per_unit,
            "offset_limit_m3": self._spec.offset_limit_m3,
            "offset_m3": self._calibrations.offset_m3(),
            "calibration_age": self._calibrations.age(),
            "readings": len(self._readings),
        }
