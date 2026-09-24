"""阶段推进引擎。

推进一个阶段要同时过三关：顺序（只能是当前阶段的下一阶段）、闩锁（阶段声明
的闩锁必须处于解除态）、联锁（矩阵里该动作的前置项全部满足）。三关任一不过
就地拒绝，设备阶段原地不动。
"""

from __future__ import annotations

from ..errors import LatchError, SequenceError, StageOrderError, UnknownDeviceError
from ..interlocks import InterlockMatrix
from .latch import LatchBank
from .stage import SequenceDefinition


class SequenceEngine:
    def __init__(self, interlocks: InterlockMatrix, latches: LatchBank, clock, bus) -> None:
        self._interlocks = interlocks
        self._latches = latches
        self._clock = clock
        self._bus = bus
        self._definitions: dict[str, SequenceDefinition] = {}
        self._current: dict[str, str | None] = {}
        self._passed: dict[str, list[str]] = {}
        self._log: list[dict] = []

    def define(self, definition: SequenceDefinition) -> SequenceDefinition:
        self._definitions[definition.device] = definition
        self._current.setdefault(definition.device, None)
        self._passed.setdefault(definition.device, [])
        return definition

    def require(self, device: str) -> SequenceDefinition:
        definition = self._definitions.get(device)
        if definition is None:
            raise UnknownDeviceError(f"未定义顺序的设备: {device}")
        return definition

    def devices(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def definition(self, device: str) -> dict:
        return self.require(device).to_dict()

    def arm(self, device: str) -> dict:
        definition = self.require(device)
        self._current[device] = None
        self._passed[device] = []
        entry = {
            "device": device,
            "stage": None,
            "next": definition.first().name,
            "tick": self._clock.tick,
        }
        self._log.append(entry)
        self._bus.publish("sequence", {"action": "arm", **entry})
        return entry

    def armed(self, device: str) -> bool:
        return device in self._current

    def current(self, device: str) -> str | None:
        self.require(device)
        return self._current.get(device)

    def next_stage(self, device: str) -> str | None:
        definition = self.require(device)
        current = self._current.get(device)
        if current is None:
            return definition.first().name
        following = definition.next_after(current)
        return None if following is None else following.name

    def reached(self, device: str, stage_name: str) -> bool:
        self.require(device)
        self.require(device).stage(stage_name)
        return stage_name in self._passed.get(device, [])

    def step(self, device: str, stage_name: str) -> dict:
        definition = self.require(device)
        expected = self.next_stage(device)
        if expected is None:
            raise SequenceError(f"{device} 已走完全部阶段")
        if stage_name != expected:
            raise StageOrderError(device, expected, stage_name)
        stage = definition.stage(stage_name)
        blocked = self._latches.blocked(stage.latches)
        if blocked:
            raise LatchError(stage_name, blocked)
        self._interlocks.require(stage_name)
        self._current[device] = stage_name
        self._passed.setdefault(device, []).append(stage_name)
        entry = {
            "device": device,
            "stage": stage_name,
            "next": self.next_stage(device),
            "tick": self._clock.tick,
        }
        self._log.append(entry)
        self._bus.publish("sequence", {"action": "step", **entry})
        return entry

    def status(self, device: str) -> dict:
        definition = self.require(device)
        current = self._current.get(device)
        return {
            "device": device,
            "armed": device in self._current,
            "current": current,
            "next": self.next_stage(device),
            "passed": list(self._passed.get(device, [])),
            "stages": definition.names(),
            "complete": current == definition.ordered()[-1].name,
        }

    def history(self, device: str | None = None) -> tuple[dict, ...]:
        if device is None:
            return tuple(self._log)
        return tuple(entry for entry in self._log if entry["device"] == device)

    def snapshot(self) -> dict:
        return {device: self.status(device) for device in self.devices()}
