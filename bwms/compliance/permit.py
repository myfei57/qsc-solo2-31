"""排放许可。

许可只对达标批次签发，带有效截止时刻。过了截止时刻的许可不能再作为排放依据，
过期许可是"查得到但用不了"，历史里仍然保留。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import PermitError, ThresholdNotMetError, UnknownSubjectError


@dataclass(frozen=True)
class DischargePermit:
    permit_id: str
    batch_id: str
    generation: int
    sheet_id: str
    issued_tick: int
    expires_at: int
    compliant: bool

    def expired_at(self, tick: int) -> bool:
        return int(tick) > self.expires_at

    def remaining(self, tick: int) -> int:
        return max(0, self.expires_at - int(tick))

    def to_dict(self) -> dict:
        return {
            "permit_id": self.permit_id,
            "batch_id": self.batch_id,
            "generation": self.generation,
            "sheet_id": self.sheet_id,
            "issued_tick": self.issued_tick,
            "expires_at": self.expires_at,
            "compliant": self.compliant,
        }


class PermitBook:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._permits: dict[str, DischargePermit] = {}
        self._counter = 0

    def issue(
        self,
        batch_id: str,
        compliant: bool,
        generation: int,
        sheet_id: str,
        valid_ticks: int | None = None,
    ) -> DischargePermit:
        if not compliant:
            raise ThresholdNotMetError(f"批次 {batch_id} 判定不达标，不签发排放许可")
        self._counter += 1
        tick = self._clock.tick
        span = int(self._spec.permit_valid_ticks if valid_ticks is None else valid_ticks)
        permit = DischargePermit(
            permit_id=f"PMT-{self._counter:04d}",
            batch_id=batch_id,
            generation=int(generation),
            sheet_id=sheet_id,
            issued_tick=tick,
            expires_at=tick + span,
            compliant=True,
        )
        self._permits[permit.permit_id] = permit
        self._bus.publish("permit", {"action": "issue", **permit.to_dict()})
        return permit

    def require(self, permit_id: str) -> DischargePermit:
        permit = self._permits.get(permit_id)
        if permit is None:
            raise UnknownSubjectError(f"没有这个许可: {permit_id}")
        return permit

    def verify(self, permit_id: str) -> DischargePermit:
        permit = self.require(permit_id)
        if permit.expired_at(self._clock.tick):
            raise PermitError(
                f"许可 {permit.permit_id} 已在 {permit.expires_at} 过期，"
                f"当前 {self._clock.tick}"
            )
        return permit

    def permits(self, batch_id: str | None = None) -> tuple[DischargePermit, ...]:
        items = sorted(self._permits.values(), key=lambda item: item.permit_id)
        if batch_id is None:
            return tuple(items)
        return tuple(item for item in items if item.batch_id == batch_id)

    def status(self) -> dict:
        return {
            "issued": len(self._permits),
            "valid_seconds": self._spec.permit_valid_ticks,
            "expired": len(
                [item for item in self._permits.values() if item.expired_at(self._clock.tick)]
            ),
        }
