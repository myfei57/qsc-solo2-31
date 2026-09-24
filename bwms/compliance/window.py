"""排放窗口。

窗口是半开区间：起点属于本窗，终点属于下一窗。同一个时刻最多落在一个窗口里，
边界时刻的样品因此不会同时被判进两批。同时开着的窗口数量有上限，超过就拒。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ThresholdError, UnknownSubjectError


@dataclass
class DischargeWindow:
    window_id: str
    batch_id: str
    start_tick: int
    end_tick: int
    closed: bool = False

    def contains(self, tick: int) -> bool:
        return self.start_tick <= int(tick) < self.end_tick

    def to_dict(self) -> dict:
        return {
            "window_id": self.window_id,
            "batch_id": self.batch_id,
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "closed": self.closed,
        }


class WindowBook:
    def __init__(self, spec, clock, bus) -> None:
        self._spec = spec
        self._clock = clock
        self._bus = bus
        self._windows: dict[str, DischargeWindow] = {}
        self._counter = 0

    def open(self, batch_id: str) -> DischargeWindow:
        live = self.open_windows()
        if len(live) >= int(self._spec.max_open_windows):
            raise ThresholdError(
                "window", "open_windows", float(len(live) + 1), float(self._spec.max_open_windows)
            )
        self._counter += 1
        start = self._clock.tick
        window = DischargeWindow(
            window_id=f"WIN-{self._counter:04d}",
            batch_id=batch_id,
            start_tick=start,
            end_tick=start + int(self._spec.discharge_window_ticks),
        )
        self._windows[window.window_id] = window
        self._bus.publish("window", {"action": "open", **window.to_dict()})
        return window

    def require(self, window_id: str) -> DischargeWindow:
        window = self._windows.get(window_id)
        if window is None:
            raise UnknownSubjectError(f"没有这个窗口: {window_id}")
        return window

    def assign(self, tick: int) -> DischargeWindow | None:
        """返回包含该时刻的窗口；半开区间保证最多命中一个。"""

        matches = [
            window
            for window in self._windows.values()
            if not window.closed and window.contains(tick)
        ]
        if len(matches) > 1:
            raise ThresholdError(
                "window", "matching_windows", float(len(matches)), 1.0
            )
        return matches[0] if matches else None

    def resolve(self, batch_id: str, tick: int) -> DischargeWindow:
        window = self.assign(tick)
        if window is None:
            raise ThresholdError("window", "sample_tick", float(tick), 0.0)
        if window.batch_id != batch_id:
            raise ThresholdError(
                "window", "batch_mismatch", float(tick), float(window.start_tick)
            )
        return window

    def close(self, window_id: str) -> DischargeWindow:
        window = self.require(window_id)
        window.closed = True
        self._bus.publish("window", {"action": "close", **window.to_dict()})
        return window

    def open_windows(self) -> tuple[DischargeWindow, ...]:
        return tuple(
            sorted(
                (item for item in self._windows.values() if not item.closed),
                key=lambda item: item.window_id,
            )
        )

    def windows(self) -> tuple[DischargeWindow, ...]:
        return tuple(sorted(self._windows.values(), key=lambda item: item.window_id))

    def status(self) -> dict:
        return {
            "window_ticks": self._spec.discharge_window_ticks,
            "max_open": self._spec.max_open_windows,
            "open": [item.to_dict() for item in self.open_windows()],
        }
