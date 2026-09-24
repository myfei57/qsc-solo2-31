"""中和剂投加。

处理系统按 standby → treating → neutralized 走：只有处理过的水量才能中和，
中和之后还要等够保持拍数才算完成，排放侧只认这个完成态。
"""

from __future__ import annotations

from ..errors import StageOrderError, ThresholdError

STANDBY = "standby"
TREATING = "treating"
NEUTRALIZED = "neutralized"


class Neutralizer:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._state = STANDBY
        self._treated_m3 = 0.0
        self._neutralized_m3 = 0.0
        self._hold_until: int | None = None

    @property
    def tag(self) -> str:
        return self._spec.tag

    def state(self) -> str:
        return self._state

    def treated_m3(self) -> float:
        return round(self._treated_m3, 6)

    def neutralized_m3(self) -> float:
        return round(self._neutralized_m3, 6)

    def start_treatment(self, volume_m3: float) -> dict:
        volume = float(volume_m3)
        if volume <= 0:
            raise ThresholdError(self.tag, "volume_m3", volume, 0.0)
        if self._state == NEUTRALIZED:
            self._state = STANDBY
        self._state = TREATING
        self._treated_m3 = round(self._treated_m3 + volume, 6)
        entry = {
            "tag": self.tag,
            "action": "treat",
            "volume_m3": volume,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def neutralize(self, volume_m3: float, ppm: float) -> dict:
        if self._state != TREATING:
            raise StageOrderError(self.tag, TREATING, self._state)
        volume = float(volume_m3)
        if volume <= 0:
            raise ThresholdError(self.tag, "volume_m3", volume, 0.0)
        if ppm > self._spec.neutralizer_ppm:
            raise ThresholdError(self.tag, "ppm", ppm, self._spec.neutralizer_ppm)
        self._state = NEUTRALIZED
        self._neutralized_m3 = round(self._neutralized_m3 + volume, 6)
        self._hold_until = self._clock.tick + int(self._spec.neutralizer_hold_ticks)
        entry = {
            "tag": self.tag,
            "action": "neutralize",
            "volume_m3": volume,
            "ppm": float(ppm),
            "hold_until": self._hold_until,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def hold_remaining(self) -> int:
        if self._hold_until is None:
            return int(self._spec.neutralizer_hold_ticks)
        return max(0, self._hold_until - self._clock.tick)

    def ready(self) -> bool:
        return self._state == NEUTRALIZED and self.hold_remaining() == 0

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "state": self._state,
            "treated_m3": self.treated_m3(),
            "neutralized_m3": self.neutralized_m3(),
            "hold_remaining": self.hold_remaining(),
            "ready": self.ready(),
            "neutralizer_ppm": self._spec.neutralizer_ppm,
        }
