from __future__ import annotations

import time
from collections import defaultdict, deque


def normalize_relay_text(text: str) -> str:
    return " ".join(text.casefold().split())


class ReflectionTracker:
    """Bounded, short-lived record of messages sent by NinjaBridge."""

    def __init__(self, ttl_seconds: float = 120.0, max_per_platform: int = 500) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_per_platform = max_per_platform
        self.items: dict[str, deque[tuple[float, str]]] = defaultdict(deque)

    def add(self, platform: str, text: str) -> None:
        queue = self.items[platform.casefold()]
        self._prune(queue)
        queue.append((time.monotonic(), normalize_relay_text(text)))
        while len(queue) > self.max_per_platform:
            queue.popleft()

    def consume(self, platform: str, text: str) -> bool:
        queue = self.items[platform.casefold()]
        self._prune(queue)
        normalized = normalize_relay_text(text)
        for index, (_, candidate) in enumerate(queue):
            if candidate == normalized:
                del queue[index]
                return True
        return False

    def discard(self, platform: str, text: str) -> None:
        self.consume(platform, text)

    def _prune(self, queue: deque[tuple[float, str]]) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        while queue and queue[0][0] < cutoff:
            queue.popleft()
