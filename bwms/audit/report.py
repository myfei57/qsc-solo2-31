"""合规汇总。

汇总不重新算数，全部取自记录流投影与各簿册的当前态，保证报表与明细同源。
"""

from __future__ import annotations

from ..store.records import (
    KIND_ANALYSIS,
    KIND_DISCHARGE,
    KIND_PERMIT,
    KIND_SAMPLE,
)


class ComplianceReport:
    def __init__(self, stream, permits, windows, analyzer, quota, epochs) -> None:
        self._stream = stream
        self._permits = permits
        self._windows = windows
        self._analyzer = analyzer
        self._quota = quota
        self._epochs = epochs

    def build(self) -> dict:
        return {
            "watermark": self._stream.watermark(),
            "digest": self._stream.digest(),
            "records": {
                "samples": self._stream.count(KIND_SAMPLE),
                "analyses": self._stream.count(KIND_ANALYSIS),
                "permits": self._stream.count(KIND_PERMIT),
                "discharges": self._stream.count(KIND_DISCHARGE),
                "total_visible": len(self._stream.visible()),
            },
            "compliance": {
                "permits": self._permits.status(),
                "windows": self._windows.status(),
                "analyzer": self._analyzer.status(),
            },
            "quota": self._quota.status(),
            "epochs": self._epochs.totals(),
            "consistent": self._stream.verify()["consistent"],
        }

    def lines(self) -> tuple[str, ...]:
        report = self.build()
        records = report["records"]
        return (
            f"水位 {report['watermark']} 摘要 {report['digest']}",
            f"水样 {records['samples']} 分析 {records['analyses']} "
            f"许可 {records['permits']} 排放 {records['discharges']}",
            f"纪元 {report['epochs']}",
        )
