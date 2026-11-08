"""The Odds API client. The key is passed per run (ODDS_API_KEY) and never stored in the repo."""
import urllib.parse
from .config import ODDS_BASE, LINES, EXCHANGES
from .http import get_json


class OddsClient:
    def __init__(self, api_key, markets="totals,alternate_totals"):
        if not api_key:
            raise ValueError("ODDS_API_KEY is not set. Ask the user for their Odds API key.")
        self.key = api_key
        self.markets = markets
        self.remaining = None

    def _get(self, path, **params):
        params["apiKey"] = self.key
        body, hdr = get_json(f"{ODDS_BASE}{path}?{urllib.parse.urlencode(params)}", return_headers=True)
        hdr = {k.lower(): v for k, v in hdr.items()}
        self.remaining = hdr.get("x-requests-remaining", self.remaining)
        return body

    def events(self, sport_key):
        """Upcoming events for a sport (the /events endpoint does not cost credits)."""
        return self._get(f"/sports/{sport_key}/events", dateFormat="iso")

    def event_totals(self, sport_key, event_id):
        """Over/Under prices for one event, UK region. Costs 1 credit per market requested."""
        return self._get(f"/sports/{sport_key}/events/{event_id}/odds", regions="uk",
                         markets=self.markets, oddsFormat="decimal", dateFormat="iso")


def parse_prices(event):
    """-> {bookmaker_key: {line: {...}}} for lines 1.5/2.5/3.5, preferring margin-adjusted probability."""
    raw = {}
    for b in event.get("bookmakers", []):
        for m in b.get("markets", []):
            for o in m.get("outcomes", []):
                ln = o.get("point")
                if ln not in LINES:
                    continue
                d = raw.setdefault(b["key"], {}).setdefault(ln, {"title": b["title"], "updated": m.get("last_update")})
                d[o["name"][0].upper()] = float(o["price"])  # 'O' / 'U'
    return {bk: {ln: price_record(d["title"], d.get("O"), d.get("U"), d["updated"], bk in EXCHANGES)
                 for ln, d in lines.items() if d.get("O")}
            for bk, lines in raw.items()}


def price_record(title, over, under, updated, exchange=False, source="The Odds API"):
    from .model import implied_probability
    impl, kind = implied_probability(over, under)
    return {"title": title, "over": over, "under": under, "raw": 1 / over, "implied": impl,
            "type": kind, "updated": updated, "exchange": exchange, "source": source}
