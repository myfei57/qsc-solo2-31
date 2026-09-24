"""配额策略。

每个纪元的处理记录条数有上限，接近上限时提前预告，超过上限直接拒绝写入。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaPolicy:
    limit_per_epoch: int
    warn_ratio: float

    def warn_at(self) -> int:
        return int(self.limit_per_epoch * self.warn_ratio)

    def exceeded(self, used: int) -> bool:
        return int(used) > self.limit_per_epoch

    def warning(self, used: int) -> bool:
        return self.warn_at() <= int(used) <= self.limit_per_epoch

    def to_dict(self) -> dict:
        return {
            "limit_per_epoch": self.limit_per_epoch,
            "warn_ratio": self.warn_ratio,
            "warn_at": self.warn_at(),
        }
