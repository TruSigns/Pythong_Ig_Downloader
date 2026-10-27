"""Per-host rate limiting: a minimum gap between request starts, plus jitter."""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class HostRateLimiter:
    """
    Enforces a minimum gap between request *starts*, tracked per host.
    The API host gets a slow interval; CDN hosts (image files) a faster one.
    Random jitter keeps the timing from looking like a metronome.
    """

    def __init__(self, intervals: dict[str, float], default: float, jitter: float) -> None:
        if default < 0 or jitter < 0 or any(v < 0 for v in intervals.values()):
            raise ValueError("intervals and jitter must be non-negative")
        self.intervals = intervals
        self.default = default
        self.jitter = jitter
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlparse(url).hostname
        if host is None:
            raise ValueError(f"URL has no host: {url}")
        interval = self.intervals.get(host, self.default)
        last = self._last.get(host)
        if last is not None:
            target = last + interval + random.uniform(0, self.jitter)
            delay = target - time.monotonic()  # monotonic: immune to clock changes
            if delay > 0:
                log.debug("rate limit: sleeping %.2fs before %s", delay, host)
                time.sleep(delay)
        self._last[host] = time.monotonic()