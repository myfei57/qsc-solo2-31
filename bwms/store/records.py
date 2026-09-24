"""记录与查询过滤条件。

记录只有一种形态：序号、类型、主体、时刻、代际、纪元、负载，外加墓碑标记与
被它作废的序号。所有写入都是这种记录的追加，不存在就地改写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KIND_TICK = "tick"
KIND_ACTION = "action"
KIND_MEASUREMENT = "measurement"
KIND_SAMPLE = "sample"
KIND_ANALYSIS = "analysis"
KIND_PERMIT = "permit"
KIND_DISCHARGE = "discharge"
KIND_CALIBRATION = "calibration"
KIND_PARAMETER = "parameter"
KIND_CONFIRMATION = "confirmation"
KIND_BASELINE = "baseline"
KIND_TOMBSTONE = "tombstone"


@dataclass(frozen=True)
class Record:
    seq: int
    kind: str
    subject: str
    tick: int
    generation: int
    payload: dict[str, Any] = field(default_factory=dict)
    epoch: int = 0
    tombstone: bool = False
    supersedes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "subject": self.subject,
            "tick": self.tick,
            "generation": self.generation,
            "epoch": self.epoch,
            "payload": dict(self.payload),
            "tombstone": self.tombstone,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Record":
        return cls(
            seq=int(raw["seq"]),
            kind=str(raw["kind"]),
            subject=str(raw["subject"]),
            tick=int(raw["tick"]),
            generation=int(raw["generation"]),
            payload=dict(raw.get("payload", {})),
            epoch=int(raw.get("epoch", 0)),
            tombstone=bool(raw.get("tombstone", False)),
            supersedes=raw.get("supersedes"),
        )

    def summary(self) -> str:
        mark = "墓碑" if self.tombstone else self.kind
        return f"#{self.seq} {mark} {self.subject}@{self.tick}"


@dataclass(frozen=True)
class RecordFilter:
    kinds: tuple[str, ...] = ()
    subject: str | None = None
    since_tick: int | None = None
    until_tick: int | None = None
    generation: int | None = None
    epoch: int | None = None
    include_tombstones: bool = False
    limit: int | None = None

    def matches(self, record: Record) -> bool:
        if self.kinds and record.kind not in self.kinds:
            return False
        if self.subject is not None and record.subject != self.subject:
            return False
        if self.since_tick is not None and record.tick < self.since_tick:
            return False
        if self.until_tick is not None and record.tick > self.until_tick:
            return False
        if self.generation is not None and record.generation != self.generation:
            return False
        if self.epoch is not None and record.epoch != self.epoch:
            return False
        if record.tombstone and not self.include_tombstones:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kinds": list(self.kinds),
            "subject": self.subject,
            "since_tick": self.since_tick,
            "until_tick": self.until_tick,
            "generation": self.generation,
            "epoch": self.epoch,
            "include_tombstones": self.include_tombstones,
            "limit": self.limit,
        }
