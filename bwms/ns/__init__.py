"""设备命名空间：标识登记、连接关系与管路阀门状态。"""

from __future__ import annotations

from .pipe import PipeHeader, PipeSegment
from .registry import Device, DeviceRegistry
from .topology import Edge, Topology

__all__ = [
    "Device",
    "DeviceRegistry",
    "Edge",
    "Topology",
    "PipeHeader",
    "PipeSegment",
]
