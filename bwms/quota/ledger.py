"""配额账。

用量直接取记录流里该纪元的条数，不另做一份计数，避免两处数字对不上。写入前
先申请余量，申请不通过就不写。
"""

from __future__ import annotations

from ..errors import QuotaExceededError


class QuotaLedger:
    def __init__(self, policy, stream, clock, bus, epoch_source) -> None:
        self._policy = policy
        self._stream = stream
        self._clock = clock
        self._bus = bus
        self._epoch_source = epoch_source
        self._warnings: list[dict] = []

    def policy(self) -> dict:
        return self._policy.to_dict()

    def used(self, epoch: int | None = None) -> int:
        moment = self._epoch_source() if epoch is None else int(epoch)
        return self._stream.epoch_count(moment)

    def remaining(self, epoch: int | None = None) -> int:
        return max(0, self._policy.limit_per_epoch - self.used(epoch))

    def require_room(self, extra: int = 1) -> dict:
        epoch = self._epoch_source()
        used = self.used(epoch)
        if used + int(extra) > self._policy.limit_per_epoch:
            raise QuotaExceededError(epoch, used + int(extra), self._policy.limit_per_epoch)
        entry = {
            "epoch": epoch,
            "used": used,
            "remaining": self._policy.limit_per_epoch - used,
            "tick": self._clock.tick,
        }
        if self._policy.warning(used + int(extra)):
            self._warnings.append(entry)
            self._bus.publish("quota", {"action": "warn", **entry})
        return entry

    def warnings(self) -> tuple[dict, ...]:
        return tuple(self._warnings)

    def epochs(self) -> tuple[int, ...]:
        return tuple(sorted(int(key) for key in self._stream.projection.epoch_counts))

    def status(self) -> dict:
        epoch = self._epoch_source()
        return {
            "epoch": epoch,
            "used": self.used(epoch),
            "remaining": self.remaining(epoch),
            "warn_at": self._policy.warn_at(),
            "limit_per_epoch": self._policy.limit_per_epoch,
            "warnings": len(self._warnings),
            "epochs": list(self.epochs()),
        }
