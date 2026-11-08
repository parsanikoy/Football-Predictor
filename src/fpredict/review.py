"""Weekly model review (docs/METHODOLOGY.md §27a).

1. LEARN: add newly finished matches, with their pre-kick-off inputs, to data/backtest_store.jsonl.
2. BACKTEST: re-run the model on every stored match with Version 1 and with each of a fixed,
   pre-declared list of alternative settings (VARIANTS).
3. SUGGEST: report a change only when it beats Version 1 on BOTH the older (calibration) and newer
   (test) part of the data, the test improvement is significant after correcting for the number of
   alternatives tried, there is enough data, and it passed at the previous review too.

It never changes src/fpredict/config.py. Adopting a suggestion needs the user's agreement and a
METHODOLOGY.md update.
"""
import csv
import json
import math
import pathlib
import statistics as st

from . import config as C
from . import model as M

ROOT = pathlib.Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "backtest_store.jsonl"
HISTORY = ROOT / "data" / "review_history.csv"

TEST_SHARE = 0.40          # newest 40% of stored matches (by kick-off) form the test set
MIN_TOTAL = 600            # stored matches needed before any change can be suggested
MIN_TEST = 250             # test-set matches needed (per variant) before any change can be suggested
FAMILY_ALPHA = 0.05        # overall false-alarm rate across all variants (Bonferroni-corrected)


def decay(n, d=0.85):
    w = [d ** i for i in range(n)]
    return tuple(x / sum(w) for x in w)


V1 = {"attack": dict(C.PREFERRED_ATTACK), "recency": tuple(C.RECENCY_WEIGHTS), "shrink": C.SHRINK_MODEL,
      "score_cap": (C.SCORE_MIN, C.SCORE_MAX)}


def variant(**kw):
    return dict(V1, **kw)


# Pre-declared: add to this list deliberately (and say so in the review), never in response to one week's results.
VARIANTS = {
    "V1 (current)": V1,
    "Shrinkage: 50% model / 50% league": variant(shrink=0.50),
    "Shrinkage: 62.5% model": variant(shrink=0.625),
    "Shrinkage: 87.5% model": variant(shrink=0.875),
    "Shrinkage: none (100% model)": variant(shrink=1.0),
    "Inputs: no xG (SOT 45 / shots 35 / corners 20)": variant(attack=dict(C.FALLBACK_ATTACK)),
    "Inputs: xG-heavy (70/15/10/5)": variant(attack={"xg": .70, "sot": .15, "shots": .10, "corners": .05}),
    "Inputs: xG only": variant(attack={"xg": 1.0}),
    "Inputs: equal weights (25/25/25/25)": variant(attack={"xg": .25, "sot": .25, "shots": .25, "corners": .25}),
    "Recency: flat (20% each)": variant(recency=(0.2,) * 5),
    "Recency: steeper (40/25/17.5/10/7.5)": variant(recency=(0.40, 0.25, 0.175, 0.10, 0.075)),
    "Sample: 8 matches, decaying weights": variant(recency=decay(8)),
    "Sample: 10 matches, decaying weights": variant(recency=decay(10)),
    "Score limits: wider (0.50-2.00)": variant(score_cap=(0.50, 2.00)),
}


# ---------------------------------------------------------------- store
def load_store(path=STORE):
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    return {r["match_id"]: r for r in map(json.loads, p.read_text().splitlines()) if r}


def update_store(rows, path=STORE):
    """Upsert backtest rows (with 'inputs'). Returns (added, updated)."""
    store = load_store(path)
    added = sum(r["match_id"] not in store for r in rows)
    for r in rows:
        store[r["match_id"]] = {k: r[k] for k in ("match_id", "league", "match", "kickoff", "score", "goals", "inputs")}
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                         for r in sorted(store.values(), key=lambda r: (r["kickoff"], r["match_id"]))))
    return added, len(rows) - added


# ---------------------------------------------------------------- parameterised model
def _score(sample, base, P, conc):
    n = len(P["recency"])
    total = 0.0
    for f, k in P["attack"].items():
        key = ("conc_" + f) if conc else f
        vals = [m.get(key) for m in sample[:n]]
        if len(vals) < n or any(v is None for v in vals) or not base.get(f):
            return None
        total += k * sum(w * v for w, v in zip(P["recency"], vals)) / base[f]
    return M.cap(total, *P["score_cap"])[0]


def predict(inputs, P):
    """Same steps as model.team_scores/expected_goals/poisson_overs, with settings P.
    Returns {"total": λ, "p": {line: prob}} or None if the inputs don't support P."""
    b = inputs["baseline"]
    if not b.get("home_goals") or not b.get("away_goals"):
        return None
    s = [_score(inputs[side], b, P, conc) for side in ("home", "away") for conc in (False, True)]
    if None in s:
        return None
    h_att, h_dw, a_att, a_dw = s
    hg, ag = b["home_goals"], b["away_goals"]
    home = M.cap(P["shrink"] * hg * h_att * a_dw + (1 - P["shrink"]) * hg, C.HOME_XG_MIN, C.HOME_XG_MAX)[0]
    away = M.cap(P["shrink"] * ag * a_att * h_dw + (1 - P["shrink"]) * ag, C.AWAY_XG_MIN, C.AWAY_XG_MAX)[0]
    total = M.cap(home + away, C.TOTAL_MIN, C.TOTAL_MAX)[0]
    return {"total": total, "p": M.poisson_overs(total)}


def match_brier(pred, goals):
    return sum((pred["p"][ln] - (goals > ln)) ** 2 for ln in C.LINES) / len(C.LINES)


def match_logloss(pred, goals):
    eps = 1e-12
    out = 0.0
    for ln in C.LINES:
        p = min(max(pred["p"][ln], eps), 1 - eps)
        out -= math.log(p) if goals > ln else math.log(1 - p)
    return out / len(C.LINES)


# ---------------------------------------------------------------- evaluation
def _z(two_sided_alpha):
    """Normal quantile for 1 - alpha/2 (bisection on erf; stdlib only)."""
    target = 1 - two_sided_alpha / 2
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _mean_ci(d, z):
    if len(d) < 2:
        return (st.mean(d) if d else None), None, None
    m, se = st.mean(d), st.stdev(d) / math.sqrt(len(d))
    return m, m - z * se, m + z * se


def evaluate(store, variants=VARIANTS):
    matches = sorted(store.values(), key=lambda r: (r["kickoff"], r["match_id"]))
    n_test = int(round(len(matches) * TEST_SHARE))
    split = len(matches) - n_test
    cut = matches[split]["kickoff"] if n_test else None
    preds = {name: [predict(r["inputs"], P) for r in matches] for name, P in variants.items()}
    base = preds["V1 (current)"]
    alts = [n for n in variants if n != "V1 (current)"]
    z = _z(FAMILY_ALPHA / max(len(alts), 1))
    enough_total = len(matches) >= MIN_TOTAL
    out = []
    for name in alts:
        res = {"variant": name}
        for part, idx in (("cal", range(0, split)), ("test", range(split, len(matches)))):
            ids = [i for i in idx if base[i] and preds[name][i]]
            g = [matches[i]["goals"] for i in ids]
            db = [match_brier(base[i], gi) - match_brier(preds[name][i], gi) for i, gi in zip(ids, g)]
            dl = [match_logloss(base[i], gi) - match_logloss(preds[name][i], gi) for i, gi in zip(ids, g)]
            m, lo, hi = _mean_ci(db, z)
            res[part] = {"n": len(ids), "brier_gain": m, "lo": lo, "hi": hi,
                         "logloss_gain": st.mean(dl) if dl else None}
        t, c = res["test"], res["cal"]
        enough = enough_total and t["n"] >= MIN_TEST
        res["enough_data"] = enough
        res["passed"] = bool(enough and c["brier_gain"] is not None and c["brier_gain"] > 0 and t["lo"] is not None
                             and t["lo"] > 0 and (t["logloss_gain"] or 0) > 0)
        out.append(res)
    # Version 1 calibration over all stored matches
    v1 = [(p, r["goals"]) for p, r in zip(base, matches) if p]
    cal = None
    if v1:
        bias = [p["total"] - g for p, g in v1]
        m, lo, hi = _mean_ci(bias, _z(0.05))
        cal = {"n": len(v1), "mean_pred": st.mean(p["total"] for p, _ in v1), "mean_goals": st.mean(g for _, g in v1),
               "bias": m, "bias_lo": lo, "bias_hi": hi,
               "brier": st.mean(match_brier(p, g) for p, g in v1)}
    return {"n_total": len(matches), "n_cal": split, "n_test": n_test, "test_from": cut,
            "first": matches[0]["kickoff"] if matches else None, "last": matches[-1]["kickoff"] if matches else None,
            "z": z, "results": out, "v1": cal, "enough_total": enough_total}


# ---------------------------------------------------------------- history and status
HIST_FIELDS = ["review_date", "n_total", "n_test", "variant", "cal_gain", "test_gain", "test_lo", "test_hi",
               "enough_data", "passed"]


def load_history(path=HISTORY):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def apply_history(ev, review_date, path=HISTORY):
    """Mark each result's status using the previous review, then record this review (replacing any
    earlier record from the same date)."""
    hist = [h for h in load_history(path) if h["review_date"] != review_date]
    prev_dates = sorted({h["review_date"] for h in hist})
    prev = {h["variant"]: h["passed"] == "True" for h in hist if prev_dates and h["review_date"] == prev_dates[-1]}
    for r in ev["results"]:
        if r["passed"] and prev.get(r["variant"]):
            r["status"] = "SUGGESTED (passed this review and the previous one)"
        elif r["passed"]:
            r["status"] = "Passed once: needs to pass again at the next review"
        elif not r["enough_data"] and (r["test"]["brier_gain"] or 0) > 0 and (r["cal"]["brier_gain"] or 0) > 0:
            r["status"] = "Better on both parts so far, but not enough data to judge"
        elif (r["test"]["brier_gain"] or 0) > 0:
            r["status"] = "Not significant"
        else:
            r["status"] = "No improvement"
    f6 = lambda x: "" if x is None else f"{x:.6f}"
    for r in ev["results"]:
        hist.append({"review_date": review_date, "n_total": ev["n_total"], "n_test": r["test"]["n"],
                     "variant": r["variant"], "cal_gain": f6(r["cal"]["brier_gain"]),
                     "test_gain": f6(r["test"]["brier_gain"]), "test_lo": f6(r["test"]["lo"]),
                     "test_hi": f6(r["test"]["hi"]), "enough_data": r["enough_data"], "passed": r["passed"]})
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        w.writeheader()
        w.writerows(hist)
    return ev


# ---------------------------------------------------------------- report
def _g(x):
    return "–" if x is None else f"{x * 1000:+.2f}"


def report(ev, review_date, added=0, updated=0, window=None):
    L = [f"# Weekly model review — {review_date}", "",
         "This review re-runs the model on every stored match using only pre-kick-off data, with Version 1 and "
         "with each pre-declared alternative. It **suggests**; it never changes the model. Adopting a change "
         "needs your agreement and a METHODOLOGY.md update (§27a).", "",
         "## Data", ""]
    if window:
        L.append(f"- This review fetched finished matches from {window[0]} to {window[1]}: "
                 f"{added} new, {updated} refreshed.")
    L += [f"- Stored matches: **{ev['n_total']}** ({(ev['first'] or '')[:10]} to {(ev['last'] or '')[:10]})",
          f"- Calibration (older) set: {ev['n_cal']} · Test (newer) set: {ev['n_test']}"
          + (f", from {ev['test_from'][:10]}" if ev["test_from"] else ""),
          f"- A change can only be suggested once there are ≥{MIN_TOTAL} stored matches and ≥{MIN_TEST} test "
          f"matches. **{'Met' if ev['enough_total'] else 'Not yet met'}.**", ""]
    v = ev["v1"]
    if v:
        L += ["## Version 1 health check", "",
              f"- Average predicted goals {v['mean_pred']:.2f} vs actual {v['mean_goals']:.2f} "
              f"(bias {v['bias']:+.2f}, 95% range {v['bias_lo']:+.2f} to {v['bias_hi']:+.2f})",
              f"- Average Brier score across the three lines: {v['brier']:.4f}",
              "- " + ("The bias range includes zero: no evidence of systematic over- or under-prediction."
                      if v["bias_lo"] <= 0 <= v["bias_hi"] else
                      "The bias range excludes zero: Version 1 is systematically "
                      + ("over" if v["bias"] > 0 else "under") + "-predicting goals. Worth watching across reviews."), ""]
    L += ["## Alternatives vs Version 1", "",
          "Gain = how much lower (better) the alternative's average Brier score is than Version 1's, ×1000. "
          "Positive means the alternative did better. The test range is corrected for the "
          f"{len(ev['results'])} alternatives tried (z = {ev['z']:.2f}).", "",
          "| Alternative | Gain, calibration set | Gain, test set | Test range | Log-loss gain, test | Status |",
          "|---|---|---|---|---|---|"]
    for r in sorted(ev["results"], key=lambda r: -(r["test"]["brier_gain"] or -9)):
        c, t = r["cal"], r["test"]
        rng = "–" if t["lo"] is None else f"{_g(t['lo'])} to {_g(t['hi'])}"
        ll = "–" if t["logloss_gain"] is None else f"{t['logloss_gain'] * 1000:+.2f}"
        L.append(f"| {r['variant']} | {_g(c['brier_gain'])} (n={c['n']}) | {_g(t['brier_gain'])} (n={t['n']}) | "
                 f"{rng} | {ll} | {r['status']} |")
    sug = [r for r in ev["results"] if r["status"].startswith("SUGGESTED")]
    L += ["", "## Suggestion", ""]
    if sug:
        for r in sug:
            L.append(f"- **{r['variant']}** has beaten Version 1 at two consecutive reviews on both the calibration "
                     "and the test set. If you agree, adopt it as a new model version and record it in METHODOLOGY.md. "
                     "From then on, only matches after the change count as a fresh test of the new version.")
    else:
        L.append("- **No change suggested.** " + (
            "There is not yet enough data to tell the alternatives apart reliably; the gains above are directional only."
            if not ev["enough_total"] else
            "No alternative has passed every check at two consecutive reviews."))
    L += ["", "## Rules (pre-declared)", "",
          f"- The alternatives list is fixed in `src/fpredict/review.py`. Adding one is a deliberate decision, "
          "not a reaction to one week.",
          f"- Data is split by kick-off date: the newest {int(TEST_SHARE * 100)}% is the test set.",
          "- An alternative passes a review only if it is better on the calibration set, better on the test set with the "
          "corrected range entirely above zero, better on test log loss, and there is enough data.",
          "- It is suggested only after passing at two consecutive reviews.",
          "- The test set grows every week and is reused, so a pass is strong evidence, not proof. After a change is adopted, "
          "judge it on matches played after the change.", ""]
    return "\n".join(L)
