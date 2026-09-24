"""记录流的写读契约。

一次写入分三步走：

1. ``stage``  —— 追加到流尾，拿到序号；此时既不落盘也不可见；
2. ``flush``  —— 落盘，记录进了文件但仍然不可见；
3. ``commit`` —— 推进水位，记录进入投影，从此可查。

未提交的尾巴在重启后一律看不见，重放只认水位以内的记录。回滚不做就地删除，
而是追加一条墓碑记录作废目标序号。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import StreamError, UncommittedRecordError, UnknownRecordError
from ..settings import StoreSpec
from .journal import Journal
from .records import KIND_TOMBSTONE, Record, RecordFilter
from .snapshot import Projection
from .watermark import Watermark


class RecordStream:
    def __init__(self, spec: StoreSpec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        root = Path(spec.root)
        root.mkdir(parents=True, exist_ok=True)
        self._journal = Journal(root / spec.journal_name)
        self._watermark = Watermark(root / spec.watermark_name)
        self._snapshot_path = root / spec.snapshot_name
        self._projection = Projection()
        self._index: dict[int, Record] = {}
        self._staged: list[Record] = []
        self.replay()

    @property
    def projection(self) -> Projection:
        return self._projection

    @property
    def root(self) -> Path:
        return Path(self._spec.root)

    def stage(
        self,
        kind: str,
        subject: str,
        payload: dict,
        generation: int = 0,
        epoch: int = 0,
        supersedes: int | None = None,
        tombstone: bool = False,
    ) -> Record:
        record = Record(
            seq=self._journal.allocated() + 1,
            kind=kind,
            subject=subject,
            tick=self._clock.tick,
            generation=int(generation),
            payload=dict(payload),
            epoch=int(epoch),
            tombstone=bool(tombstone),
            supersedes=supersedes,
        )
        seq = self._journal.append(record.to_dict())
        if seq != record.seq:
            raise StreamError(f"序号错位: 分配 {record.seq} 实际 {seq}")
        self._staged.append(record)
        return record

    def flush(self) -> int:
        flushed = self._journal.flush()
        self._bus.publish("stream", {"action": "flush", "allocated": flushed})
        return flushed

    def buffered(self) -> int:
        """已分配但还没落盘的记录条数。"""

        return self._journal.buffered()

    def commit(self, record: Record | int) -> int:
        seq = record.seq if isinstance(record, Record) else int(record)
        if seq not in {item.seq for item in self._staged}:
            if seq <= self._watermark.value():
                return self._watermark.value()
            raise UnknownRecordError(f"记录 {seq} 不在待提交队列里")
        self.flush()
        batch = [item for item in self._staged if item.seq <= seq]
        for item in batch:
            self._apply(item)
        self._staged = [item for item in self._staged if item.seq > seq]
        self._watermark.advance(seq)
        self._projection_dump()
        self._bus.publish(
            "stream", {"action": "commit", "watermark": seq, "records": len(batch)}
        )
        return seq

    def write(
        self,
        kind: str,
        subject: str,
        payload: dict,
        generation: int = 0,
        epoch: int = 0,
    ) -> Record:
        record = self.stage(kind, subject, payload, generation=generation, epoch=epoch)
        self.commit(record)
        return record

    def tombstone(
        self, seq: int, reason: str, generation: int = 0, epoch: int = 0
    ) -> Record:
        target = self._index.get(int(seq)) or next(
            (item for item in self._staged if item.seq == int(seq)), None
        )
        if target is None:
            raise UnknownRecordError(f"记录 {seq} 不存在")
        record = self.stage(
            KIND_TOMBSTONE,
            target.subject,
            {"reason": reason, "target_kind": target.kind},
            generation=generation,
            epoch=epoch,
            supersedes=int(seq),
            tombstone=True,
        )
        self.commit(record)
        return record

    def _apply(self, record: Record) -> None:
        self._index[record.seq] = record
        self._projection.apply(record)

    def _projection_dump(self) -> None:
        self._snapshot_path.write_text(
            json.dumps(self._projection.state(), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def replay(self) -> dict:
        """按水位重放：只吃水位以内的记录，重建投影。"""

        self._journal.close()
        self._journal = Journal(self._journal.path)
        self._index = {}
        self._staged = []
        self._projection = Projection()
        watermark = self._watermark.reload()
        rows = self._journal.read_upto(watermark)
        for row in rows:
            record = Record.from_dict(row)
            self._apply(record)
        pending = [
            Record.from_dict(row)
            for row in self._journal.read_all()
            if int(row["seq"]) > watermark
        ]
        self._staged = sorted(pending, key=lambda item: item.seq)
        return {
            "watermark": watermark,
            "replayed": len(rows),
            "pending": len(self._staged),
            "digest": self._projection.digest(),
        }

    def restart(self) -> dict:
        """模拟进程重启：关掉句柄，按水位重放，再报一次状态。"""

        report = self.replay()
        self._projection_dump()
        self._bus.publish("stream", {"action": "restart", **report})
        return report

    def watermark(self) -> int:
        return self._watermark.value()

    def allocated(self) -> int:
        return self._journal.allocated()

    def durable(self) -> tuple[Record, ...]:
        """已经落到磁盘上的记录，不论提交与否。"""

        rows = self._journal.read_all()
        return tuple(Record.from_dict(row) for row in rows)

    def pending(self) -> tuple[Record, ...]:
        return tuple(sorted(self._staged, key=lambda item: item.seq))

    def visible(self, criteria: RecordFilter | None = None) -> tuple[Record, ...]:
        filter_ = criteria or RecordFilter()
        rows = self._journal.read_upto(self._watermark.value())
        records = [Record.from_dict(row) for row in rows]
        selected = [
            record
            for record in records
            if not self._projection.is_superseded(record.seq) and filter_.matches(record)
        ]
        if filter_.limit is not None:
            return tuple(selected[: int(filter_.limit)])
        return tuple(selected)

    def get(self, seq: int) -> Record:
        """按序号取已提交记录；未提交的尾巴一律读不到。"""

        target = int(seq)
        record = self._index.get(target)
        if record is None:
            if any(item.seq == target for item in self._staged):
                raise UncommittedRecordError(target, self._watermark.value())
            raise UnknownRecordError(f"记录 {seq} 不在已提交索引里")
        return record

    def latest(self, subject: str) -> Record | None:
        entry = self._projection.latest.get(subject)
        if entry is None:
            return None
        return self._index.get(int(entry["seq"]))

    def count(self, kind: str) -> int:
        return self._projection.count(kind)

    def epoch_count(self, epoch: int) -> int:
        return self._projection.epoch_count(epoch)

    def digest(self) -> str:
        return self._projection.digest()

    def snapshot_digest(self) -> str | None:
        if not self._snapshot_path.is_file():
            return None
        raw = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        projection = Projection()
        projection.load(raw)
        return projection.digest()

    def verify(self) -> dict:
        """比对磁盘快照与按水位重放的结果。"""

        rebuilt = Projection()
        durable = self.durable()
        committed = [record for record in durable if record.seq <= self._watermark.value()]
        for record in committed:
            rebuilt.apply(record)
        stored = self.snapshot_digest()
        return {
            "watermark": self._watermark.value(),
            "replayed_digest": rebuilt.digest(),
            "stored_digest": stored,
            "pending_durable": len(durable) - len(committed),
            "consistent": stored == rebuilt.digest(),
        }

    def truncate(self) -> None:
        """清空整条流，开新航次时使用。"""

        self._journal.truncate()
        self._watermark.reset()
        self._projection = Projection()
        self._index = {}
        self._staged = []
        self._projection_dump()
        self._bus.publish("stream", {"action": "truncate"})
