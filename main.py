#!/usr/bin/env python3
"""
Entry point: download images from a public Instagram profile.

Public profiles only, no login. Respect Instagram's Terms of Use and
the rights of whoever posted the images.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from errors import DownloaderError
from http_client import HttpClient
from instagram import API_HOST, download_image, extract_images, fetch_profile, warm_up
from rate_limit import HostRateLimiter

log = logging.getLogger("ig_downloader")

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download images from a public Instagram profile.")
    p.add_argument("username", nargs="?", default="revived_signs")
    p.add_argument("-o", "--out", default="downloads", help="output directory (default: downloads)")
    p.add_argument("-n", "--max", type=int, default=0, help="max images to download (0 = all returned)")
    p.add_argument("--start-delay", type=float, default=0.0, help="seconds to wait before the first request")
    p.add_argument("--api-interval", type=float, default=3.0, help="seconds between API requests")
    p.add_argument("--cdn-interval", type=float, default=0.75, help="seconds between image requests")
    p.add_argument("--jitter", type=float, default=0.5, help="random extra delay, seconds")
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--rate-limit-backoff", type=float, default=60.0,
                   help="base wait after a 429, doubled each retry (default: 60)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not USERNAME_RE.fullmatch(args.username):
        p.error(f"invalid Instagram username: {args.username!r}")
    if args.max < 0 or args.retries < 0 or args.start_delay < 0 or args.rate_limit_backoff < 0:
        p.error("--max, --retries, --start-delay and --rate-limit-backoff must be >= 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Configures the root logger, so the loggers in every module print too.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )

    out_dir = Path(args.out) / args.username
    out_dir.mkdir(parents=True, exist_ok=True)

    limiter = HostRateLimiter(
        intervals={API_HOST: args.api_interval},
        default=args.cdn_interval,  # CDN hosts vary (scontent-*.cdninstagram.com)
        jitter=args.jitter,
    )
    client = HttpClient(
        limiter,
        max_retries=args.retries,
        rate_limit_backoff_base=args.rate_limit_backoff,
    )

    if args.start_delay:
        log.info("waiting %.0fs before first request", args.start_delay)
        time.sleep(args.start_delay)

    try:
        warm_up(client)
        user = fetch_profile(client, args.username)
        items = extract_images(user)
        if args.max:
            items = items[: args.max]
        log.info("found %d images for %s", len(items), args.username)

        saved = 0
        for item in items:
            if download_image(client, item, out_dir):
                saved += 1
    except DownloaderError as exc:
        log.error("%s", exc)
        return 1
    finally:
        client.close()

    log.info("done: %d new, %d skipped -> %s", saved, len(items) - saved, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())