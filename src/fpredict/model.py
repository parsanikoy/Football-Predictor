"""Pure model functions (docs/METHODOLOGY.md §7–§16), Version 2. No I/O here."""
import math
from . import config as C


def weighted(values):
    """Recency-weighted metric. values[0] is the most recent match."""
    if len(values) != C.SAMPLE_SIZE:
        raise ValueError(f"need exactly {C.SAMPLE_SIZE} values, got {len(values)}")
    if any(v is None for v in values):
        raise ValueError("missing value in sample; never treat missing as zero")
    return sum(w * v for w, v in zip(C.RECENCY_WEIGHTS, values))


def cap(x, lo, hi):
    """-> (value, capped_flag)"""
    if x < lo:
        return lo, True
    if x > hi:
        return hi, True
    return x, False


def team_scores(sample, baseline):
    """sample: list of SAMPLE_SIZE dicts (most recent first) with keys shots, sot, corners and
    conc_shots, conc_sot, conc_corners. baseline: league averages per team per match."""
    w = {}
    for f in C.MODEL_FIELDS:
        w[f] = weighted([m[f] for m in sample])
        w["conc_" + f] = weighted([m["conc_" + f] for m in sample])
    ratios = {}
    for f in C.MODEL_FIELDS:
        ratios[f] = w[f] / baseline[f]
        ratios["conc_" + f] = w["conc_" + f] / baseline[f]
    attack_raw = sum(k * ratios[f] for f, k in C.ATTACK_WEIGHTS.items())
    dw_raw = sum(k * ratios["conc_" + f] for f, k in C.ATTACK_WEIGHTS.items())
    attack, a_cap = cap(attack_raw, C.SCORE_MIN, C.SCORE_MAX)
    dw, d_cap = cap(dw_raw, C.SCORE_MIN, C.SCORE_MAX)
    return {"weighted": w, "ratios": ratios, "attack_raw": attack_raw, "attack": attack,
            "attack_capped": a_cap, "dw_raw": dw_raw, "dw": dw, "dw_capped": d_cap}


def expected_goals(home, away, baseline):
    """home/away: outputs of team_scores. Returns dict with raw/final expected goals, total and cap flags.
    If the total cap applies, home and away are scaled so they still add up to the capped total."""
    hg, ag = baseline["home_goals"], baseline["away_goals"]
    raw_h = hg * home["attack"] * away["dw"]
    raw_a = ag * away["attack"] * home["dw"]
    shr_h = C.SHRINK_MODEL * raw_h + C.SHRINK_LEAGUE * hg
    shr_a = C.SHRINK_MODEL * raw_a + C.SHRINK_LEAGUE * ag
    fin_h, cap_h = cap(shr_h, C.HOME_XG_MIN, C.HOME_XG_MAX)
    fin_a, cap_a = cap(shr_a, C.AWAY_XG_MIN, C.AWAY_XG_MAX)
    total, cap_t = cap(fin_h + fin_a, C.TOTAL_MIN, C.TOTAL_MAX)
    if cap_t:
        fin_h, fin_a = fin_h * total / (fin_h + fin_a), fin_a * total / (fin_h + fin_a)
    return {"raw_home": raw_h, "raw_away": raw_a, "shrunk_home": shr_h, "shrunk_away": shr_a,
            "home": fin_h, "away": fin_a, "total": total,
            "caps": {"home_xg": cap_h, "away_xg": cap_a, "total": cap_t}}


def _pois(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def total_goals_dist(home, away, rho=None, upto=3):
    """P(total = k) for k = 0..upto: independent Poisson home/away goals with the Dixon-Coles (1997)
    correction on 0-0, 1-0, 0-1 and 1-1."""
    rho = C.DC_RHO if rho is None else rho
    tau = {(0, 0): 1 - home * away * rho, (0, 1): 1 + home * rho, (1, 0): 1 + away * rho, (1, 1): 1 - rho}
    p = [0.0] * (upto + 1)
    for i in range(upto + 1):
        for j in range(upto + 1 - i):
            p[i + j] += max(tau.get((i, j), 1.0), 0.0) * _pois(home, i) * _pois(away, j)
    return p


def over_probs(home, away):
    """P(Over 1.5), P(Over 2.5), P(Over 3.5), validated as nested."""
    p = total_goals_dist(home, away)
    out = {1.5: 1 - sum(p[:2]), 2.5: 1 - sum(p[:3]), 3.5: 1 - sum(p[:4])}
    if not 1 >= out[1.5] >= out[2.5] >= out[3.5] >= 0:
        raise ArithmeticError("nested probability validation failed")
    return out


def implied_probability(over, under=None):
    """-> (probability, 'margin-adjusted' | 'raw')"""
    raw_o = 1 / over
    if under:
        return raw_o / (raw_o + 1 / under), "margin-adjusted"
    return raw_o, "raw"


def edge_pp(model_p, implied_p):
    return (model_p - implied_p) * 100


def rating(edge):
    if edge < 0:
        return "No model value"
    if edge < 2:
        return "Negligible"
    if edge < 4:
        return "Weak"
    if edge < 7:
        return "Moderate"
    return "Strong model difference"
