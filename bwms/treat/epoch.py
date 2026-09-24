"""处理日志纪元。

日志按纪元分段：每条处理记录在写入时就被打上当时的纪元号，换段只影响之后写
入的记录。上一段收尾的记录继续留在上一段里，不跟着新纪元走。
"""

from __future__ import annotations

from ..store.records import KIND_ACTION


class TreatmentLogEpoch:
    def __init__(self, clock, bus, stream) -> None:
        self._clock = clock
        self._bus = bus
        self._stream = stream
        self._epoch = 0
        self._rolls: list[dict] = []

    def current(self) -> int:
        return self._epoch

    def roll(self, reason: str = "") -> dict:
        closed = self._epoch
        self._epoch = closed + 1
        entry = {
            "closed_epoch": closed,
            "opened_epoch": self._epoch,
            "closed_records": self._stream.epoch_count(closed),
            "reason": reason,
            "tick": self._clock.tick,
        }
        self._rolls.append(entry)
        self._bus.publish("epoch", {"action": "roll", **entry})
        self._stream.write(
            KIND_ACTION, "treatment-epoch", entry, epoch=self._epoch
        )
        return entry

    def rolls(self) -> tuple[dict, ...]:
        return tuple(self._rolls)

    def totals(self) -> dict[str, int]:
        """按纪元汇总的处理记录条数，上一段的尾巴不会被算进新段。"""

        totals: dict[str, int] = {}
        for epoch in range(self._epoch + 1):
            totals[str(epoch)] = self._stream.epoch_count(epoch)
        return totals

    def status(self) -> dict:
        return {
            "epoch": self._epoch,
            "rolls": len(self._rolls),
            "totals": self.totals(),
        }
