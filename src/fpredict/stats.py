"""PitchAPI client. Auth: X-API-KEY header. In Claude cloud sessions the key is injected by the
network proxy, so the header value here is only a placeholder unless PITCHAPI_KEY is set."""
import json, os, pathlib
from .config import PITCH_BASE, STAT_KEYS
from .http import get_json

CACHE = pathlib.Path(os.environ.get("FPREDICT_CACHE", ".cache"))


class PitchClient:
    def __init__(self, api_key=None):
        self.headers = {"X-API-KEY": api_key or os.environ.get("PITCHAPI_KEY") or "proxy-injected"}

    def _get(self, path, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items() if v)
        return get_json(f"{PITCH_BASE}{path}{'?' + q if q else ''}", headers=self.headers)["data"]

    def league_matches(self, league_id, season=None):
        return self._get(f"/leagues/{league_id}/matches", season=season, status="all")

    def match_stats(self, match_id, cacheable=True):
        f = CACHE / "stats" / f"{match_id}.json"
        if cacheable and f.exists():
            return json.loads(f.read_text())
        data = self._get(f"/matches/{match_id}/stats")
        if cacheable:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data))
        return data

    def match(self, match_id):
        return self._get(f"/matches/{match_id}")


def parse_team_stats(data):
    """-> {'home': {field: float}, 'away': {...}} from the full-match ('All') period.
    Fields absent from the source are simply absent (never zero-filled)."""
    out = {"home": {}, "away": {}}
    period = next((p for p in data.get("periods", []) if p.get("period") == "All"), None)
    if not period:
        return out
    for g in period["groups"]:
        for item in g["items"]:
            for field, key in STAT_KEYS.items():
                if item.get("key") != key:
                    continue
                for side in ("home", "away"):
                    try:
                        out[side][field] = float(str(item[side]).split()[0])
                    except (KeyError, ValueError, IndexError):
                        pass
    return out
