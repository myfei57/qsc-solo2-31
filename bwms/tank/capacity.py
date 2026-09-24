"""舱容与舱容修订。

舱容是可变的：检修、清舱、加装隔板都会改变有效舱容。每次变更产生一个新修订
号，规划装载时报告用的是哪一版舱容，事后才追得清是按哪一版算的。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnknownSubjectError


@dataclass
class CapacityRevision:
    tag: str
    capacity_m3: float
    revision: int
    tick: int
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "capacity_m3": self.capacity_m3,
            "revision": self.revision,
            "tick": self.tick,
            "note": self.note,
        }


class CapacityBook:
    def __init__(self, settings, clock) -> None:
        self._clock = clock
        self._revisions: dict[str, list[CapacityRevision]] = {}
        for spec in settings.tanks:
            self._revisions[spec.tag] = [
                CapacityRevision(
                    tag=spec.tag,
                    capacity_m3=float(spec.capacity_m3),
                    revision=1,
                    tick=clock.tick,
                    note="初始舱容",
                )
            ]

    def require(self, tag: str) -> CapacityRevision:
        bucket = self._revisions.get(tag)
        if not bucket:
            raise UnknownSubjectError(f"没有舱容记录: {tag}")
        return bucket[-1]

    def capacity(self, tag: str) -> float:
        return self.require(tag).capacity_m3

    def revision(self, tag: str) -> int:
        return self.require(tag).revision

    def set_capacity(self, tag: str, capacity_m3: float, note: str = "") -> CapacityRevision:
        previous = self.require(tag)
        entry = CapacityRevision(
            tag=tag,
            capacity_m3=float(capacity_m3),
            revision=previous.revision + 1,
            tick=self._clock.tick,
            note=note,
        )
        self._revisions[tag].append(entry)
        return entry

    def history(self, tag: str) -> tuple[CapacityRevision, ...]:
        return tuple(self._revisions.get(tag, ()))

    def snapshot(self) -> dict:
        return {tag: self.require(tag).to_dict() for tag in sorted(self._revisions)}
