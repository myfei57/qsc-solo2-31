"""参数代际。

参数不是就地改的：每发布一次就产生一个新代际号，旧代际的记录仍然留在流里。
任何引用参数的动作都要带上代际号，代际对不上直接拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import StaleGenerationError, UnknownSubjectError
from .records import KIND_PARAMETER


@dataclass(frozen=True)
class ParameterSet:
    key: str
    generation: int
    values: dict[str, Any]
    tick: int

    def value(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "generation": self.generation,
            "values": dict(self.values),
            "tick": self.tick,
        }


class GenerationRegister:
    def __init__(self, stream, epoch_source) -> None:
        self._stream = stream
        self._epoch_source = epoch_source
        self._history: dict[str, list[ParameterSet]] = {}
        self._load_from_stream()

    def _load_from_stream(self) -> None:
        for record in self._stream.visible():
            if record.kind != KIND_PARAMETER:
                continue
            self._remember(
                ParameterSet(
                    key=record.subject,
                    generation=record.generation,
                    values=dict(record.payload),
                    tick=record.tick,
                )
            )

    def _remember(self, entry: ParameterSet) -> ParameterSet:
        bucket = self._history.setdefault(entry.key, [])
        bucket = [item for item in bucket if item.generation != entry.generation]
        bucket.append(entry)
        bucket.sort(key=lambda item: item.generation)
        self._history[entry.key] = bucket
        return entry

    def publish(self, key: str, values: dict[str, Any]) -> ParameterSet:
        previous = self.current(key) if key in self._history else None
        generation = 1 if previous is None else previous.generation + 1
        record = self._stream.write(
            KIND_PARAMETER,
            key,
            dict(values),
            generation=generation,
            epoch=self._epoch_source(),
        )
        return self._remember(
            ParameterSet(
                key=key,
                generation=generation,
                values=dict(values),
                tick=record.tick,
            )
        )

    def current(self, key: str) -> ParameterSet:
        bucket = self._history.get(key)
        if not bucket:
            raise UnknownSubjectError(f"参数集 {key} 未发布")
        return bucket[-1]

    def history(self, key: str) -> tuple[ParameterSet, ...]:
        return tuple(self._history.get(key, ()))

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._history))

    def get(self, key: str, generation: int) -> ParameterSet:
        for item in self._history.get(key, ()):
            if item.generation == int(generation):
                return item
        raise UnknownSubjectError(f"参数集 {key} 没有代际 {generation}")

    def is_current(self, key: str, generation: int) -> bool:
        try:
            return self.current(key).generation == int(generation)
        except UnknownSubjectError:
            return False

    def require_current(self, key: str, generation: int) -> ParameterSet:
        current = self.current(key)
        if current.generation != int(generation):
            raise StaleGenerationError(key, int(generation), current.generation)
        return current

    def snapshot(self) -> dict[str, Any]:
        return {
            key: [item.to_dict() for item in bucket]
            for key, bucket in sorted(self._history.items())
        }
