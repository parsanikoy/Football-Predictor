"""Minimal JSON-over-HTTPS helper (stdlib only)."""
import json, time, urllib.error, urllib.request
from .config import USER_AGENT


class ApiError(RuntimeError):
    pass


def get_json(url, headers=None, retries=3, return_headers=False):
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                body = json.loads(r.read().decode())
                return (body, dict(r.headers)) if return_headers else body
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(int(e.headers.get("Retry-After") or 2 ** attempt))
                continue
            detail = e.read()[:300].decode(errors="replace")
            raise ApiError(f"HTTP {e.code} for {url.split('?')[0]}: {detail}") from None
        except urllib.error.URLError as e:
            last = e
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
    raise ApiError(f"Request failed for {url.split('?')[0]}: {last}")
