"""取样管路步骤。

取样前必须按排空 → 冲管 → 静置的顺序把管路残留置换掉，步骤只能按序推进，
跳步或倒序都会当场被拒。
"""

from __future__ import annotations

from ..errors import StageOrderError

STEPS = ("drain", "flush", "dwell")


class SamplingLine:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._done: list[str] = []
        self._completions = 0

    @property
    def tag(self) -> str:
        return self._spec.tag

    def steps(self) -> tuple[str, ...]:
        return STEPS

    def next_step(self) -> str | None:
        for step in STEPS:
            if step not in self._done:
                return step
        return None

    def reset(self) -> None:
        self._done = []

    def advance(self, step: str) -> dict:
        expected = self.next_step()
        if step != expected:
            raise StageOrderError(self.tag, expected or "done", step)
        self._done.append(step)
        if not self.next_step():
            self._completions += 1
        entry = {
            "tag": self.tag,
            "action": "purge_step",
            "step": step,
            "tick": self._clock.tick,
        }
        self._bus.publish(self.tag, entry)
        return entry

    def completed(self) -> bool:
        return self.next_step() is None

    def done(self) -> tuple[str, ...]:
        return tuple(self._done)

    def completions(self) -> int:
        return self._completions

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "steps": list(STEPS),
            "done": list(self._done),
            "next": self.next_step(),
            "completed": self.completed(),
            "completions": self._completions,
        }
