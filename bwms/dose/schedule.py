"""投加量计算。

按水量和浓度目标算药剂体积，并把投加换算成泵要跑的拍数。每一步投加都记下
当时用的参数代际，事后核验才追得清按哪一版参数投的。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ThresholdError


@dataclass(frozen=True)
class DoseStep:
    volume_m3: float
    ppm: float
    agent_l: float
    ticks: int
    generation: int

    def to_dict(self) -> dict:
        return {
            "volume_m3": self.volume_m3,
            "ppm": self.ppm,
            "agent_l": self.agent_l,
            "ticks": self.ticks,
            "generation": self.generation,
        }


class DoseSchedule:
    def __init__(self, spec, clock) -> None:
        self._spec = spec
        self._clock = clock
        self._steps: list[DoseStep] = []

    def ppm_for(self, agent_l: float, volume_m3: float) -> float:
        if volume_m3 <= 0:
            raise ThresholdError(self._spec.tag, "volume_m3", volume_m3, 0.0)
        return round(agent_l / volume_m3 * 1000.0, 6)

    def agent_for(self, ppm: float, volume_m3: float) -> float:
        return round(ppm * volume_m3 / 1000.0, 6)

    def plan(self, volume_m3: float, ppm: float, generation: int, flow: float) -> DoseStep:
        if ppm <= 0:
            raise ThresholdError(self._spec.tag, "ppm", ppm, 0.0)
        if ppm > self._spec.max_ppm:
            raise ThresholdError(self._spec.tag, "ppm", ppm, self._spec.max_ppm)
        if flow <= 0:
            raise ThresholdError(self._spec.tag, "flow_m3_per_tick", flow, 0.0)
        step = DoseStep(
            volume_m3=round(float(volume_m3), 6),
            ppm=float(ppm),
            agent_l=self.agent_for(ppm, volume_m3),
            ticks=max(1, -(-int(volume_m3) // int(flow))),
            generation=int(generation),
        )
        self._steps.append(step)
        return step

    def steps(self, generation: int | None = None) -> tuple[DoseStep, ...]:
        if generation is None:
            return tuple(self._steps)
        return tuple(step for step in self._steps if step.generation == int(generation))

    def scheduled_ppm(self, generation: int | None = None) -> float:
        return round(sum(step.ppm for step in self.steps(generation)), 6)

    def snapshot(self) -> dict:
        return {
            "tag": self._spec.tag,
            "target_ppm": self._spec.target_ppm,
            "min_flow_m3_per_tick": self._spec.min_flow_m3_per_tick,
            "steps": [step.to_dict() for step in self._steps],
        }
