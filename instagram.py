"""Instagram-specific logic: fetch a profile, pull image URLs out of it, download them."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from errors import BlockedByInstagram, PrivateProfile, ProfileNotFound, UnexpectedResponse
from http_client import HttpClient

log = logging.getLogger(__name__)

HOME_URL = "https://www.instagram.com/"
PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
API_HOST = "www.instagram.com"
# The instagram.com web app sends this header; the endpoint rejects requests without it.
IG_APP_ID = "936619743392459"


@dataclass(frozen=True)
class ImageItem:
    shortcode: str  # the post ID in instagram.com/p/<shortcode>/
    index: int      # position inside a carousel; 0 for single-image posts
    url: str


def warm_up(client: HttpClient) -> None:
    """
    Load the homepage like a browser would. The response sets cookies
    (csrftoken, mid, ig_did...) and the Session's cookie jar keeps them,
    so every later request sends them automatically.
    """
    resp = client.get(HOME_URL)
    with resp:
        if resp.status_code != 200:
            raise UnexpectedResponse(f"homepage returned HTTP {resp.status_code}")
    names = sorted(client.session.cookies.keys())
    log.debug("cookies after warm-up: %s", names)
    if "csrftoken" not in names:
        log.warning("no csrftoken cookie from homepage; the API call will likely be rejected")


def fetch_profile(client: HttpClient, username: str) -> dict:
    resp = client.get(
        PROFILE_URL,
        params={"username": username},
        headers={
            "X-IG-App-ID": IG_APP_ID,
            "X-CSRFToken": client.session.cookies.get("csrftoken", ""),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.instagram.com/{username}/",
        },
        allow_redirects=False,  # a redirect here means "go log in"; we want to see it
    )
    with resp:
        if resp.status_code == 404:
            raise ProfileNotFound(f"no such profile: {username}")
        if resp.is_redirect or resp.status_code in (401, 403):
            raise BlockedByInstagram(
                f"Instagram wants a login (HTTP {resp.status_code}). "
                "Usually means too many anonymous requests from your IP; wait a while."
            )
        if resp.status_code != 200:
            raise UnexpectedResponse(f"profile request returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise UnexpectedResponse("profile response was not JSON") from exc

    if not isinstance(payload, dict):
        raise UnexpectedResponse("profile JSON was not an object")
    user = (payload.get("data") or {}).get("user")
    if user is None:
        raise ProfileNotFound(f"no such profile: {username}")
    if user.get("is_private"):
        raise PrivateProfile(f"{username} is private")
    return user


def extract_images(user: dict) -> list[ImageItem]:
    try:
        edges = user["edge_owner_to_timeline_media"]["edges"]
        items: list[ImageItem] = []
        for edge in edges:
            node = edge["node"]
            shortcode = node["shortcode"]
            sidecar = node.get("edge_sidecar_to_children")  # present on carousels
            nodes = [child["node"] for child in sidecar["edges"]] if sidecar else [node]
            for i, media in enumerate(nodes):
                if media.get("is_video"):
                    continue
                items.append(ImageItem(shortcode, i, media["display_url"]))
        return items
    except (KeyError, TypeError) as exc:
        # Fail fast: if Instagram changed the JSON shape, don't guess.
        raise UnexpectedResponse(f"profile JSON missing expected field: {exc!r}") from exc


def download_image(client: HttpClient, item: ImageItem, out_dir: Path) -> Path | None:
    ext = Path(urlparse(item.url).path).suffix or ".jpg"
    dest = out_dir / f"{item.shortcode}_{item.index:02d}{ext}"
    if dest.exists():
        log.info("skip %s (already downloaded)", dest.name)
        return None

    # Write to .part then rename, so a crash never leaves a half-file
    # that looks complete on the next run.
    tmp = dest.with_name(dest.name + ".part")
    resp = client.get(item.url, stream=True)
    try:
        with resp:
            if resp.status_code != 200:
                raise UnexpectedResponse(f"image HTTP {resp.status_code}: {item.shortcode}")
            ctype = resp.headers.get("Content-Type", "")
            if not ctype.startswith("image/"):
                raise UnexpectedResponse(f"expected an image, got {ctype!r}: {item.shortcode}")
            with tmp.open("wb") as fh:
                # stream=True + iter_content: never holds the whole file in memory
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    fh.write(chunk)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    log.info("saved %s", dest.name)
    return dest