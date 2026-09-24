"""UV 处理与强度判定窗口。

强度按检测周期分组：周期以固定的窗口长度切分，判定只看当前周期内的读数。
周期内掉过一次强度就算这一批处理不足，恢复要连续达标够清除拍数才解除闩锁。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntensityReading:
    tick: int
    value: float
    cycle: int
    acceptable: bool

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "value": self.value,
            "cycle": self.cycle,
            "acceptable": self.acceptable,
        }


class UvReactor:
    def __init__(self, spec, clock, bus, latches) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._latches = latches
        self._readings: list[IntensityReading] = []
        self._clear_streak = 0
        self._verdicts: list[dict] = []

    @property
    def tag(self) -> str:
        return self._spec.tag

    def cycle_of(self, tick: int | None = None) -> int:
        moment = self._clock.tick if tick is None else int(tick)
        span = max(1, int(self._spec.uv_window_ticks))
        return moment // span

    def window_bounds(self, tick: int | None = None) -> tuple[int, int]:
        """当前检测周期的半开区间 [start, end)。"""

        cycle = self.cycle_of(tick)
        span = max(1, int(self._spec.uv_window_ticks))
        return cycle * span, cycle * span + span

    def record(self, value: float) -> IntensityReading:
        moment = self._clock.tick
        reading = IntensityReading(
            tick=moment,
            value=float(value),
            cycle=self.cycle_of(moment),
            acceptable=float(value) >= self._spec.uv_min_intensity,
        )
        self._readings.append(reading)
        self._bus.publish(
            self.tag, {"action": "intensity", "tick": moment, "value": reading.value}
        )
        if reading.acceptable:
            self._clear_streak += 1
            if self._clear_streak >= int(self._spec.uv_clear_ticks):
                self._latches.clear("uv_low", moment)
        else:
            self._clear_streak = 0
            self._latches.trip("uv_low", f"强度 {reading.value} 低于下限", moment)
        return reading

    def readings_in_window(self, tick: int | None = None) -> tuple[IntensityReading, ...]:
        start, end = self.window_bounds(tick)
        return tuple(
            reading for reading in self._readings if start <= reading.tick < end
        )

    def window_verdict(self) -> dict:
        start, end = self.window_bounds()
        readings = self.readings_in_window()
        values = [reading.value for reading in readings]
        minimum = min(values) if values else 0.0
        verdict = {
            "tag": self.tag,
            "cycle": self.cycle_of(),
            "window_start": start,
            "window_end": end,
            "samples": len(readings),
            "min_value": minimum,
            "limit": self._spec.uv_min_intensity,
            "pass": self.intensity_ok(),
        }
        self._verdicts.append(verdict)
        self._bus.publish(self.tag, {"action": "window", **verdict})
        return verdict

    def intensity_ok(self) -> bool:
        """当前检测周期内的最低强度是否达标（纯查询，不产生判定记录）。"""

        readings = self.readings_in_window()
        if not readings:
            return False
        return min(reading.value for reading in readings) >= self._spec.uv_min_intensity

    def latched(self) -> bool:
        return self._latches.is_set("uv_low")

    def clear_streak(self) -> int:
        return self._clear_streak

    def history(self, limit: int | None = None) -> tuple[IntensityReading, ...]:
        items = tuple(self._readings)
        if limit is None:
            return items
        return items[-int(limit) :]

    def verdicts(self, limit: int | None = None) -> tuple[dict, ...]:
        items = tuple(self._verdicts)
        if limit is None:
            return items
        return items[-int(limit) :]

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "min_intensity": self._spec.uv_min_intensity,
            "window_ticks": self._spec.uv_window_ticks,
            "clear_ticks": self._spec.uv_clear_ticks,
            "window": self.window_bounds(),
            "samples": len(self._readings),
            "latched": self.latched(),
            "clear_streak": self._clear_streak,
        }
