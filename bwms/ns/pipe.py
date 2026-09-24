"""管路与阀门。

阀门有两个独立状态：通断与落位确认。装载前必须拿到落位确认，光有"开"的
指令不算数，这样阀芯没到位就不会开始灌舱。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnknownDeviceError

CLOSED = "closed"
OPEN = "open"


@dataclass
class PipeSegment:
    tag: str
    medium: str
    state: str = CLOSED
    seated: bool = False
    seated_tick: int | None = None

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "medium": self.medium,
            "state": self.state,
            "seated": self.seated,
            "seated_tick": self.seated_tick,
        }


class PipeHeader:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._segments: dict[str, PipeSegment] = {}

    def add(self, tag: str, medium: str) -> PipeSegment:
        self._registry.register(tag, "valve", "header")
        segment = PipeSegment(tag=tag, medium=medium)
        self._segments[tag] = segment
        return segment

    def require(self, tag: str) -> PipeSegment:
        segment = self._segments.get(tag)
        if segment is None:
            raise UnknownDeviceError(f"未登记的阀: {tag}")
        return segment

    def open(self, tag: str) -> PipeSegment:
        segment = self.require(tag)
        segment.state = OPEN
        return segment

    def close(self, tag: str) -> PipeSegment:
        segment = self.require(tag)
        segment.state = CLOSED
        segment.seated = False
        segment.seated_tick = None
        return segment

    def confirm_seated(self, tag: str, tick: int) -> PipeSegment:
        segment = self.require(tag)
        segment.state = OPEN
        segment.seated = True
        segment.seated_tick = tick
        return segment

    def is_open(self, tag: str) -> bool:
        return self.require(tag).state == OPEN

    def is_seated(self, tag: str) -> bool:
        return self.require(tag).seated

    def open_tags(self) -> tuple[str, ...]:
        return tuple(
            sorted(tag for tag, segment in self._segments.items() if segment.state == OPEN)
        )

    def snapshot(self) -> list[dict]:
        return [segment.to_dict() for _, segment in sorted(self._segments.items())]
