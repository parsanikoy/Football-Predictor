"""Historical match data for backtesting (docs/METHODOLOGY.md §27).

Two sources, both normalised to the same row format:

* football-data.co.uk  - free CSVs, many seasons: goals, shots, shots on target, corners and
                         Over/Under 2.5 odds (pre-match and, from 2019/20, closing). No xG.
* PitchAPI             - the live model's own source: adds xG/xGA, seasons 2021/2022 onwards.
                         One request per match (cached), so fetching is slower.

Row format (dict):
  league, season ('2024/2025'), date ('YYYY-MM-DD'), time ('HH:MM' or ''), home, away, hg, ag,
  stats: {'home': {field: float}, 'away': {...}}   fields from xg, shots, sot, corners (absent = missing)
  odds:  {source: (over, under)}   for the 2.5 line only; sources listed in FD_ODDS.
Nothing is ever zero-filled: a stat that is absent in the source is absent here.
"""
import csv, datetime as dt, difflib, io, json, pathlib, urllib.request

from . import config as C
from .teams import norm

ROOT = pathlib.Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "history"

FD_BASE = "https://www.football-data.co.uk/mmz4281"
FD_CODES = {"epl": "E0", "laliga": "SP1", "seriea": "I1", "bundesliga": "D1", "ligue1": "F1",
            "portugal": "P1", "eredivisie": "N1", "belgium": "B1", "turkey": "T1", "scotland": "SC0"}
# odds source -> (over column candidates, under column candidates); first present column wins
FD_ODDS = {
    "avg":       (("Avg>2.5", "BbAv>2.5"), ("Avg<2.5", "BbAv<2.5")),        # market average, pre-match
    "max":       (("Max>2.5", "BbMx>2.5"), ("Max<2.5", "BbMx<2.5")),        # best available, pre-match
    "b365":      (("B365>2.5",), ("B365<2.5",)),
    "pin":       (("P>2.5",), ("P<2.5",)),                                  # Pinnacle, pre-match
    "pin_close": (("PC>2.5",), ("PC<2.5",)),                                # Pinnacle closing
    "avg_close": (("AvgC>2.5",), ("AvgC<2.5",)),                            # market average closing
}
FD_STATS = {"shots": ("HS", "AS"), "sot": ("HST", "AST"), "corners": ("HC", "AC")}


def season_code(season):
    """'2024/2025' -> '2425'."""
    a, b = season.split("/")
    return a[2:] + b[2:]


def seasons_between(first, last):
    """'2018/2019', '2020/2021' -> ['2018/2019', '2019/2020', '2020/2021']."""
    a, b = int(first[:4]), int(last[:4])
    return [f"{y}/{y + 1}" for y in range(a, b + 1)]


def _float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------- football-data.co.uk
def fd_path(league, season):
    return HIST / "footballdata" / f"{FD_CODES[league]}_{season_code(season)}.csv"


def fd_download(league, season, force=False):
    p = fd_path(league, season)
    if p.exists() and not force:
        return p
    url = f"{FD_BASE}/{season_code(season)}/{FD_CODES[league]}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def fd_parse(text, league, season):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k is not None and isinstance(v, (str, type(None)))}
        d, hg, ag = _date(r.get("Date", "")), _float(r.get("FTHG")), _float(r.get("FTAG"))
        if not d or hg is None or ag is None or not r.get("HomeTeam"):
            continue  # unplayed or malformed line
        stats = {"home": {}, "away": {}}
        for f, (hc, ac) in FD_STATS.items():
            for side, col in (("home", hc), ("away", ac)):
                v = _float(r.get(col))
                if v is not None:
                    stats[side][f] = v
        odds = {}
        for src, (ocols, ucols) in FD_ODDS.items():
            o = next((_float(r[c]) for c in ocols if _float(r.get(c))), None)
            u = next((_float(r[c]) for c in ucols if _float(r.get(c))), None)
            if o and o > 1 and u and u > 1:
                odds[src] = (o, u)
        rows.append({"league": league, "season": season, "date": d, "time": r.get("Time", ""),
                     "home": r["HomeTeam"], "away": r["AwayTeam"], "hg": int(hg), "ag": int(ag),
                     "stats": stats, "odds": odds, "source": "football-data.co.uk"})
    return rows


def load_footballdata(league, season, download=True):
    p = fd_path(league, season)
    if not p.exists():
        if not download:
            return []
        fd_download(league, season)
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return fd_parse(text, league, season)


# ---------------------------------------------------------------- PitchAPI
def pitch_path(league, season):
    return HIST / "pitchapi" / f"{league}_{season.replace('/', '-')}.json"


def load_pitch(league, season, pitch=None, fetch=True, log=print):
    """Finished league matches with stats. Saved as one JSON file per league-season so a backtest
    never re-requests a season it already has."""
    p = pitch_path(league, season)
    if p.exists():
        return json.loads(p.read_text())
    if not fetch:
        return []
    from concurrent.futures import ThreadPoolExecutor
    from .stats import PitchClient, parse_team_stats
    pitch = pitch or PitchClient()
    data = pitch.league_matches(C.LEAGUES[league][2], season)
    fin = [m for m in data["matches"] if m["status"] == "finished"
           and m.get("score_home") is not None and m.get("score_away") is not None]
    log(f"  PitchAPI {league} {season}: fetching stats for {len(fin)} matches (cached per match)")
    with ThreadPoolExecutor(6) as ex:
        stats = list(ex.map(lambda m: parse_team_stats(pitch.match_stats(m["id"], cacheable=True)), fin))
    rows = []
    for m, s in zip(fin, stats):
        rows.append({"league": league, "season": season, "date": m["date"],
                     "time": m["time_utc"][11:16], "home": m["home_team"]["name"],
                     "away": m["away_team"]["name"], "hg": m["score_home"], "ag": m["score_away"],
                     "stats": {side: {f: v for f, v in s[side].items() if f in ("xg", "shots", "sot", "corners")}
                               for side in ("home", "away")},
                     "odds": {}, "source": "PitchAPI", "match_id": m["id"]})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    return rows


def _name_sim(a, b):
    """Name similarity in [0, 1]; short forms ('Wolves' / 'Wolverhampton Wanderers') score 0.8."""
    a, b = norm(a), norm(b)
    r = difflib.SequenceMatcher(None, a, b).ratio()
    return max(r, 0.8) if a[:3] and a[:3] == b[:3] else r


def join_odds(pitch_rows, fd_rows):
    """Copy football-data.co.uk odds onto PitchAPI rows: same league, kick-off date within one day,
    final score equal, and team names that agree after normalisation (fuzzy, reported).
    Returns (matched_count, notes[(pitch_name, fd_name)]) for name pairs that were not exact."""
    by_key = {}
    for r in fd_rows:
        by_key.setdefault((r["league"], r["hg"], r["ag"]), []).append(r)
    notes, n = set(), 0
    for r in pitch_rows:
        d0 = dt.date.fromisoformat(r["date"])
        best, best_s = None, 0.0
        cands = [c for c in by_key.get((r["league"], r["hg"], r["ag"]), [])
                 if abs((dt.date.fromisoformat(c["date"]) - d0).days) <= 1]
        for c in cands:
            sims = (_name_sim(r["home"], c["home"]), _name_sim(r["away"], c["away"]))
            # both names similar, or the only same-score match that day with one name clearly the same
            s = min(sims) if min(sims) >= 0.5 else (max(sims) if len(cands) == 1 and max(sims) >= 0.8 else 0.0)
            if s > best_s:
                best, best_s = c, s
        if best and best_s >= 0.5:
            r["odds"] = dict(best["odds"])
            n += 1
            for a, b in ((r["home"], best["home"]), (r["away"], best["away"])):
                if norm(a) != norm(b):
                    notes.add((a, b))
    return n, sorted(notes)
