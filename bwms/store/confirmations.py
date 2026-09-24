"""确认单。

确认单把"谁在什么时刻为哪个代际的参数签了字"固定下来，并带有效截止时刻。
签发时是当前代际，不等于永远有效：过期或代际被顶替都会在核验时被拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ExpiredConfirmationError, StaleGenerationError, UnknownSubjectError
from .records import KIND_CONFIRMATION


@dataclass(frozen=True)
class ConfirmationSheet:
    sheet_id: str
    key: str
    generation: int
    operator: str
    issued_tick: int
    valid_until_tick: int
    note: str = ""

    def expired_at(self, tick: int) -> bool:
        return int(tick) > self.valid_until_tick

    def remaining(self, tick: int) -> int:
        return max(0, self.valid_until_tick - int(tick))

    def to_dict(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "key": self.key,
            "generation": self.generation,
            "operator": self.operator,
            "issued_tick": self.issued_tick,
            "valid_until_tick": self.valid_until_tick,
            "note": self.note,
        }


class ConfirmationBook:
    def __init__(self, stream, generations, clock) -> None:
        self._stream = stream
        self._generations = generations
        self._clock = clock
        self._sheets: dict[str, ConfirmationSheet] = {}
        self._counter = 0

    def confirm(
        self,
        key: str,
        operator: str,
        validity_ticks: int,
        note: str = "",
    ) -> ConfirmationSheet:
        current = self._generations.current(key)
        self._counter += 1
        tick = self._clock.tick
        sheet = ConfirmationSheet(
            sheet_id=f"CF-{key}-{current.generation:03d}-{self._counter:03d}",
            key=key,
            generation=current.generation,
            operator=operator,
            issued_tick=tick,
            valid_until_tick=tick + int(validity_ticks),
            note=note,
        )
        self._stream.write(
            KIND_CONFIRMATION,
            sheet.sheet_id,
            sheet.to_dict(),
            generation=current.generation,
        )
        self._sheets[sheet.sheet_id] = sheet
        return sheet

    def require(self, sheet_id: str) -> ConfirmationSheet:
        sheet = self._sheets.get(sheet_id)
        if sheet is None:
            raise UnknownSubjectError(f"确认单 {sheet_id} 未登记")
        return sheet

    def verify(self, sheet_id: str, key: str, generation: int) -> ConfirmationSheet:
        sheet = self.require(sheet_id)
        if not self._generations.is_current(key, sheet.generation):
            current = self._generations.current(key)
            raise StaleGenerationError(key, sheet.generation, current.generation)
        if sheet.key != key or sheet.generation != int(generation):
            raise StaleGenerationError(key, int(generation), sheet.generation)
        if sheet.expired_at(self._clock.tick):
            raise ExpiredConfirmationError(
                sheet.sheet_id, sheet.valid_until_tick, self._clock.tick
            )
        return sheet

    def sheets(self, key: str | None = None) -> tuple[ConfirmationSheet, ...]:
        items = sorted(self._sheets.values(), key=lambda item: item.sheet_id)
        if key is None:
            return tuple(items)
        return tuple(item for item in items if item.key == key)

    def latest(self, key: str) -> ConfirmationSheet | None:
        bucket = self.sheets(key)
        return bucket[-1] if bucket else None

    def snapshot(self) -> list[dict]:
        return [item.to_dict() for item in self.sheets()]
