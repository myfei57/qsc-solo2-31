"""设备连接关系。

连接表是单向的：装载链、排放链和取样链各自从取源走到终点，路由查询用来在
动作前确认这条路径真的存在，而不是假设设备一定连着。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnknownDeviceError


@dataclass(frozen=True)
class Edge:
    upstream: str
    downstream: str
    medium: str

    def to_dict(self) -> dict:
        return {
            "upstream": self.upstream,
            "downstream": self.downstream,
            "medium": self.medium,
        }


class Topology:
    def __init__(self, registry) -> None:
        self._registry = registry
        self._edges: list[Edge] = []

    def connect(self, upstream: str, downstream: str, medium: str) -> Edge:
        self._registry.require(upstream)
        self._registry.require(downstream)
        edge = Edge(upstream=upstream, downstream=downstream, medium=medium)
        self._edges.append(edge)
        return edge

    def edges(self) -> tuple[Edge, ...]:
        return tuple(self._edges)

    def downstream(self, tag: str) -> tuple[str, ...]:
        self._registry.require(tag)
        return tuple(edge.downstream for edge in self._edges if edge.upstream == tag)

    def upstream(self, tag: str) -> tuple[str, ...]:
        self._registry.require(tag)
        return tuple(edge.upstream for edge in self._edges if edge.downstream == tag)

    def route(self, source: str, target: str) -> tuple[str, ...]:
        """广度优先返回 source → target 的标签序列，走不通就报错。"""

        self._registry.require(source)
        self._registry.require(target)
        queue: list[tuple[str, ...]] = [(source,)]
        seen = {source}
        while queue:
            path = queue.pop(0)
            if path[-1] == target:
                return path
            for neighbour in self.downstream(path[-1]):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                queue.append(path + (neighbour,))
        raise UnknownDeviceError(f"{source} 到 {target} 没有通路")

    def summary(self) -> dict:
        return {
            "edges": [edge.to_dict() for edge in self._edges],
            "media": sorted({edge.medium for edge in self._edges}),
        }
