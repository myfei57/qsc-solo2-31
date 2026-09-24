"""基线与快照的时效。

每次取值都固化成一条基线：代际号、取值时刻、失效时刻和一个摘要。基线过了
失效时刻，或者它绑定的代际已被新代际顶替，都不能再拿来当依据。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ExpiredBaselineError, StaleGenerationError, UnknownSubjectError
from .records import KIND_BASELINE


@dataclass(frozen=True)
class Baseline:
    baseline_id: str
    key: str
    generation: int
    captured_tick: int
    expires_at_tick: int
    digest: str
    label: str = ""

    def expired_at(self, tick: int) -> bool:
        return int(tick) > self.expires_at_tick

    def age(self, tick: int) -> int:
        return int(tick) - self.captured_tick

    def to_dict(self) -> dict:
        return {
            "baseline_id": self.baseline_id,
            "key": self.key,
            "generation": self.generation,
            "captured_tick": self.captured_tick,
            "expires_at_tick": self.expires_at_tick,
            "digest": self.digest,
            "label": self.label,
        }


class BaselineRegistry:
    def __init__(self, stream, generations, clock) -> None:
        self._stream = stream
        self._generations = generations
        self._clock = clock
        self._baselines: dict[str, Baseline] = {}
        self._counter = 0

    def capture(
        self,
        key: str,
        digest: str,
        valid_ticks: int,
        label: str = "BASE",
    ) -> Baseline:
        current = self._generations.current(key)
        self._counter += 1
        tick = self._clock.tick
        baseline = Baseline(
            baseline_id=f"{label}-{key}-{self._counter:03d}",
            key=key,
            generation=current.generation,
            captured_tick=tick,
            expires_at_tick=tick + int(valid_ticks),
            digest=digest,
            label=label,
        )
        self._stream.write(
            KIND_BASELINE,
            baseline.baseline_id,
            baseline.to_dict(),
            generation=current.generation,
        )
        self._baselines[baseline.baseline_id] = baseline
        return baseline

    def require(self, baseline_id: str) -> Baseline:
        baseline = self._baselines.get(baseline_id)
        if baseline is None:
            raise UnknownSubjectError(f"基线 {baseline_id} 未登记")
        return baseline

    def resolve(self, baseline_id: str) -> Baseline:
        baseline = self.require(baseline_id)
        if baseline.expired_at(self._clock.tick):
            raise ExpiredBaselineError(
                baseline.baseline_id, baseline.expires_at_tick, self._clock.tick
            )
        current = self._generations.current(baseline.key)
        if current.generation != baseline.generation:
            raise StaleGenerationError(
                baseline.key, baseline.generation, current.generation
            )
        return baseline

    def latest(self, key: str) -> Baseline | None:
        bucket = [item for item in self._baselines.values() if item.key == key]
        if not bucket:
            return None
        return sorted(bucket, key=lambda item: item.captured_tick)[-1]

    def baselines(self) -> tuple[Baseline, ...]:
        return tuple(sorted(self._baselines.values(), key=lambda item: item.baseline_id))

    def snapshot(self) -> list[dict]:
        return [item.to_dict() for item in self.baselines()]
