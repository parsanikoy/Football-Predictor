"""Backtest harness (docs/METHODOLOGY.md §27, docs/BACKTESTING.md).

Replays the Version 1 model point-in-time over historical seasons with every coefficient exposed as a
parameter, so alternative inputs, weightings and distributions can be compared:

  snapshots()  - for each historical match, what the live model could have known before kick-off:
                 each team's previous league matches (most recent first) and the league averages so far.
  Variant      - one complete parameter set. Variant.v1() reproduces src/fpredict/model.py exactly.
  evaluate()   - probabilities for every eligible match; prob_metrics() / bet_metrics() score them.
  search()     - coordinate search over weights, recency, shrinkage, caps and distribution, run on the
                 CALIBRATION seasons only. The chosen variant is then scored once on the held-out TEST
                 seasons (never optimise on data later used to claim out-of-sample performance).

Pure functions apart from report writing; no network access here (see history.py).
"""
import dataclasses, datetime as dt, itertools, math, statistics
from . import config as C

FIELDS = ("xg", "shots", "sot", "corners")
EPS = 1e-6


# ---------------------------------------------------------------- variants
@dataclasses.dataclass(frozen=True)
class Variant:
    model: str = "preferred"                      # 'preferred' (needs xG) or 'fallback'
    weights: tuple = tuple(C.PREFERRED_ATTACK.items())   # ((field, weight), ...) same for attack & defence
    recency: tuple = C.RECENCY_WEIGHTS            # most recent first; its length is the sample size
    shrink: float = C.SHRINK_MODEL                # weight on the model; 1 - shrink on the league average
    caps: bool = True                             # V1 score / xG / total caps
    dist: str = "poisson"                         # 'poisson' | 'dc' (Dixon-Coles, rho) | 'negbin' (size k)
    dist_param: float = 0.0
    recency_label: str = "V1 30/25/20/15/10"

    @classmethod
    def v1(cls, model="preferred"):
        w = C.PREFERRED_ATTACK if model == "preferred" else C.FALLBACK_ATTACK
        return cls(model=model, weights=tuple(w.items()))

    @property
    def n(self):
        return len(self.recency)

    def fields(self):
        return tuple(f for f, _ in self.weights)

    def describe(self):
        w = " / ".join(f"{f} {k:.2f}" for f, k in self.weights)
        d = {"poisson": "Poisson", "dc": f"Dixon-Coles rho={self.dist_param:+.2f}",
             "negbin": f"Negative binomial k={self.dist_param:g}"}[self.dist]
        return (f"{self.model}; weights {w}; last {self.n} matches ({self.recency_label}); "
                f"shrink {self.shrink:.2f}/{1 - self.shrink:.2f}; caps {'on' if self.caps else 'off'}; {d}")

    def as_dict(self):
        d = dataclasses.asdict(self)
        d["weights"] = dict(self.weights)
        return d


def recency_weights(n, kind, half_life=None):
    """-> (weights most-recent-first summing to 1, label)."""
    if kind == "v1":
        return C.RECENCY_WEIGHTS, "V1 30/25/20/15/10"
    if kind == "equal":
        w = [1.0] * n
    elif kind == "linear":
        w = [float(n - i) for i in range(n)]
    elif kind == "exp":
        w = [0.5 ** (i / half_life) for i in range(n)]
    else:
        raise ValueError(kind)
    s = sum(w)
    label = f"half-life {half_life:g} matches" if kind == "exp" else {"equal": "equal", "linear": "linear decay"}[kind]
    return tuple(x / s for x in w), label


# ---------------------------------------------------------------- point-in-time snapshots
def snapshots(rows, carry_over=False):
    """rows from history.py (any leagues/seasons). Returns chronological snapshots:
    {'row', 'home': [records most recent first], 'away': [...], 'base': league averages so far}.
    Only matches on EARLIER dates feed a snapshot (same-day matches are never used).
    Team history resets each season unless carry_over (V1 uses current-season matches only);
    league averages always reset each season, as in V1."""
    out = []
    leagues = {}
    for r in rows:
        leagues.setdefault(r["league"], []).append(r)
    for lg, lrows in leagues.items():
        lrows.sort(key=lambda r: (r["season"], r["date"], r["time"] or ""))
        hist, season, sums = {}, None, None
        for (s, d), grp in itertools.groupby(lrows, key=lambda r: (r["season"], r["date"])):
            grp = list(grp)
            if s != season:
                season = s
                sums = {"n": 0, "hg": 0, "ag": 0, "over": {ln: 0 for ln in C.LINES},
                        **{f: [0.0, 0] for f in FIELDS}}
                if not carry_over:
                    hist = {}
            base = None
            if sums["n"]:
                base = {f: (sums[f][0] / sums[f][1] if sums[f][1] else None) for f in FIELDS}
                base.update(home_goals=sums["hg"] / sums["n"], away_goals=sums["ag"] / sums["n"],
                            over_rate={ln: sums["over"][ln] / sums["n"] for ln in C.LINES}, n=sums["n"])
            for r in grp:
                out.append({"row": r, "home": hist.get(r["home"], [])[::-1], "away": hist.get(r["away"], [])[::-1],
                            "base": base})
            for r in grp:
                st = r["stats"]
                for side, other, team in (("home", "away", r["home"]), ("away", "home", r["away"])):
                    rec = {}
                    for f in FIELDS:
                        rec[f] = st[side].get(f)
                        rec["conc_" + f] = st[other].get(f)
                    hist.setdefault(team, []).append(rec)
                for f in FIELDS:
                    for side in ("home", "away"):
                        v = st[side].get(f)
                        if v is not None:
                            sums[f][0] += v
                            sums[f][1] += 1
                sums["n"] += 1
                sums["hg"] += r["hg"]
                sums["ag"] += r["ag"]
                for ln in C.LINES:
                    sums["over"][ln] += (r["hg"] + r["ag"]) > ln
    out.sort(key=lambda s: (s["row"]["date"], s["row"]["time"] or "", s["row"]["league"]))
    return out


def eligible(snaps, n, fields):
    """Snapshots where both teams have >= n previous matches with every needed field present, and
    the league baseline has every needed field. Every variant in a comparison is scored on the same set."""
    out = []
    for s in snaps:
        b = s["base"]
        if not b or any(b.get(f) in (None, 0) for f in fields):
            continue
        ok = True
        for side in ("home", "away"):
            recs = s[side][:n]
            if len(recs) < n or any(rec[k] is None for rec in recs for f in fields for k in (f, "conc_" + f)):
                ok = False
                break
        if ok:
            out.append(s)
    return out


# ---------------------------------------------------------------- probability model
def _cap(x, lo, hi):
    return min(max(x, lo), hi)


def _ratios(snap, recency, fields):
    """Weighted metric / league average for each field: {'home': {f: r, 'conc_f': r}, 'away': ...}."""
    out = {}
    for side in ("home", "away"):
        recs = snap[side][:len(recency)]
        d = {}
        for f in fields:
            for k in (f, "conc_" + f):
                d[k] = sum(w * rec[k] for w, rec in zip(recency, recs)) / snap["base"][f]
        out[side] = d
    return out


def expected(ratios, base, v):
    """-> (home, away, total) expected goals, following METHODOLOGY §7-§13 with v's parameters."""
    def score(side, prefix):
        x = sum(k * ratios[side][prefix + f] for f, k in v.weights)
        return _cap(x, C.SCORE_MIN, C.SCORE_MAX) if v.caps else x
    ha, hd, aa, ad = score("home", ""), score("home", "conc_"), score("away", ""), score("away", "conc_")
    hg, ag = base["home_goals"], base["away_goals"]
    h = v.shrink * hg * ha * ad + (1 - v.shrink) * hg
    a = v.shrink * ag * aa * hd + (1 - v.shrink) * ag
    if v.caps:
        h, a = _cap(h, C.HOME_XG_MIN, C.HOME_XG_MAX), _cap(a, C.AWAY_XG_MIN, C.AWAY_XG_MAX)
        t = _cap(h + a, C.TOTAL_MIN, C.TOTAL_MAX)
        if t != h + a:  # keep home/away consistent with a capped total (matters for Dixon-Coles only)
            h, a = h * t / (h + a), a * t / (h + a)
    return h, a, h + a


def _pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def over_probs(h, a, dist="poisson", param=0.0):
    """P(total > line) for each line in C.LINES."""
    lam = h + a
    if dist == "poisson":
        cdf = list(itertools.accumulate(_pois(lam, k) for k in range(4)))
    elif dist == "negbin":
        k = param
        p = k / (k + lam)
        pmf = [math.exp(math.lgamma(x + k) - math.lgamma(k) - math.lgamma(x + 1) + k * math.log(p)
                        + x * math.log(1 - p)) for x in range(4)]
        cdf = list(itertools.accumulate(pmf))
    elif dist == "dc":
        rho = param
        tau = {(0, 0): 1 - h * a * rho, (0, 1): 1 + h * rho, (1, 0): 1 + a * rho, (1, 1): 1 - rho}
        cell = [0.0] * 4
        for i in range(4):
            for j in range(4 - i):
                cell[i + j] += max(tau.get((i, j), 1.0), 0.0) * _pois(h, i) * _pois(a, j)
        cdf = list(itertools.accumulate(cell))
    else:
        raise ValueError(dist)
    return {ln: min(max(1 - cdf[int(ln)], EPS), 1 - EPS) for ln in C.LINES}


class Evaluator:
    """Caches league-relative ratios per recency vector so that weight/shrink/distribution searches are fast."""

    def __init__(self, snaps, fields):
        self.snaps, self.fields, self._cache = snaps, fields, {}

    def ratios(self, recency):
        if recency not in self._cache:
            self._cache[recency] = [_ratios(s, recency, self.fields) for s in self.snaps]
        return self._cache[recency]

    def predict(self, v):
        """-> list of (snap, (home, away, total), {line: P(over)})."""
        out = []
        for s, r in zip(self.snaps, self.ratios(v.recency)):
            h, a, t = expected(r, s["base"], v)
            out.append((s, (h, a, t), over_probs(h, a, v.dist, v.dist_param)))
        return out


# ---------------------------------------------------------------- scoring
def outcome(snap, ln):
    r = snap["row"]
    return 1 if r["hg"] + r["ag"] > ln else 0


def prob_metrics(pairs):
    """pairs: [(p, y)] -> Brier, log loss, mean forecast, observed rate, n."""
    n = len(pairs)
    if not n:
        return None
    br = sum((p - y) ** 2 for p, y in pairs) / n
    ll = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in pairs) / n
    return {"n": n, "brier": br, "logloss": ll, "mean_p": sum(p for p, _ in pairs) / n,
            "rate": sum(y for _, y in pairs) / n}


def calibration_table(pairs, bins=10):
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1)]
        if sel:
            rows.append((lo, hi, len(sel), sum(p for p, _ in sel) / len(sel), sum(y for _, y in sel) / len(sel)))
    return rows


def mean_logloss(preds):
    """Objective used for model selection: log loss averaged over the three lines (Walsh & Joshi 2024:
    select on calibration-sensitive scores, not hit rate)."""
    tot = 0.0
    for s, _, P in preds:
        for ln in C.LINES:
            y = outcome(s, ln)
            tot -= math.log(P[ln]) if y else math.log(1 - P[ln])
    return tot / (len(preds) * len(C.LINES)) if preds else float("inf")


def paired_logloss_diff(preds_a, preds_b, ln):
    """Mean and standard error of logloss(a) - logloss(b) on the same matches (negative = a better)."""
    d = []
    for (s, _, Pa), (_, _, Pb) in zip(preds_a, preds_b):
        y = outcome(s, ln)
        la = -math.log(Pa[ln]) if y else -math.log(1 - Pa[ln])
        lb = -math.log(Pb[ln]) if y else -math.log(1 - Pb[ln])
        d.append(la - lb)
    if len(d) < 2:
        return None
    return statistics.fmean(d), statistics.stdev(d) / math.sqrt(len(d))


# ---------------------------------------------------------------- bookmaker margin & betting
def fair_over(over, under, method="proportional"):
    """Margin-free P(Over) from a two-way Over/Under price pair."""
    a, b = 1 / over, 1 / under
    s = a + b
    if method == "proportional" or s <= 1:
        return a / s
    if method == "power":            # p_i = a_i ** k with k chosen so they sum to 1
        lo, hi = 1.0, 10.0
        for _ in range(60):
            k = (lo + hi) / 2
            lo, hi = (k, hi) if a ** k + b ** k > 1 else (lo, k)
        return a ** ((lo + hi) / 2)
    if method == "shin":             # Shin (1993); see Štrumbelj (2014)
        def ps(z):
            return [(math.sqrt(z * z + 4 * (1 - z) * x * x / s) - z) / (2 * (1 - z)) for x in (a, b)]
        lo, hi = 0.0, 0.5
        for _ in range(60):
            z = (lo + hi) / 2
            lo, hi = (z, hi) if sum(ps(z)) > 1 else (lo, z)
        po, pu = ps((lo + hi) / 2)
        return po / (po + pu)
    raise ValueError(method)


def bet_metrics(preds, odds_src="avg", margin="proportional", min_edge=C.MIN_EDGE_PP, sides=("over",),
                close_src="pin_close", line=2.5):
    """Flat 1-unit stakes on every selection whose model edge >= min_edge (pp), at most one per match
    (largest edge), in kick-off order. V1 only recommends Overs; pass sides=('over','under') to test both."""
    bets = []
    for s, _, P in preds:
        od = s["row"]["odds"].get(odds_src)
        if not od:
            continue
        po = fair_over(*od, method=margin)
        cands = []
        if "over" in sides:
            cands.append(((P[line] - po) * 100, "over", od[0]))
        if "under" in sides:
            cands.append(((po - P[line]) * 100, "under", od[1]))
        e, side, price = max(cands)
        if e < min_edge:
            continue
        win = outcome(s, line) == (1 if side == "over" else 0)
        b = {"date": s["row"]["date"], "league": s["row"]["league"], "edge": e, "side": side, "price": price,
             "profit": price - 1 if win else -1.0, "win": win, "clv": None}
        cl = s["row"]["odds"].get(close_src)
        if cl:
            pc = fair_over(*cl, method=margin)
            b["clv"] = price * (pc if side == "over" else 1 - pc) - 1   # EV of the bet at the fair closing price
        bets.append(b)
    return summarise_bets(bets)


def summarise_bets(bets):
    n = len(bets)
    out = {"n": n}
    if not n:
        return out
    profits = [b["profit"] for b in bets]
    cum = peak = dd = 0.0
    for p in profits:
        cum += p
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    clv = [b["clv"] for b in bets if b["clv"] is not None]
    out.update(profit=sum(profits), roi=sum(profits) / n, roi_se=(statistics.stdev(profits) / math.sqrt(n)) if n > 1 else None,
               hit=sum(b["win"] for b in bets) / n, avg_price=statistics.fmean(b["price"] for b in bets),
               max_drawdown=dd, clv=statistics.fmean(clv) if clv else None, clv_n=len(clv),
               overs=sum(b["side"] == "over" for b in bets))
    bands = {}
    for lo, hi in ((4, 7), (7, 10), (10, 1e9)):
        sel = [b for b in bets if lo <= b["edge"] < hi]
        if sel:
            bands[f"{lo}-{hi if hi < 1e9 else '+'}pp"] = (len(sel), sum(b["profit"] for b in sel) / len(sel))
    below = [b for b in bets if b["edge"] < 4]
    if below:
        bands["<4pp"] = (len(below), sum(b["profit"] for b in below) / len(below))
    out["bands"] = bands
    lg = {}
    for b in bets:
        lg.setdefault(b["league"], []).append(b["profit"])
    out["leagues"] = {k: (len(v), sum(v) / len(v)) for k, v in lg.items()}
    return out


def market_metrics(snaps, odds_src, margin, line=2.5):
    pairs = [(min(max(fair_over(*s["row"]["odds"][odds_src], method=margin), EPS), 1 - EPS), outcome(s, line))
             for s in snaps if odds_src in s["row"]["odds"]]
    return prob_metrics(pairs)


def naive_metrics(snaps, line):
    """Benchmark: the league's over-rate so far this season."""
    return prob_metrics([(min(max(s["base"]["over_rate"][line], 0.01), 0.99), outcome(s, line)) for s in snaps])


# ---------------------------------------------------------------- search space
def weight_grid(fields, step):
    k = round(1 / step)
    for combo in itertools.product(range(k + 1), repeat=len(fields) - 1):
        if sum(combo) <= k:
            yield tuple(zip(fields, [c / k for c in combo] + [(k - sum(combo)) / k]))


def dimensions(model, max_n):
    fields = ("xg", "sot", "shots", "corners") if model == "preferred" else ("sot", "shots", "corners")
    step = 0.1 if model == "preferred" else 0.05

    def rec(v):
        out = [recency_weights(5, "v1")] if max_n >= 5 else []
        for n in sorted({x for x in (3, 5, 6, 8, 10, 12, 15, 20) if x <= max_n}):
            for kind, hl in (("equal", None), ("linear", None), ("exp", 2), ("exp", 4), ("exp", 8)):
                out.append(recency_weights(n, kind, hl))
        return [dataclasses.replace(v, recency=tuple(w), recency_label=lab) for w, lab in out]

    return [
        ("recency & sample size", rec),
        ("input weights", lambda v: [dataclasses.replace(v, weights=w) for w in weight_grid(fields, step)]),
        ("shrinkage", lambda v: [dataclasses.replace(v, shrink=x / 100) for x in range(40, 101, 5)]),
        ("caps", lambda v: [dataclasses.replace(v, caps=c) for c in (True, False)]),
        ("distribution", lambda v: [dataclasses.replace(v, dist="poisson", dist_param=0.0)]
         + [dataclasses.replace(v, dist="dc", dist_param=r) for r in (-0.2, -0.15, -0.1, -0.05, 0.05, 0.1)]
         + [dataclasses.replace(v, dist="negbin", dist_param=k) for k in (2, 5, 10, 20, 50)]),
    ]


def search(evaluator, start, max_n, passes=2, log=print):
    """Coordinate descent on mean log loss. Returns (best variant, best score, path)."""
    best, best_s = start, mean_logloss(evaluator.predict(start))
    path = [("start (V1)", best, best_s)]
    for p in range(passes):
        improved = False
        for name, gen in dimensions(start.model, max_n):
            cands = gen(best)
            scored = [(mean_logloss(evaluator.predict(c)), i, c) for i, c in enumerate(cands)]
            sc, _, c = min(scored)
            if sc < best_s - 1e-9:
                best, best_s, improved = c, sc, True
            path.append((f"pass {p + 1}: {name} ({len(cands)} candidates)", best, best_s))
            log(f"  {path[-1][0]}: mean log loss {best_s:.5f}")
        if not improved:
            break
    return best, best_s, path
