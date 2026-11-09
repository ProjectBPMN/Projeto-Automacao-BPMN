from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any


class BoundedLRUCache:
    """LRU com limites simultâneos de itens e bytes aproximados."""

    def __init__(self, max_entries: int, max_bytes: int) -> None:
        self.max_entries = max(0, max_entries)
        self.max_bytes = max(0, max_bytes)
        self._items: OrderedDict[str, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    @staticmethod
    def _size(value: Any) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            return 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._items:
                self._misses += 1
                return None
            value, size = self._items.pop(key)
            self._items[key] = (value, size)
            self._hits += 1
            return value

    def put(self, key: str, value: Any) -> None:
        if self.max_entries == 0 or self.max_bytes == 0:
            return
        size = self._size(value)
        if size <= 0 or size > self.max_bytes:
            return
        with self._lock:
            previous = self._items.pop(key, None)
            if previous:
                self._bytes -= previous[1]
            self._items[key] = (value, size)
            self._bytes += size
            while self._items and (
                len(self._items) > self.max_entries or self._bytes > self.max_bytes
            ):
                _, (_, removed_size) = self._items.popitem(last=False)
                self._bytes -= removed_size

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._items),
                "bytes_approx": self._bytes,
                "hits": self._hits,
                "misses": self._misses,
                "max_entries": self.max_entries,
                "max_bytes": self.max_bytes,
            }

