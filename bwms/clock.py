"""可推进的逻辑时钟。

服务里没有任何地方读真实时间：所有时限、窗口和有效期都用这个时钟的 tick 数
表达，测试可以精确地把时间推到边界上。
"""

from __future__ import annotations


class TickClock:
    """单调递增的逻辑时钟，只由显式推进驱动。"""

    def __init__(self, start: int = 0) -> None:
        self._tick = int(start)

    @property
    def tick(self) -> int:
        return self._tick

    def advance(self, steps: int = 1) -> int:
        if steps < 0:
            raise ValueError("tick 只能单调前进")
        self._tick += int(steps)
        return self._tick

    def reached(self, target: int) -> bool:
        return self._tick >= int(target)

    def age(self, since: int) -> int:
        return self._tick - int(since)

    def reset(self, tick: int = 0) -> int:
        self._tick = int(tick)
        return self._tick
