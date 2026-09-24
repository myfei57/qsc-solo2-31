"""投影快照。

投影只吃已提交且未被打墓碑的记录，产出计数、主体最新态、纪元归属与参数代际
四类派生状态。重启时投影由记录流重放重建，快照文件只用于比对重放结果是否
与上次提交一致。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .records import KIND_PARAMETER, Record


@dataclass
class Projection:
    counts: dict[str, int] = field(default_factory=dict)
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    epoch_counts: dict[str, int] = field(default_factory=dict)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    superseded: list[int] = field(default_factory=list)
    record_kinds: dict[str, str] = field(default_factory=dict)
    last_tick: int = 0
    applied: int = 0

    def apply(self, record: Record) -> None:
        self.record_kinds[str(record.seq)] = record.kind
        self.applied += 1
        self.last_tick = max(self.last_tick, record.tick)
        if record.tombstone:
            self._annul(record)
            return
        self.counts[record.kind] = self.counts.get(record.kind, 0) + 1
        self.epoch_counts[str(record.epoch)] = (
            self.epoch_counts.get(str(record.epoch), 0) + 1
        )
        self.latest[record.subject] = {
            "seq": record.seq,
            "kind": record.kind,
            "tick": record.tick,
            "generation": record.generation,
            "payload": dict(record.payload),
        }
        if record.kind == KIND_PARAMETER:
            self.parameters[record.subject] = {
                "generation": record.generation,
                "values": dict(record.payload),
            }

    def _annul(self, record: Record) -> None:
        target = record.supersedes
        if target is None:
            return
        self.superseded.append(int(target))
        self.superseded = sorted(set(self.superseded))
        kind = self.record_kinds.get(str(target))
        if kind is not None and kind in self.counts:
            self.counts[kind] = max(0, self.counts[kind] - 1)
        if self.latest.get(record.subject, {}).get("seq") == target:
            self.latest.pop(record.subject, None)

    def is_superseded(self, seq: int) -> bool:
        return int(seq) in set(self.superseded)

    def count(self, kind: str) -> int:
        return self.counts.get(kind, 0)

    def epoch_count(self, epoch: int) -> int:
        return self.epoch_counts.get(str(epoch), 0)

    def parameter(self, key: str) -> dict[str, Any] | None:
        return self.parameters.get(key)

    def state(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "latest": {key: dict(value) for key, value in sorted(self.latest.items())},
            "epoch_counts": dict(sorted(self.epoch_counts.items())),
            "parameters": {
                key: dict(value) for key, value in sorted(self.parameters.items())
            },
            "superseded": list(self.superseded),
            "record_kinds": dict(sorted(self.record_kinds.items())),
            "last_tick": self.last_tick,
            "applied": self.applied,
        }

    def load(self, raw: dict[str, Any]) -> None:
        self.counts = {str(k): int(v) for k, v in raw.get("counts", {}).items()}
        self.latest = {str(k): dict(v) for k, v in raw.get("latest", {}).items()}
        self.epoch_counts = {
            str(k): int(v) for k, v in raw.get("epoch_counts", {}).items()
        }
        self.parameters = {str(k): dict(v) for k, v in raw.get("parameters", {}).items()}
        self.superseded = [int(item) for item in raw.get("superseded", [])]
        self.record_kinds = {
            str(k): str(v) for k, v in raw.get("record_kinds", {}).items()
        }
        self.last_tick = int(raw.get("last_tick", 0))
        self.applied = int(raw.get("applied", 0))

    def digest(self) -> str:
        blob = json.dumps(self.state(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
