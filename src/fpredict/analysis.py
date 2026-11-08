"""Orchestration: fixtures -> samples -> model -> edges -> recommendations -> bookmaker assessment."""
import datetime as dt
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor

from . import config as C
from . import model as M
from .odds import parse_prices, price_record
from .stats import parse_team_stats
from .teams import load_aliases, norm, resolve


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- user-supplied data
def load_user_supplied(path):
    """JSON: {"match_stats": {"<pitch match id>": {"home": {"xg": 1.2}, "away": {...}}},
              "baselines": {"<league key>": {"xg": 1.45, ...}},
              "odds": [{"home": "...", "away": "...", "bookmaker": "...", "line": 2.5,
                        "over": 1.9, "under": 1.95, "captured_at": "..."}]}"""
    if not path:
        return {}
    p = pathlib.Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------- league context
def league_baseline(finished, league, user):
    """League averages per team per match from the given finished matches (§4), plus user overrides.
    -> (baseline, coverage, n_matches)"""
    base, cov = {}, {}
    for f in ("xg", "shots", "sot", "corners"):
        vals = [m["stats"][s][f] for m in finished for s in ("home", "away") if f in m["stats"][s]]
        base[f] = sum(vals) / len(vals) if vals else None
        cov[f] = (len(vals), 2 * len(finished))
    n = len(finished)
    base["home_goals"] = sum(m["score_home"] for m in finished) / n if n else None
    base["away_goals"] = sum(m["score_away"] for m in finished) / n if n else None
    base["sources"] = {}
    for f, v in user.get("baselines", {}).get(league, {}).items():
        base[f] = float(v)
        base["sources"][f] = "User supplied"
    return base, cov, n


def as_of(ctx, cutoff):
    """Copy of a league context restricted to matches that kicked off before `cutoff` (ISO UTC),
    with league averages recomputed from those matches only. Used by the backtest so that no
    information from the match being predicted, or later, leaks into the prediction. User-supplied
    baselines are NOT applied: they describe the league now, not as it stood at `cutoff`."""
    finished = [m for m in ctx["finished"] if m["time_utc"] < cutoff]
    base, cov, n = league_baseline(finished, ctx["league"], {})
    return dict(ctx, finished=finished, baseline=base, coverage=cov, n_finished=n)


def league_context(pitch, league, now, user):
    name, sport_key, lid = C.LEAGUES[league]
    data = pitch.league_matches(lid)
    matches = data["matches"]
    finished = [m for m in matches if m["status"] == "finished" and m["time_utc"] < iso(now)]
    # PitchAPI can revise stats (notably xG) shortly after full time, so only cache settled matches.
    settled = iso(now - dt.timedelta(hours=48))
    with ThreadPoolExecutor(6) as ex:
        stats = list(ex.map(lambda m: parse_team_stats(
            pitch.match_stats(m["id"], cacheable=m["time_utc"] < settled)), finished))
    over = user.get("match_stats", {})
    for m, s in zip(finished, stats):
        m["stats"] = s
        m["user_fields"] = []
        for side in ("home", "away"):
            for f, v in over.get(m["id"], {}).get(side, {}).items():
                if f not in s[side]:
                    s[side][f] = float(v)
                    m["user_fields"].append(f"{side}.{f}")
    base, cov, n = league_baseline(finished, league, user)
    teams = {}
    for m in matches:
        for side in ("home_team", "away_team"):
            teams[m[side]["id"]] = m[side]["name"]
    return {"league": league, "name": name, "sport_key": sport_key, "season": data["league"].get("season"),
            "matches": matches, "finished": finished, "baseline": base, "coverage": cov,
            "n_finished": n, "teams": teams}


def team_sample(ctx, team_id, n=C.SAMPLE_SIZE):
    """n most recent completed league matches (five for the model). Returns (rows, missing[(date, opponent, field)])."""
    played = sorted((m for m in ctx["finished"] if team_id in (m["home_team"]["id"], m["away_team"]["id"])),
                    key=lambda m: m["time_utc"], reverse=True)[:n]
    rows, missing = [], []
    for m in played:
        s = "home" if m["home_team"]["id"] == team_id else "away"
        o = "away" if s == "home" else "home"
        row = {"match_id": m["id"], "date": m["date"], "venue": s[0].upper(),
               "opponent": m[o + "_team"]["name"], "score": f"{m['score_home']}-{m['score_away']}",
               "user_fields": [x for x in m["user_fields"]]}
        for f in ("xg", "shots", "sot", "corners"):
            row[f] = m["stats"][s].get(f)
            row["conc_" + f] = m["stats"][o].get(f)
            for key in (f, "conc_" + f):
                if row[key] is None:
                    missing.append((m["date"], row["opponent"], key))
        row["red_for"] = m["stats"][s].get("red")
        row["red_against"] = m["stats"][o].get("red")
        rows.append(row)
    return rows, missing


# ---------------------------------------------------------------- odds join
def attach_odds(fixtures, ctx_by_league, odds_client, user, log):
    """Match Odds API events to PitchAPI fixtures by team id; fetch Over/Under prices."""
    aliases = load_aliases()
    mapping_notes = []
    by_pair = {(f["home_id"], f["away_id"]): f for f in fixtures}
    if odds_client:
        for league in sorted({f["league"] for f in fixtures}):
            ctx = ctx_by_league[league]
            try:
                events = odds_client.events(ctx["sport_key"])
            except Exception as e:  # league not active in the odds feed
                log(f"  odds: {ctx['name']}: no events ({e})")
                continue
            for ev in events:
                h = resolve(league, ev["home_team"], ctx["teams"], aliases)
                a = resolve(league, ev["away_team"], ctx["teams"], aliases)
                fx = by_pair.get((h[0], a[0]))
                if not fx:
                    continue
                for odds_name, r in ((ev["home_team"], h), (ev["away_team"], a)):
                    if r[2] == "fuzzy":
                        mapping_notes.append((ctx["name"], odds_name, r[1]))
                body = odds_client.event_totals(ctx["sport_key"], ev["id"])
                fx["odds"].update(parse_prices(body))
                fx["odds_event_time"] = ev["commence_time"]
            log(f"  odds: {ctx['name']} done (credits remaining: {odds_client.remaining})")
    for o in user.get("odds", []):
        for fx in fixtures:
            if norm(o["home"]) == norm(fx["home"]) and norm(o["away"]) == norm(fx["away"]):
                key = "user:" + o["bookmaker"].lower().replace(" ", "")
                fx["odds"].setdefault(key, {})[float(o["line"])] = price_record(
                    o["bookmaker"], float(o["over"]), o.get("under") and float(o["under"]),
                    o.get("captured_at"), source="User supplied")
    return mapping_notes


# ---------------------------------------------------------------- per-fixture model
def analyse(fx, ctx, fallback_ok):
    base = ctx["baseline"]
    fx["baseline"] = base
    for need in ("shots", "sot", "corners", "home_goals", "away_goals"):
        if base.get(need) is None:
            fx["missing"].append(("league", "-", "-", f"league average {need}"))
    samples = {}
    for side in ("home", "away"):
        rows, miss = team_sample(ctx, fx[side + "_id"])
        samples[side] = rows
        if len(rows) < C.SAMPLE_SIZE:
            fx["missing"].append((side, "-", "-", f"only {len(rows)} completed league matches this season"))
        fx["missing"] += [(side,) + m for m in miss]
    fx["samples"] = samples
    xg_missing = [m for m in fx["missing"] if m[-1] in ("xg", "conc_xg")]
    if base.get("xg") is None:
        xg_missing.append(("league", "-", "-", "league average xG"))
    core_missing = [m for m in fx["missing"] if m not in xg_missing]
    if core_missing:
        fx["status"] = "blocked"
        return fx
    if xg_missing:
        if not fallback_ok:
            fx["status"] = "needs_fallback_choice"
            fx["missing"] = xg_missing
            return fx
        fx["model_type"] = "fallback"
    else:
        fx["model_type"] = "preferred"
    H = M.team_scores(samples["home"], base, fx["model_type"])
    A = M.team_scores(samples["away"], base, fx["model_type"])
    E = M.expected_goals(H, A, base)
    fx.update(status="modelled", H=H, A=A, E=E, P=M.poisson_overs(E["total"]))
    return fx


def line_edges(fx):
    """Best sportsbook (non-exchange) edge per line -> {line: (edge, bookmaker_key, price_record)}."""
    out = {}
    for ln in C.LINES:
        cands = [(M.edge_pp(fx["P"][ln], d["implied"]), bk, d)
                 for bk, lines in fx["odds"].items() for l, d in lines.items()
                 if float(l) == ln and not d["exchange"]]
        if cands:
            out[ln] = max(cands, key=lambda t: t[0])
    return out


def recommend(fixtures):
    recs = {}
    for fx in fixtures:
        if fx["status"] != "modelled" or fx["started"]:
            continue
        fx["edges"] = line_edges(fx)
        q = [(e, ln, bk, d) for ln, (e, bk, d) in fx["edges"].items() if e >= C.MIN_EDGE_PP]
        if q:
            recs[fx["key"]] = max(q, key=lambda t: t[0])
    return recs


def bookmaker_assessment(fixtures, recs):
    fx_by_key = {f["key"]: f for f in fixtures}
    books = {}
    for f in fixtures:
        for bk, lines in f["odds"].items():
            if lines and not next(iter(lines.values()))["exchange"]:
                books[bk] = next(iter(lines.values()))["title"]
    rows = []
    for bk, title in books.items():
        have, miss = [], []
        for key, (e, ln, _, _) in recs.items():
            f = fx_by_key[key]
            d = f["odds"].get(bk, {}).get(ln)
            if d:
                have.append((key, ln, d, M.edge_pp(f["P"][ln], d["implied"])))
            else:
                miss.append(key)
        mean = sum(h[3] for h in have) / len(have) if have else None
        rows.append({"bookmaker": bk, "title": title, "have": have, "missing": miss, "mean_edge": mean,
                     "eligible": bool(recs) and not miss})
    rows.sort(key=lambda r: (-len(r["have"]), -(r["mean_edge"] or -99)))
    eligible = [r for r in rows if r["eligible"]]
    return {"rows": rows, "recommended": eligible[0] if eligible else None}


# ---------------------------------------------------------------- top level
def run(pitch, odds_client, leagues, date_from, date_to, fallback=(), only=(), user=None, log=print):
    user = user or {}
    now = utcnow()
    ctx_by_league, fixtures, excluded = {}, [], []
    for lg in leagues:
        log(f"stats: {C.LEAGUES[lg][0]} ...")
        ctx = league_context(pitch, lg, now, user)
        ctx_by_league[lg] = ctx
        for m in ctx["matches"]:
            if not (date_from <= m["date"] <= date_to) or m["status"] == "finished":
                continue
            label = f"{m['home_team']['name']} v {m['away_team']['name']}"
            if only and not any(o.lower() in label.lower() for o in only):
                continue
            started = m["time_utc"] <= iso(now) or m["status"] not in ("not_started", "scheduled")
            fx = {"key": m["id"], "league": lg, "league_name": ctx["name"], "kickoff": m["time_utc"],
                  "home": m["home_team"]["name"], "away": m["away_team"]["name"],
                  "home_id": m["home_team"]["id"], "away_id": m["away_team"]["id"], "label": label,
                  "status": None, "started": started, "missing": [], "odds": {}}
            if started:
                excluded.append((label, ctx["name"], "match has started or is not in a pre-match state"))
                continue
            fixtures.append(fx)
    log(f"fixtures in window: {len(fixtures)}")
    mapping_notes = attach_odds(fixtures, ctx_by_league, odds_client, user, log)
    fb_all = "all" in [x.lower() for x in fallback]
    for fx in fixtures:
        ok = fb_all or any(x.lower() in fx["label"].lower() for x in fallback)
        analyse(fx, ctx_by_league[fx["league"]], ok)
    recs = recommend(fixtures)
    return {"generated_at": iso(now), "window": (date_from, date_to), "leagues": leagues,
            "contexts": ctx_by_league, "fixtures": fixtures, "excluded": excluded, "recs": recs,
            "books": bookmaker_assessment(fixtures, recs), "mapping_notes": mapping_notes,
            "odds_remaining": odds_client.remaining if odds_client else None}
