"""联锁矩阵。

每个动作在矩阵里登记若干前置项，前置项由真正拥有该状态的组件提供求值函数。
动作执行前统一走 ``require``，不满足就带着未满足项名单拒绝——顺序约束因此
是"做不出来"，而不是事后核对日志才发现的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .errors import InterlockError


@dataclass(frozen=True)
class Gate:
    name: str
    source: str
    check: Callable[[], bool]

    def evaluate(self) -> bool:
        return bool(self.check())

    def to_dict(self, satisfied: bool) -> dict:
        return {"name": self.name, "source": self.source, "satisfied": satisfied}


class InterlockMatrix:
    def __init__(self) -> None:
        self._gates: dict[str, list[Gate]] = {}

    def register(self, action: str, gate: Gate) -> Gate:
        if any(existing.name == gate.name for existing in self._gates.get(action, [])):
            return gate
        self._gates.setdefault(action, []).append(gate)
        return gate

    def actions(self) -> tuple[str, ...]:
        return tuple(sorted(self._gates))

    def gates(self, action: str) -> tuple[Gate, ...]:
        return tuple(self._gates.get(action, ()))

    def unmet(self, action: str) -> tuple[str, ...]:
        return tuple(
            gate.name for gate in self._gates.get(action, ()) if not gate.evaluate()
        )

    def satisfied(self, action: str) -> bool:
        return not self.unmet(action)

    def require(self, action: str) -> None:
        unmet = self.unmet(action)
        if unmet:
            raise InterlockError(action, unmet)

    def describe(self, action: str) -> dict:
        return {
            "action": action,
            "gates": [
                gate.to_dict(gate.evaluate()) for gate in self._gates.get(action, ())
            ],
        }

    def snapshot(self) -> dict:
        return {action: self.describe(action)["gates"] for action in self.actions()}
