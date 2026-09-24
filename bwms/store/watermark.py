"""提交水位。

水位是"已提交到第几条"的唯一事实，只允许前进。重启后所有可见性判断都以
水位为准，水位之后的记录一律当作未提交。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import StreamError


class Watermark:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._value = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> int:
        if not self._path.is_file():
            return 0
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        return int(raw.get("watermark", 0))

    def value(self) -> int:
        return self._value

    def reload(self) -> int:
        self._value = self._load()
        return self._value

    def advance(self, seq: int) -> int:
        seq = int(seq)
        if seq < self._value:
            raise StreamError(f"水位只能前进: {self._value} → {seq}")
        self._value = seq
        self.persist()
        return self._value

    def reset(self) -> int:
        """开新航次时的管理性归零，正常写入路径不会用到。"""

        self._value = 0
        self.persist()
        return self._value

    def persist(self) -> int:
        self._path.write_text(
            json.dumps({"watermark": self._value}, sort_keys=True), encoding="utf-8"
        )
        return self._value
