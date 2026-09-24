"""只追加的记录文件。

写入先进文件缓冲区；``flush`` 之后才算落盘。落盘与提交是两件事：落盘的记录
仍然不可见，只有水位推到它之后才对外可见。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..errors import StreamError


class Journal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = None
        self._seq = self._count_lines()

    @property
    def path(self) -> Path:
        return self._path

    def _count_lines(self) -> int:
        if not self._path.is_file():
            return 0
        text = self._path.read_text(encoding="utf-8")
        return sum(1 for line in text.splitlines() if line.strip())

    def open(self) -> "Journal":
        if self._handle is None:
            self._handle = self._path.open("a", encoding="utf-8")
        return self

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def append(self, payload: dict) -> int:
        if self._handle is None:
            self.open()
        self._seq += 1
        assert self._handle is not None
        self._handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return self._seq

    def flush(self) -> int:
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
        return self._seq

    def length(self) -> int:
        """已经落盘的行数。"""

        return self._count_lines()

    def buffered(self) -> int:
        """还在缓冲区、尚未落盘的记录条数。"""

        return max(0, self._seq - self.length())

    def allocated(self) -> int:
        return self._seq

    def read_all(self) -> list[dict]:
        if not self._path.is_file():
            return []
        rows: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as broken:
                raise StreamError(f"记录文件在第 {len(rows) + 1} 行损坏") from broken
        return rows

    def read_upto(self, seq: int) -> list[dict]:
        return [row for row in self.read_all() if int(row["seq"]) <= int(seq)]

    def truncate(self) -> None:
        """清空记录流，用于开新航次。调用方负责先落盘再清。"""

        self.flush()
        self.close()
        self._path.write_text("", encoding="utf-8")
        self._seq = 0
