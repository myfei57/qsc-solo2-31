"""取样管路吹扫控制。

吹扫按冲管 → 静置两段计时推进，管路步骤由取样管路自己按序记录；两段都走完
之前水样不算干净，取样动作在这之前不满足前置。
"""

from __future__ import annotations

IDLE = "idle"
FLUSHING = "flushing"
DWELLING = "dwelling"
CLEAN = "clean"


class PurgeController:
    def __init__(self, spec, clock, bus, line) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._line = line
        self._phase = IDLE
        self._phase_until: int | None = None
        self._purges = 0

    @property
    def tag(self) -> str:
        return self._spec.tag

    def start(self) -> dict:
        self._line.reset()
        self._line.advance("drain")
        self._phase = FLUSHING
        self._phase_until = self._clock.tick + int(self._spec.flush_ticks)
        self._purges += 1
        entry = {
            "tag": self.tag,
            "action": "purge_start",
            "phase": self._phase,
            "until": self._phase_until,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def advance(self) -> dict:
        if self._phase == FLUSHING and self._phase_until is not None:
            if self._clock.tick >= self._phase_until:
                self._line.advance("flush")
                self._phase = DWELLING
                self._phase_until = self._clock.tick + int(self._spec.dwell_ticks)
        elif self._phase == DWELLING and self._phase_until is not None:
            if self._clock.tick >= self._phase_until:
                self._line.advance("dwell")
                self._phase = CLEAN
                self._phase_until = None
        entry = {
            "tag": self.tag,
            "action": "purge_advance",
            "phase": self._phase,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def clean(self) -> bool:
        return self._phase == CLEAN and self._line.completed()

    def phase(self) -> str:
        return self._phase

    def remaining(self) -> int:
        if self._phase_until is None:
            return 0
        return max(0, self._phase_until - self._clock.tick)

    def steps_done(self) -> tuple[str, ...]:
        return self._line.done()

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "phase": self._phase,
            "clean": self.clean(),
            "remaining": self.remaining(),
            "purges": self._purges,
            "line": self._line.status(),
        }
