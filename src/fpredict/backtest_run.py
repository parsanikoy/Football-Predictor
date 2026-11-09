"""Runs a backtest end to end and writes the Markdown report (`fpredict backtest`)."""
import datetime as dt, json

from . import backtest as B
from . import config as C
from . import history as Hst


def parse_seasons(spec):
    """'2018/2019:2025/2026' or '2023/2024,2024/2025'."""
    if ":" in spec:
        a, b = spec.split(":")
        return Hst.seasons_between(a.strip(), b.strip())
    return [s.strip() for s in spec.split(",") if s.strip()]


def load_rows(source, leagues, seasons, log=print):
    rows, notes, join = [], [], None
    for lg in leagues:
        for s in seasons:
            try:
                if source == "footballdata":
                    r = Hst.load_footballdata(lg, s)
                else:
                    r = Hst.load_pitch(lg, s, log=log)
                    try:
                        fd = Hst.load_footballdata(lg, s)
                    except Exception as e:  # odds are optional for the probability metrics
                        fd = []
                        notes.append(f"{lg} {s}: no football-data.co.uk odds ({e})")
                    m, pairs = Hst.join_odds(r, fd)
                    join = (join or (0, 0, []))
                    join = (join[0] + m, join[1] + len(r), join[2] + [(lg,) + p for p in pairs])
            except Exception as e:
                notes.append(f"{lg} {s}: not loaded ({e})")
                continue
            if not r:
                notes.append(f"{lg} {s}: no finished matches")
            log(f"  {lg} {s}: {len(r)} matches")
            rows += r
    return rows, notes, join


def _fmt(x, d=4):
    return "-" if x is None else f"{x:.{d}f}"


def _pct(x, d=1):
    return "-" if x is None else f"{100 * x:+.{d}f}%"


def run(source, leagues, seasons, test_seasons, model=None, max_n=10, carry_over=False, odds_src="avg",
        margin="proportional", min_edge=C.MIN_EDGE_PP, sides=("over",), do_search=True, passes=2, log=print):
    rows, notes, join = load_rows(source, leagues, seasons, log)
    if not rows:
        raise SystemExit("no historical rows loaded")
    model = model or "standard"
    v1 = B.Variant.live(model)   # the live configuration is the baseline every run compares against
    max_n = max(max_n, v1.n)
    snaps = B.snapshots(rows, carry_over=carry_over)
    elig = B.eligible(snaps, max_n, v1.fields())
    elig_v1 = B.eligible(snaps, v1.n, v1.fields())
    cal = [s for s in elig if s["row"]["season"] not in test_seasons]
    test = [s for s in elig if s["row"]["season"] in test_seasons]
    test_v1own = [s for s in elig_v1 if s["row"]["season"] in test_seasons]
    log(f"eligible matches: calibration {len(cal)}, test {len(test)} (of {len(rows)} loaded)")

    best, path = v1, []
    if do_search and cal:
        best, _, path = B.search(B.Evaluator(cal, v1.fields()), v1, max_n, passes=passes, log=log)

    ev_test = B.Evaluator(test, v1.fields())
    pv1, pbest = ev_test.predict(v1), ev_test.predict(best)
    ev_cal = B.Evaluator(cal, v1.fields())
    res = {"source": source, "leagues": leagues, "seasons": seasons, "test_seasons": test_seasons,
           "model": model, "max_n": max_n, "carry_over": carry_over, "odds_src": odds_src, "margin": margin,
           "min_edge": min_edge, "sides": sides, "rows": len(rows), "notes": notes, "join": join,
           "n_cal": len(cal), "n_test": len(test), "n_test_v1own": len(test_v1own),
           "v1": v1, "best": best, "path": path, "searched": do_search and bool(cal)}

    res["cal"] = {"v1": B.mean_logloss(ev_cal.predict(v1)) if cal else None,
                  "best": B.mean_logloss(ev_cal.predict(best)) if cal else None}
    lines = {}
    for ln in C.LINES:
        lines[ln] = {
            "v1": B.prob_metrics([(P[ln], B.outcome(s, ln)) for s, _, P in pv1]),
            "best": B.prob_metrics([(P[ln], B.outcome(s, ln)) for s, _, P in pbest]),
            "naive": B.naive_metrics(test, ln),
            "diff": B.paired_logloss_diff(pbest, pv1, ln),
            "calib_v1": B.calibration_table([(P[ln], B.outcome(s, ln)) for s, _, P in pv1]),
            "calib_best": B.calibration_table([(P[ln], B.outcome(s, ln)) for s, _, P in pbest]),
        }
    res["lines"] = lines
    res["v1_own"] = {ln: B.prob_metrics([(P[ln], B.outcome(s, ln)) for s, _, P in
                                         B.Evaluator(test_v1own, v1.fields()).predict(v1)]) for ln in C.LINES}
    # market benchmarks on the same test matches (2.5 line only: the only line in the history files)
    res["market"] = {(src, m): B.market_metrics(test, src, m)
                     for src in ("avg", "pin", "pin_close", "avg_close") for m in ("proportional", "shin", "power")}
    res["market_n"] = {src: sum(1 for s in test if src in s["row"]["odds"]) for src in ("avg", "pin", "pin_close", "avg_close")}
    res["bets"] = {name: B.bet_metrics(p, odds_src, margin, min_edge, sides) for name, p in (("v1", pv1), ("best", pbest))}
    res["bets_margin"] = {m: B.bet_metrics(pv1, odds_src, m, min_edge, sides) for m in ("proportional", "shin", "power")}
    res["bets_threshold"] = {t: (B.bet_metrics(pv1, odds_src, margin, t, sides), B.bet_metrics(pbest, odds_src, margin, t, sides))
                             for t in (0, 2, 4, 7, 10)}
    by_league = {}
    for lg in leagues:
        a = [(P, s) for s, _, P in pv1 if s["row"]["league"] == lg]
        b = [(P, s) for s, _, P in pbest if s["row"]["league"] == lg]
        if a:
            by_league[lg] = (len(a), B.prob_metrics([(P[2.5], B.outcome(s, 2.5)) for P, s in a])["logloss"],
                             B.prob_metrics([(P[2.5], B.outcome(s, 2.5)) for P, s in b])["logloss"],
                             B.naive_metrics([s for _, s in a], 2.5)["logloss"])
    res["by_league"] = by_league
    return res


def report(res):
    v1, best = res["v1"], res["best"]
    L = []
    w = L.append
    w(f"# Backtest — {res['model']} model ({res['source']})\n")
    w(f"Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
      "Method: docs/BACKTESTING.md. These are category-3 findings (METHODOLOGY §25) only for the TEST seasons; "
      "calibration-season numbers are in-sample.\n")
    w("## Data\n")
    w(f"- Source: {res['source']}; leagues: {', '.join(res['leagues'])}")
    w(f"- Seasons: {res['seasons'][0]} to {res['seasons'][-1]}; **test (held out): {', '.join(res['test_seasons'])}**")
    w(f"- Matches loaded: {res['rows']}. Eligible (both teams ≥ {res['max_n']} previous league matches "
      f"{'incl. previous seasons' if res['carry_over'] else 'this season'}, every input present): "
      f"calibration {res['n_cal']}, test {res['n_test']}")
    w(f"- Every variant is scored on the same matches. Live model alone on its own eligibility (≥ {v1.n} matches): "
      f"{res['n_test_v1own']} test matches.")
    if res["join"]:
        m, n, pairs = res["join"]
        w(f"- Odds joined from football-data.co.uk onto PitchAPI matches: {m} of {n}. "
          f"Non-identical name pairs used: {len(pairs)} (check: {', '.join(f'{a}={b}' for _, a, b in pairs[:15])}{' …' if len(pairs) > 15 else ''})")
    for nte in res["notes"]:
        w(f"- Note: {nte}")
    w("")
    w("## Variants\n")
    w(f"- **Live**: {v1.describe()}")
    if res["searched"]:
        w(f"- **Best on calibration seasons**: {best.describe()}")
    else:
        w("- No search was run (no calibration seasons, or --no-search); 'best' below is Live.")
    if res["searched"]:
        w(f"- Calibration mean log loss (3 lines): Live {_fmt(res['cal']['v1'], 5)} → best {_fmt(res['cal']['best'], 5)}\n")
        w("Search path (coordinate descent on calibration seasons only):\n")
        w("| step | mean log loss |\n|---|---|")
        for name, _, sc in res["path"]:
            w(f"| {name} | {sc:.5f} |")
    w("")
    w("## Test seasons: probability accuracy\n")
    w("Lower is better. 'League rate' predicts each league's over-rate so far this season. "
      "Δ = best − Live paired log loss with standard error; |Δ| < 2·SE is not a reliable difference.\n")
    w("| line | n | Live Brier | Live log loss | best Brier | best log loss | league-rate log loss | Δ log loss (SE) | mean forecast Live / best | observed |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for ln, d in res["lines"].items():
        a, b, nv = d["v1"], d["best"], d["naive"]
        if not a:
            continue
        df = d["diff"]
        w(f"| O{ln} | {a['n']} | {a['brier']:.4f} | {a['logloss']:.4f} | {b['brier']:.4f} | {b['logloss']:.4f} | "
          f"{nv['logloss']:.4f} | {'-' if not df else f'{df[0]:+.4f} ({df[1]:.4f})'} | "
          f"{a['mean_p']:.3f} / {b['mean_p']:.3f} | {a['rate']:.3f} |")
    w("")
    w(f"Live model on its own eligibility (≥ {v1.n} matches): " + "; ".join(
        f"O{ln} log loss {d['logloss']:.4f} (n={d['n']})" for ln, d in res["v1_own"].items() if d))
    w("")
    w("### Market benchmark, Over 2.5 (same test matches)\n")
    w("Margin removed three ways (Štrumbelj 2014). If the market's log loss is lower than the model's, the model "
      "has no information the price lacks.\n")
    w("| odds | n | proportional | Shin | power |\n|---|---|---|---|---|")
    for src in ("avg", "pin", "pin_close", "avg_close"):
        if res["market_n"][src]:
            w(f"| {src} | {res['market_n'][src]} | " + " | ".join(
                _fmt(res["market"][(src, m)]["logloss"]) for m in ("proportional", "shin", "power")) + " |")
    w("")
    w("### Calibration, Over 2.5 (test)\n")
    w("| forecast bin | Live n | Live mean forecast | Live observed | best n | best mean forecast | best observed |")
    w("|---|---|---|---|---|---|---|")
    cv = {(r[0], r[1]): r for r in res["lines"][2.5]["calib_v1"]}
    cb = {(r[0], r[1]): r for r in res["lines"][2.5]["calib_best"]}
    for k in sorted(set(cv) | set(cb)):
        a, b = cv.get(k), cb.get(k)
        w(f"| {k[0]:.1f}–{k[1]:.1f} | {a[2] if a else 0} | {_fmt(a and a[3], 3)} | {_fmt(a and a[4], 3)} | "
          f"{b[2] if b else 0} | {_fmt(b and b[3], 3)} | {_fmt(b and b[4], 3)} |")
    w("")
    w("### Over 2.5 log loss by league (test)\n")
    w("| league | n | Live | best | league rate |\n|---|---|---|---|---|")
    for lg, (n, a, b, nv) in res["by_league"].items():
        w(f"| {lg} | {n} | {a:.4f} | {b:.4f} | {nv:.4f} |")
    w("")
    w("## Test seasons: betting simulation, Over/Under 2.5\n")
    w(f"Flat 1-unit stakes at **{res['odds_src']}** pre-match odds; edge vs {res['margin']} margin-free probability; "
      f"qualifying edge ≥ {res['min_edge']}pp; sides: {', '.join(res['sides'])}; at most one bet per match. "
      "CLV = expected value of the bet at the margin-free Pinnacle closing price (positive = beat the close). "
      "ROI ± 2·SE spanning 0 means the result is consistent with no edge.\n")

    def bet_row(label, b):
        if not b.get("n"):
            return f"| {label} | 0 | - | - | - | - | - | - |"
        se = b["roi_se"]
        return (f"| {label} | {b['n']} | {b['profit']:+.1f} | {_pct(b['roi'])} ± {_pct(2 * se) if se else '-'} | "
                f"{100 * b['hit']:.1f}% | {b['avg_price']:.2f} | {b['max_drawdown']:.1f} | "
                f"{_pct(b['clv'], 2) if b['clv'] is not None else '-'} |")
    hdr = "| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |\n|---|---|---|---|---|---|---|---|"
    w(hdr)
    w(bet_row("Live", res["bets"]["v1"]))
    w(bet_row("best", res["bets"]["best"]))
    w("\nLive by qualifying edge threshold (the 4pp rule is an untested assumption):\n")
    w(hdr)
    for t, (a, b) in res["bets_threshold"].items():
        w(bet_row(f"Live ≥{t}pp", a))
        w(bet_row(f"best ≥{t}pp", b))
    w("\nLive by margin-removal method:\n")
    w(hdr)
    for m, b in res["bets_margin"].items():
        w(bet_row(m, b))
    for name in ("v1", "best"):
        b = res["bets"][name]
        if b.get("bands"):
            w(f"\n{'Live' if name == 'v1' else 'Best'} by edge band: " + "; ".join(
                f"{k}: {n} bets, ROI {_pct(r)}" for k, (n, r) in b["bands"].items()))
            w(f"{'Live' if name == 'v1' else 'Best'} by league: " + "; ".join(
                f"{k}: {n} bets, ROI {_pct(r)}" for k, (n, r) in b["leagues"].items()))
    w("")
    w("## Reading this report\n")
    w("- The search tried many variants on the calibration seasons, so its calibration score is optimistic. "
      "Only the test-season columns estimate real performance, and even those are one sample.")
    w("- Small differences in log loss (a few thousandths) are typical between reasonable models; check Δ against its SE.")
    w("- Betting ROI is far noisier than log loss. A few hundred bets cannot distinguish a 2% edge from zero.")
    w("- Historical odds are football-data.co.uk market averages/maximums and Pinnacle prices, not the UK books "
      "the live model compares against; only the 2.5 line is available.")
    w("- Do not change config.py from this report without the user's agreement; record any change in METHODOLOGY.md (§27).")
    return "\n".join(L) + "\n"


def best_json(res):
    return json.dumps({"model": res["model"], "source": res["source"], "leagues": res["leagues"],
                       "calibration_seasons": [s for s in res["seasons"] if s not in res["test_seasons"]],
                       "test_seasons": res["test_seasons"], "variant": res["best"].as_dict()}, indent=2)
