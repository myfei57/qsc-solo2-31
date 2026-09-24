"""水样批次登记。

批次号是水样、分析与排放许可之间的唯一纽带，必须唯一：批次号重复直接拒绝，
同一个时刻只属于一个批次。批次号本身是确定性的计数序列，不依赖随机数。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import DuplicateBatchError, UnknownSubjectError


@dataclass(frozen=True)
class SampleBatch:
    batch_id: str
    tank_tag: str
    tick: int
    sequence: int

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "tank_tag": self.tank_tag,
            "tick": self.tick,
            "sequence": self.sequence,
        }


class BatchBook:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._batches: dict[str, SampleBatch] = {}
        self._counter = 0

    @property
    def prefix(self) -> str:
        return self._spec.batch_prefix

    def open(self, tank_tag: str) -> SampleBatch:
        self._counter += 1
        batch_id = f"{self._spec.batch_prefix}-{self._counter:04d}"
        return self.reserve(batch_id, tank_tag)

    def reserve(self, batch_id: str, tank_tag: str) -> SampleBatch:
        if batch_id in self._batches:
            raise DuplicateBatchError(batch_id)
        batch = SampleBatch(
            batch_id=batch_id,
            tank_tag=tank_tag,
            tick=self._clock.tick,
            sequence=self._counter,
        )
        self._batches[batch_id] = batch
        self._bus.publish("batch", {"action": "open", **batch.to_dict()})
        return batch

    def require(self, batch_id: str) -> SampleBatch:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise UnknownSubjectError(f"没有这个批次: {batch_id}")
        return batch

    def of_tick(self, tick: int) -> SampleBatch | None:
        for batch in sorted(self._batches.values(), key=lambda item: item.tick):
            if batch.tick == int(tick):
                return batch
        return None

    def batches(self) -> tuple[SampleBatch, ...]:
        return tuple(sorted(self._batches.values(), key=lambda item: item.batch_id))

    def status(self) -> dict:
        return {
            "prefix": self._spec.batch_prefix,
            "count": len(self._batches),
            "batches": [item.to_dict() for item in self.batches()],
        }
