# Instagram Image Downloader

A small Python command-line tool that downloads images from a public Instagram profile.

It's a learning project built around three ideas that come up in almost any program that talks to a web API:

- **Sessions**: reusing connections, headers, and cookies across requests with `requests.Session`
- **Rate limiting**: deliberately spacing requests out, per host
- **Retries and backoff**: handling `429 Too Many Requests` and `5xx` errors without hammering the server

## Project structure

```
.
├── main.py          # CLI entry point: parses arguments, wires everything together
├── errors.py        # Custom exceptions
├── rate_limit.py    # HostRateLimiter: minimum gap between requests, per host
├── http_client.py   # Session wrapper with retries and exponential backoff
├── instagram.py     # Profile fetch, JSON parsing, image download
└── requirements.txt
```

Modules only import "downward" (`errors` ← `rate_limit` ← `http_client` ← `instagram` ← `main`), which keeps circular imports out.

## Setup

Requires Python 3.9+.

```bash
git clone https://github.com/TruSigns/Pythong_Ig_Downloader.git
cd Pythong_Ig_Downloader
pip install -r requirements.txt
```

## Usage

```bash
python main.py <username>
```

Images are saved to `downloads/<username>/` as `<shortcode>_<index>.jpg`, where `shortcode` is the post ID from `instagram.com/p/<shortcode>/` and `index` is the image's position in a carousel. Files that already exist are skipped, so re-running is safe.

### Examples

```bash
python main.py natgeo              # download everything the endpoint returns
python main.py natgeo -n 5         # only the first 5 images
python main.py natgeo -v           # verbose: shows cookies, rate-limit sleeps, retries
python main.py natgeo -o my_pics   # save to ./my_pics/natgeo/
python main.py -h                  # list every option
```

### Options

| Option | Default | Description |
|---|---|---|
| `username` | `revived_signs` | Public Instagram account to download from |
| `-o`, `--out` | `downloads` | Output directory |
| `-n`, `--max` | `0` (all) | Maximum number of images to download |
| `--start-delay` | `0` | Seconds to wait before the first request |
| `--api-interval` | `3.0` | Minimum seconds between requests to instagram.com |
| `--cdn-interval` | `0.75` | Minimum seconds between image downloads |
| `--jitter` | `0.5` | Random extra delay added to each interval |
| `--retries` | `2` | Retries for 429 / 5xx / network errors |
| `--rate-limit-backoff` | `60` | Base wait after a 429, doubled on each retry |
| `-v`, `--verbose` | off | Debug logging |

## How it works

1. **Warm-up.** Loads the instagram.com homepage like a browser would. The response sets cookies (such as `csrftoken`), and the `Session` cookie jar keeps them for every later request.
2. **Profile fetch.** Calls Instagram's web profile endpoint with the headers the website itself sends, then fails fast with a specific error for missing, private, or blocked profiles.
3. **Extract.** Walks the JSON for image URLs, expanding carousels and skipping videos. If the JSON shape has changed, it raises an error instead of guessing.
4. **Download.** Streams each image to a `.part` file in chunks, checks that it's really an image, then renames it into place, so a crash never leaves a half-written file that looks complete.

### Rate limiting

`HostRateLimiter` tracks the last request time **per host**, so the API (slow, strict) and the image CDN (fast) get different intervals. It uses `time.monotonic()` so system clock changes can't break the spacing, and it adds random jitter.

### Retries

- **429**: long exponential backoff (60s, 120s, ...). A `Retry-After` header from the server always takes priority.
- **5xx and network errors**: short exponential backoff (2s, 4s, 8s, ...) with jitter.
- **Other 4xx**: no retry. These won't succeed on a second try, so retrying only wastes requests.

## Limitations

- **Public profiles only.** There's no login support.
- **About 12 posts max.** The anonymous endpoint only returns the most recent posts; that's a server-side limit.
- **Instagram heavily restricts anonymous access.** You may get `429` on the very first request if your IP is flagged. When that happens, wait (sometimes 30+ minutes) rather than retrying; more requests extend the block.
- **Image URLs expire.** They're signed with a time limit, so they're downloaded right after the profile is fetched rather than saved for later.
- **The endpoint is unofficial** and can change or stop working at any time.

## Disclaimer

For educational use. Respect [Instagram's Terms of Use](https://help.instagram.com/581066165581870) and the rights of the people who posted the images. Only download content you have permission to use.
