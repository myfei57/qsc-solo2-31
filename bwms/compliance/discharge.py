"""排放执行。

排放要在同一时刻同时满足三件事：许可还在有效期内、处理侧已经中和完成、当前
时刻落在该批次的排放窗口里。三条缺一不放水。
"""

from __future__ import annotations

from ..errors import InterlockError, PermitError, ThresholdError, UnknownSubjectError


class DischargeController:
    def __init__(self, spec, clock, bus, bay, permits, windows) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._bay = bay
        self._permits = permits
        self._windows = windows
        self._releases = 0

    def blockers(self, batch_id: str, permit_id: str, neutralized: bool) -> tuple[str, ...]:
        unmet: list[str] = []
        if not neutralized:
            unmet.append("treatment_not_neutralized")
        try:
            permit = self._permits.require(permit_id)
        except UnknownSubjectError:
            unmet.append("permit_unknown")
        else:
            if permit.expired_at(self._clock.tick):
                unmet.append("permit_expired")
            elif permit.batch_id != batch_id:
                unmet.append("permit_batch_mismatch")
        window = self._windows.assign(self._clock.tick)
        if window is None:
            unmet.append("no_window")
        elif window.batch_id != batch_id:
            unmet.append("window_batch_mismatch")
        return tuple(unmet)

    def release(
        self,
        batch_id: str,
        tank_tag: str,
        volume_m3: float,
        permit_id: str,
        neutralized: bool,
    ) -> dict:
        unmet = self.blockers(batch_id, permit_id, neutralized)
        if unmet:
            raise InterlockError("compliance.discharge", unmet)
        permit = self._permits.require(permit_id)
        if permit.batch_id != batch_id:
            raise PermitError(f"许可 {permit_id} 属于批次 {permit.batch_id}")
        window = self._windows.resolve(batch_id, self._clock.tick)
        record = self._bay.discharge(tank_tag, volume_m3)
        self._releases += 1
        entry = {
            "batch_id": batch_id,
            "tank_tag": tank_tag,
            "volume_m3": float(volume_m3),
            "permit_id": permit_id,
            "window_id": window.window_id,
            "tick": self._clock.tick,
            "state": record["state"],
        }
        self._bus.publish("discharge", {"action": "release", **entry})
        return entry

    def releases(self) -> int:
        return self._releases

    def status(self) -> dict:
        return {
            "releases": self._releases,
            "open_windows": [item.to_dict() for item in self._windows.open_windows()],
        }
