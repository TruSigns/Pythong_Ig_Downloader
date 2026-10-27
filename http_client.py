"""A requests.Session wrapper with rate limiting, retries, and exponential backoff."""
from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime

import requests
from requests.adapters import HTTPAdapter

from errors import BlockedByInstagram, DownloaderError, UnexpectedResponse
from rate_limit import HostRateLimiter

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 600.0


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After is either a number of seconds or an HTTP date."""
    if not value:
        return None
    if value.strip().isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


class HttpClient:
    def __init__(
        self,
        limiter: HostRateLimiter,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        rate_limit_backoff_base: float = 60.0,
        timeout: tuple[float, float] = (5.0, 30.0),  # (connect, read)
    ) -> None:
        self.limiter = limiter
        self.max_retries = max_retries
        self.backoff_base = backoff_base                        # network errors, 5xx
        self.rate_limit_backoff_base = rate_limit_backoff_base  # 429 specifically
        self.timeout = timeout

        # One Session = one connection pool + shared headers/cookies.
        # Every request through it reuses TCP/TLS connections instead of
        # handshaking from scratch each time.
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        # max_retries=0: we handle retries ourselves so the logic is visible.
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0)
        self.session.mount("https://", adapter)

    def close(self) -> None:
        self.session.close()

    def _backoff(self, attempt: int, base: float, retry_after: float | None, reason: str) -> None:
        if retry_after is not None:
            delay = retry_after  # server told us exactly how long; obey it
        else:
            # Exponential backoff with jitter: base, 2*base, 4*base... plus up to 10% noise.
            delay = base * (2 ** attempt)
            delay += random.uniform(0, delay * 0.1)
        delay = min(delay, MAX_BACKOFF_SECONDS)
        log.warning("%s - retry %d/%d in %.1fs", reason, attempt + 1, self.max_retries, delay)
        time.sleep(delay)

    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        stream: bool = False,
        allow_redirects: bool = True,
    ) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            self.limiter.wait(url)
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                    stream=stream,
                    allow_redirects=allow_redirects,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.max_retries:
                    raise DownloaderError(f"network failure after retries: {exc}") from exc
                self._backoff(attempt, self.backoff_base, None,
                              f"network error ({type(exc).__name__}) on {url}")
                continue

            if resp.status_code in RETRYABLE_STATUSES:
                status = resp.status_code
                retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                log.debug("HTTP %d from %s, Retry-After=%r", status, resp.url,
                          resp.headers.get("Retry-After"))
                resp.close()
                if attempt == self.max_retries:
                    if status == 429:
                        raise BlockedByInstagram(
                            f"still rate limited (429) after retries on {url}; wait and try later"
                        )
                    raise UnexpectedResponse(f"HTTP {status} after retries: {url}")
                base = self.rate_limit_backoff_base if status == 429 else self.backoff_base
                self._backoff(attempt, base, retry_after, f"HTTP {status} on {url}")
                continue

            # Anything else (2xx, 3xx, other 4xx) goes back to the caller to judge.
            # Other 4xx are not transient, so retrying them would just waste requests.
            return resp

        raise AssertionError("unreachable")