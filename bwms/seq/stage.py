"""阶段与顺序定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import UnknownSubjectError


@dataclass(frozen=True)
class StageDefinition:
    name: str
    order: int
    latches: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "order": self.order, "latches": list(self.latches)}


@dataclass(frozen=True)
class SequenceDefinition:
    device: str
    stages: tuple[StageDefinition, ...] = field(default_factory=tuple)

    def ordered(self) -> tuple[StageDefinition, ...]:
        return tuple(sorted(self.stages, key=lambda stage: stage.order))

    def names(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self.ordered())

    def stage(self, name: str) -> StageDefinition:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise UnknownSubjectError(f"{self.device} 没有阶段 {name}")

    def index(self, name: str) -> int:
        for position, stage in enumerate(self.ordered()):
            if stage.name == name:
                return position
        raise UnknownSubjectError(f"{self.device} 没有阶段 {name}")

    def first(self) -> StageDefinition:
        return self.ordered()[0]

    def next_after(self, name: str) -> StageDefinition | None:
        ordered = self.ordered()
        position = self.index(name)
        if position + 1 >= len(ordered):
            return None
        return ordered[position + 1]

    def to_dict(self) -> dict:
        return {"device": self.device, "stages": [s.to_dict() for s in self.ordered()]}
