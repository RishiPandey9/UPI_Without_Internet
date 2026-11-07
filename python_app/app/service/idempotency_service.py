import time
import threading
from typing import Dict


class IdempotencyService:
    """
    In-memory thread-safe idempotency cache.
    Equivalent to Redis SETNX with TTL.

    Ensures that if multiple bridge nodes upload the same packet simultaneously,
    exactly one claim succeeds and the rest are identified as duplicates.
    """
    def __init__(self, ttl_seconds: int = 86400, auto_evict: bool = True):
        self._ttl_seconds = ttl_seconds
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()
        if auto_evict:
            self._start_eviction_thread()

    def _start_eviction_thread(self, interval_seconds: float = 60.0) -> None:
        def _loop():
            while True:
                time.sleep(interval_seconds)
                self.evict_expired()
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def claim(self, packet_hash: str) -> bool:
        """
        Atomic claim of packet hash.
        Returns True if first claim (winner), False if already claimed (duplicate).
        """
        now = time.time()
        with self._lock:
            # Check if exists and not expired
            if packet_hash in self._seen:
                if now - self._seen[packet_hash] < self._ttl_seconds:
                    return False
            self._seen[packet_hash] = now
            return True

    def size(self) -> int:
        with self._lock:
            return len(self._seen)

    def evict_expired(self) -> None:
        now = time.time()
        with self._lock:
            cutoff = now - self._ttl_seconds
            self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()
