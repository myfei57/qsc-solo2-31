"""水样分析。

一次分析产出两件事：判定结论与判定依据。浊度和生物指标都按上限比较，任一
越限即判不达标，结论和依据一起落记录，事后查得到是按哪条限值判的。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import DuplicateBatchError, ThresholdError, UnknownSubjectError


@dataclass(frozen=True)
class AnalysisResult:
    batch_id: str
    tag: str
    turbidity_ntu: float
    organisms_per_m3: float
    compliant: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    tick: int = 0

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "tag": self.tag,
            "turbidity_ntu": self.turbidity_ntu,
            "organisms_per_m3": self.organisms_per_m3,
            "compliant": self.compliant,
            "reasons": list(self.reasons),
            "tick": self.tick,
        }


class SampleAnalyzer:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._results: dict[str, AnalysisResult] = {}

    @property
    def tag(self) -> str:
        return self._spec.tag

    def limits(self) -> dict:
        return {
            "turbidity_limit_ntu": self._spec.turbidity_limit_ntu,
            "organism_limit_per_m3": self._spec.organism_limit_per_m3,
        }

    def analyze(
        self, batch_id: str, turbidity_ntu: float, organisms_per_m3: float
    ) -> AnalysisResult:
        turbidity = float(turbidity_ntu)
        organisms = float(organisms_per_m3)
        if batch_id in self._results:
            raise DuplicateBatchError(batch_id)
        if turbidity < 0 or organisms < 0:
            raise ThresholdError(self.tag, "reading", min(turbidity, organisms), 0.0)
        reasons: list[str] = []
        if turbidity > self._spec.turbidity_limit_ntu:
            reasons.append(
                f"浊度 {turbidity} 超过上限 {self._spec.turbidity_limit_ntu}"
            )
        if organisms > self._spec.organism_limit_per_m3:
            reasons.append(
                f"生物指标 {organisms} 超过上限 {self._spec.organism_limit_per_m3}"
            )
        result = AnalysisResult(
            batch_id=batch_id,
            tag=self.tag,
            turbidity_ntu=turbidity,
            organisms_per_m3=organisms,
            compliant=not reasons,
            reasons=tuple(reasons),
            tick=self._clock.tick,
        )
        self._results[batch_id] = result
        self._bus.publish(self.tag, {"action": "analyze", **result.to_dict()})
        return result

    def result(self, batch_id: str) -> AnalysisResult:
        found = self._results.get(batch_id)
        if found is None:
            raise UnknownSubjectError(f"{batch_id} 还没有分析结论")
        return found

    def done(self, batch_id: str) -> bool:
        return batch_id in self._results

    def compliant(self, batch_id: str) -> bool:
        return self.result(batch_id).compliant

    def results(self) -> tuple[AnalysisResult, ...]:
        return tuple(sorted(self._results.values(), key=lambda item: item.tick))

    def status(self) -> dict:
        return {
            "tag": self.tag,
            "limits": self.limits(),
            "analyses": len(self._results),
            "rejected": len([item for item in self._results.values() if not item.compliant]),
        }
