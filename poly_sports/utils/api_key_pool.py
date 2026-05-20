"""Round-robin API key pool for The Odds API with usage tracking."""
from __future__ import annotations

import os
import threading
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


class ApiKeyPool:
    """Thread-safe round-robin pool of Odds API keys.

    Reads ``ODDS_API_KEYS`` (comma-separated) from the environment.
    Falls back to ``ODDS_API_KEY`` (single key) for backward compatibility.
    """

    _instance: Optional["ApiKeyPool"] = None
    _lock = threading.Lock()

    def __init__(self, keys: List[str]) -> None:
        self._keys = [k.strip() for k in keys if k.strip()]
        self._index = 0
        self._usage: dict[str, int] = {k: 0 for k in self._keys}
        self._mutex = threading.Lock()

    @classmethod
    def from_env(cls) -> "ApiKeyPool":
        multi = os.getenv("ODDS_API_KEYS", "")
        if multi.strip():
            keys = multi.split(",")
        else:
            single = os.getenv("ODDS_API_KEY", "")
            keys = [single] if single.strip() else []
        return cls(keys)

    @classmethod
    def shared(cls) -> "ApiKeyPool":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls.from_env()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    @property
    def keys(self) -> List[str]:
        return list(self._keys)

    def next_key(self) -> str:
        if not self._keys:
            raise ValueError(
                "No Odds API keys configured. "
                "Set ODDS_API_KEYS or ODDS_API_KEY in .env"
            )
        with self._mutex:
            key = self._keys[self._index % len(self._keys)]
            self._usage[key] += 1
            self._index += 1
            return key

    def usage_summary(self) -> dict[str, int]:
        with self._mutex:
            return dict(self._usage)

    def total_requests(self) -> int:
        with self._mutex:
            return sum(self._usage.values())
