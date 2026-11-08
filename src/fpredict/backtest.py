"""Pre-kick-off backtest without odds (docs/METHODOLOGY.md §27, accuracy part only).

For every finished league match in a date window, rebuild the model's inputs exactly as they stood
before kick-off (each team's five previous league matches and league averages from matches that had
already finished), predict Over 1.5/2.5/3.5, and score the predictions against the real result.

No bookmaker odds are used, so edge, ROI and closing-line value cannot be measured here.
"""
import csv
import datetime as dt
import math

from . import analysis
from . import config as C
from . import model as M

# A match only counts as "already finished" for a later fixture if it kicked off at least this long
# before that fixture, so that a match still in progress at kick-off is never used.
FINISH_GAP = dt.timedelta(hours=3)
EPS = 1e-12


def _parse(t):
    return dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def brier(p, y):
    return (p - y) ** 2


def log_loss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def run(pitch, leagues, date_from, date_to, fallback=(), only=(), user=None, log=print):
    user = user or {}
    now = analysis.utcnow()
    fb_all = "all" in [x.lower() for x in fallback]
    rows, skipped = [], []
    for lg in leagues:
        log(f"stats: {C.LEAGUES[lg][0]} ...")
        ctx = analysis.league_context(pitch, lg, now, user)
        for m in sorted(ctx["finished"], key=lambda m: m["time_utc"]):
            if not (date_from <= m["date"] <= date_to):
                continue
            label = f"{m['home_team']['name']} v {m['away_team']['name']}"
            if only and not any(o.lower() in label.lower() for o in only):
                continue
            cutoff = analysis.iso(_parse(m["time_utc"]) - FINISH_GAP)
            pre = analysis.as_of(ctx, cutoff)
            fx = {"key": m["id"], "league": lg, "league_name": ctx["name"], "kickoff": m["time_utc"],
                  "home": m["home_team"]["name"], "away": m["away_team"]["name"],
                  "home_id": m["home_team"]["id"], "away_id": m["away_team"]["id"], "label": label,
                  "status": None, "started": False, "missing": [], "odds": {}}
            ok = fb_all or any(x.lower() in label.lower() for x in fallback)
            analysis.analyse(fx, pre, ok)
            goals = m["score_home"] + m["score_away"]
            if fx["status"] != "modelled":
                skipped.append({"label": label, "league": ctx["name"], "kickoff": m["time_utc"],
                                "status": fx["status"], "missing": fx["missing"]})
                continue
            base = pre["baseline"]
            bench = M.poisson_overs(base["home_goals"] + base["away_goals"])
            rows.append({"match_id": m["id"], "league": ctx["name"], "match": label, "kickoff": m["time_utc"],
                         "model_type": fx["model_type"], "exp_home": fx["E"]["home"], "exp_away": fx["E"]["away"],
                         "exp_total": fx["E"]["total"], "league_avg_total": base["home_goals"] + base["away_goals"],
                         "league_matches_before": pre["n_finished"],
                         "home_attack": fx["H"]["attack"], "home_dw": fx["H"]["dw"],
                         "away_attack": fx["A"]["attack"], "away_dw": fx["A"]["dw"],
                         "score": f"{m['score_home']}-{m['score_away']}", "goals": goals,
                         "p": fx["P"], "bench": bench, "y": {ln: int(goals > ln) for ln in C.LINES}})
    return {"generated_at": analysis.iso(now), "window": (date_from, date_to), "leagues": leagues,
            "rows": rows, "skipped": skipped, "summary": summarise(rows)}


def _scores(rows, ln):
    n = len(rows)
    if not n:
        return None
    y = [r["y"][ln] for r in rows]
    pm = [r["p"][ln] for r in rows]
    pb = [r["bench"][ln] for r in rows]
    bm = sum(map(brier, pm, y)) / n
    bb = sum(map(brier, pb, y)) / n
    return {"n": n, "hit_rate": sum(y) / n, "mean_model": sum(pm) / n, "mean_bench": sum(pb) / n,
            "brier_model": bm, "brier_bench": bb, "skill": (1 - bm / bb) if bb > 0 else None,
            "logloss_model": sum(map(log_loss, pm, y)) / n, "logloss_bench": sum(map(log_loss, pb, y)) / n}


def calibration(rows, bins=(0, 0.2, 0.4, 0.6, 0.8, 1.0001)):
    """Pooled across all three lines: predicted probability band -> (n, mean predicted, observed rate)."""
    out = []
    pairs = [(r["p"][ln], r["y"][ln]) for r in rows for ln in C.LINES]
    for lo, hi in zip(bins, bins[1:]):
        b = [(p, y) for p, y in pairs if lo <= p < hi]
        if b:
            out.append((lo, min(hi, 1.0), len(b), sum(p for p, _ in b) / len(b), sum(y for _, y in b) / len(b)))
    return out


def summarise(rows):
    s = {"by_line": {ln: _scores(rows, ln) for ln in C.LINES}, "calibration": calibration(rows), "by_league": {}}
    if rows:
        err = [r["exp_total"] - r["goals"] for r in rows]
        s["goals"] = {"mean_expected": sum(r["exp_total"] for r in rows) / len(rows),
                      "mean_actual": sum(r["goals"] for r in rows) / len(rows),
                      "mae": sum(abs(e) for e in err) / len(err),
                      "mae_bench": sum(abs(r["league_avg_total"] - r["goals"]) for r in rows) / len(rows)}
    for lg in sorted({r["league"] for r in rows}):
        sub = [r for r in rows if r["league"] == lg]
        s["by_league"][lg] = {ln: _scores(sub, ln) for ln in C.LINES}
    return s


# ---------------------------------------------------------------- output
def _pct(x):
    return "–" if x is None else f"{x * 100:.1f}%"


def _f(x, d=3):
    return "–" if x is None else f"{x:.{d}f}"


def _signed(x):
    return "–" if x is None else f"{x:+.3f}"


def report(res):
    rows, s = res["rows"], res["summary"]
    n_all = len(rows) + len(res["skipped"])
    L = [f"# Backtest (pre-kick-off, no odds) — {res['window'][0]} to {res['window'][1]}", "",
         f"Generated {res['generated_at']} · Model {C.MODEL_VERSION} · Leagues: {', '.join(res['leagues'])}", "",
         "## Summary", "",
         f"- Finished league matches in window: **{n_all}**",
         f"- Modelled from pre-kick-off data: **{len(rows)}** "
         f"(preferred xG: {sum(r['model_type'] == 'preferred' for r in rows)}, "
         f"fallback: {sum(r['model_type'] == 'fallback' for r in rows)})",
         f"- Not modelled: **{len(res['skipped'])}** (see the last section)", "",
         "How it works: for each match, the model used only league matches that kicked off at least "
         f"{int(FINISH_GAP.total_seconds() // 3600)} hours before it, for both the five-match team samples and "
         "the league averages. Predictions are compared with a **benchmark**: a Poisson model using only "
         "the league's average goals per match at the time, with no team information. A skill score above 0 "
         "means the model beat the benchmark.", "",
         "> **No odds were used.** This measures how accurate the probabilities are, not whether they would have "
         "beaten bookmakers. Edge, ROI and closing-line value need pre-match prices (§27).", ""]
    if len(rows) < 200:
        L += [f"> **Small sample ({len(rows)} matches).** Differences of a few points in Brier score are within "
              "noise at this size. Do not change Version 1 coefficients on this evidence (§27).", ""]
    L += ["## Accuracy by line", "",
          "| Line | Matches | Actual Over rate | Mean model % | Mean benchmark % | Brier (model) | Brier (benchmark) "
          "| Skill | Log loss (model) | Log loss (benchmark) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for ln, x in s["by_line"].items():
        if x:
            L.append(f"| Over {ln} | {x['n']} | {_pct(x['hit_rate'])} | {_pct(x['mean_model'])} | "
                     f"{_pct(x['mean_bench'])} | {_f(x['brier_model'])} | {_f(x['brier_bench'])} | "
                     f"{_signed(x['skill'])} | "
                     f"{_f(x['logloss_model'])} | {_f(x['logloss_bench'])} |")
    L.append("")
    L.append("Lower Brier score and log loss are better. Skill = 1 − Brier(model) / Brier(benchmark).")
    L.append("")
    if "goals" in s:
        g = s["goals"]
        L += ["## Expected vs actual goals", "",
              f"- Mean expected total goals: {g['mean_expected']:.2f} · mean actual: {g['mean_actual']:.2f}",
              f"- Mean absolute error: model {g['mae']:.2f} goals, league-average benchmark {g['mae_bench']:.2f}", ""]
    if s["calibration"]:
        L += ["## Calibration (all lines pooled)", "",
              "| Model probability band | Predictions | Mean predicted | Actual rate |", "|---|---|---|---|"]
        for lo, hi, n, mp, obs in s["calibration"]:
            L.append(f"| {lo * 100:.0f}–{hi * 100:.0f}% | {n} | {_pct(mp)} | {_pct(obs)} |")
        L += ["", "A well-calibrated model has the actual rate close to the mean predicted in each band.", ""]
    if s["by_league"]:
        L += ["## By league", "", "| League | Matches | Brier O1.5 (model/bench) | Brier O2.5 (model/bench) "
              "| Brier O3.5 (model/bench) |", "|---|---|---|---|---|"]
        for lg, d in s["by_league"].items():
            cells = [f"{_f(d[ln]['brier_model'])} / {_f(d[ln]['brier_bench'])}" for ln in C.LINES]
            L.append(f"| {lg} | {d[C.LINES[0]]['n']} | " + " | ".join(cells) + " |")
        L.append("")
    if rows:
        L += ["## Match by match", "",
              "| Kick-off | League | Match | Model | Home Att / DW | Away Att / DW | Exp. goals | O1.5 | O2.5 | O3.5 "
              "| Result |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: (r["kickoff"], r["match"])):
            ps = " | ".join(f"{r['p'][ln] * 100:.1f}% {'✓' if r['y'][ln] else '✗'}" for ln in C.LINES)
            L.append(f"| {r['kickoff'][:16].replace('T', ' ')} | {r['league']} | {r['match']} | {r['model_type']} | "
                     f"{r['home_attack']:.2f} / {r['home_dw']:.2f} | {r['away_attack']:.2f} / {r['away_dw']:.2f} | "
                     f"{r['exp_home']:.2f} + {r['exp_away']:.2f} = {r['exp_total']:.2f} | {ps} | {r['score']} |")
        L += ["", "✓ = the Over happened, ✗ = it did not.", ""]
    if res["skipped"]:
        nf = sum(x["status"] == "needs_fallback_choice" for x in res["skipped"])
        L += ["## Not modelled", "", "| Kick-off | League | Match | Reason |", "|---|---|---|---|"]
        for x in sorted(res["skipped"], key=lambda x: x["kickoff"]):
            if x["status"] == "needs_fallback_choice":
                why = "xG/xGA missing before kick-off; fallback model not approved (§8)"
            else:
                why = "; ".join(sorted({str(m[-1]) for m in x["missing"]}))[:200]
            L.append(f"| {x['kickoff'][:16].replace('T', ' ')} | {x['league']} | {x['label']} | {why} |")
        L.append("")
        if nf:
            L += [f"{nf} match(es) could be scored with the Shots/SOT/Corners fallback model if you approve it "
                  "(`--fallback all` or `--fallback \"<match>\"`).", ""]
    L += ["## Limitations", "",
          "- Team and league statistics are PitchAPI's current values, which may include revisions made after "
          "the match (§28). Results, not stats, decide outcomes, so this cannot change who won a bet.",
          "- Only the current season's league matches are available, so early-season fixtures where a team had "
          "played fewer than five league games cannot be modelled.",
          "- User-supplied league averages are not applied here, because they describe the league today, not "
          "before each match. User-supplied match stats are applied.",
          "- These are fixed Version 1 coefficients that were not fitted to these matches, so this is an "
          "out-of-sample check of Version 1. Re-using these same matches to tune Version 2 would make them in-sample.",
          ""]
    return "\n".join(L)


CSV_FIELDS = ["match_id", "league", "match", "kickoff", "model_type", "exp_home", "exp_away", "exp_total",
              "league_avg_total", "league_matches_before", "home_attack", "home_dw", "away_attack", "away_dw",
              "score", "goals"] + [f"{k}_{ln}" for ln in C.LINES for k in ("p_over", "bench_over", "over")]


def write_csv(res, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in res["rows"]:
            d = {k: r[k] for k in CSV_FIELDS if k in r}
            for k in ("exp_home", "exp_away", "exp_total", "league_avg_total", "home_attack", "home_dw",
                      "away_attack", "away_dw"):
                d[k] = f"{r[k]:.4f}"
            for ln in C.LINES:
                d[f"p_over_{ln}"] = f"{r['p'][ln]:.4f}"
                d[f"bench_over_{ln}"] = f"{r['bench'][ln]:.4f}"
                d[f"over_{ln}"] = r["y"][ln]
            w.writerow(d)
