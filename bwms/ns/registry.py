"""设备标识登记。

任何按标签寻址的动作都先经过这里，标签写错了要当场报错，而不是在后面拿
一个空对象继续跑。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnknownDeviceError


@dataclass(frozen=True)
class Device:
    tag: str
    kind: str
    area: str

    def to_dict(self) -> dict:
        return {"tag": self.tag, "kind": self.kind, "area": self.area}


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}

    def register(self, tag: str, kind: str, area: str) -> Device:
        device = Device(tag=tag, kind=kind, area=area)
        self._devices[tag] = device
        return device

    def require(self, tag: str) -> Device:
        device = self._devices.get(tag)
        if device is None:
            raise UnknownDeviceError(f"未登记的标识: {tag}")
        return device

    def tags(self) -> tuple[str, ...]:
        return tuple(sorted(self._devices))

    def by_kind(self, kind: str) -> tuple[Device, ...]:
        return tuple(
            device for _, device in sorted(self._devices.items()) if device.kind == kind
        )

    def areas(self) -> tuple[str, ...]:
        return tuple(sorted({device.area for device in self._devices.values()}))

    def summary(self) -> dict:
        kinds: dict[str, int] = {}
        for device in self._devices.values():
            kinds[device.kind] = kinds.get(device.kind, 0) + 1
        return {
            "count": len(self._devices),
            "kinds": kinds,
            "areas": list(self.areas()),
        }
