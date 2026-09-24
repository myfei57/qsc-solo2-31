"""进程内事件总线。

子系统只往总线上发主题事件，审计与告警各自订阅，谁都不需要知道对方存在。
"""

from __future__ import annotations

from typing import Callable, Iterable

WILDCARD = "*"

Subscriber = Callable[[str, dict], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._history: dict[str, list[dict]] = {}

    def subscribe(self, topic: str, handler: Subscriber) -> Callable[[], None]:
        self._subscribers.setdefault(topic, []).append(handler)

        def unsubscribe() -> None:
            handlers = self._subscribers.get(topic, [])
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    def publish(self, topic: str, payload: dict) -> dict:
        event = {"topic": topic, **payload}
        self._history.setdefault(topic, []).append(event)
        for handler in list(self._subscribers.get(topic, [])):
            handler(topic, event)
        for handler in list(self._subscribers.get(WILDCARD, [])):
            handler(topic, event)
        return event

    def history(self, topic: str | None = None) -> list[dict]:
        if topic is None:
            merged: list[dict] = []
            for topic_name in sorted(self._history):
                merged.extend(self._history[topic_name])
            return merged
        return list(self._history.get(topic, []))

    def subscribers(self, topic: str) -> int:
        return len(self._subscribers.get(topic, []))

    def topics(self) -> Iterable[str]:
        return tuple(sorted(self._history))
