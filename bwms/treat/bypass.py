"""处理旁路阀。

泵换向时处理系统必须挂旁路，否则药剂会顺着管路倒灌。旁路挂上要等稳定拍数，
没稳定之前按未旁路处理。
"""

from __future__ import annotations


class BypassValve:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._engaged = False
        self._settled_at: int | None = None
        self._engagements = 0

    @property
    def tag(self) -> str:
        return self._spec.tag

    def engage(self, reason: str) -> dict:
        self._engaged = True
        self._settled_at = self._clock.tick + int(self._spec.bypass_settle_ticks)
        self._engagements += 1
        entry = {
            "tag": self.tag,
            "action": "bypass",
            "reason": reason,
            "settled_at": self._settled_at,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def release(self) -> dict:
        self._engaged = False
        self._settled_at = None
        entry = {"tag": self.tag, "action": "bypass_release", "tick": self._clock.tick}
        self._bus.publish(self.tag, entry)
        return entry

    def engaged(self) -> bool:
        return self._engaged

    def settled(self) -> bool:
        if not self._engaged or self._settled_at is None:
            return False
        return self._clock.tick >= self._settled_at

    def settle_remaining(self) -> int:
        if not self._engaged or self._settled_at is None:
            return 0
        return max(0, self._settled_at - self._clock.tick)

    def engagements(self) -> int:
        return self._engagements

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "engaged": self._engaged,
            "settled": self.settled(),
            "settle_remaining": self.settle_remaining(),
            "engagements": self._engagements,
        }
