"""投加执行。

投加的前置是水流真的建立起来并且流量不低于投加下限，不是"泵已启动"。投加
窗口按拍数核验，窗口内一直保持合格才算投加成立。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ThresholdNotMetError, UnknownSubjectError


@dataclass(frozen=True)
class InjectionResult:
    tag: str
    batch_key: str
    volume_m3: float
    ppm: float
    agent_l: float
    ticks: int
    generation: int
    sheet_id: str
    tick: int

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "batch_key": self.batch_key,
            "volume_m3": self.volume_m3,
            "ppm": self.ppm,
            "agent_l": self.agent_l,
            "ticks": self.ticks,
            "generation": self.generation,
            "sheet_id": self.sheet_id,
            "tick": self.tick,
        }


class DoseInjector:
    def __init__(self, spec, clock, bus, flow, schedule) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._flow = flow
        self._schedule = schedule
        self._results: dict[str, InjectionResult] = {}
        self._verify_until: int | None = None

    @property
    def tag(self) -> str:
        return self._spec.tag

    def flow_ok(self) -> bool:
        return self._flow.ready() and self._flow.read() >= self._spec.min_flow_m3_per_tick

    def inject(
        self,
        batch_key: str,
        volume_m3: float,
        ppm: float,
        generation: int,
        sheet_id: str,
    ) -> InjectionResult:
        if not self.flow_ok():
            raise ThresholdNotMetError(f"{self.tag} 水流未建立，不能投加")
        flow = self._flow.read()
        step = self._schedule.plan(volume_m3, ppm, generation, flow)
        result = InjectionResult(
            tag=self.tag,
            batch_key=batch_key,
            volume_m3=step.volume_m3,
            ppm=step.ppm,
            agent_l=step.agent_l,
            ticks=step.ticks,
            generation=step.generation,
            sheet_id=sheet_id,
            tick=self._clock.tick,
        )
        self._results[batch_key] = result
        self._verify_until = self._clock.tick + int(self._spec.verify_ticks)
        self._bus.publish(
            self.tag, {"action": "inject", "batch_key": batch_key, **result.to_dict()}
        )
        return result

    def result(self, batch_key: str) -> InjectionResult:
        found = self._results.get(batch_key)
        if found is None:
            raise UnknownSubjectError(f"没有这批的投加记录: {batch_key}")
        return found

    def verify_ready(self) -> bool:
        if self._verify_until is None:
            return False
        return self._clock.tick >= self._verify_until

    def verify(self, batch_key: str) -> dict:
        """投加窗口走完后的自检：按药剂体积反算的浓度要与计划一致。"""

        result = self.result(batch_key)
        recomputed = self._schedule.ppm_for(result.agent_l, result.volume_m3)
        return {
            "tag": self.tag,
            "batch_key": batch_key,
            "scheduled_ppm": result.ppm,
            "recomputed_ppm": recomputed,
            "window_elapsed": self.verify_ready(),
            "match": abs(recomputed - result.ppm) < 1e-6,
        }

    def verify_window_remaining(self) -> int:
        if self._verify_until is None:
            return int(self._spec.verify_ticks)
        return max(0, self._verify_until - self._clock.tick)

    def results(self) -> tuple[InjectionResult, ...]:
        return tuple(sorted(self._results.values(), key=lambda item: item.tick))

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "flow_ok": self.flow_ok(),
            "injections": len(self._results),
            "scheduled_ppm": self._schedule.scheduled_ppm(),
            "verify_window_remaining": self.verify_window_remaining(),
            "target_ppm": self._spec.target_ppm,
            "max_ppm": self._spec.max_ppm,
        }
