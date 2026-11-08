"""Pure model functions (docs/METHODOLOGY.md §7–§16). No I/O here."""
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


def team_scores(sample, baseline, model_type):
    """sample: list of 5 dicts (most recent first) with keys xg, shots, sot, corners and
    conc_xg, conc_shots, conc_sot, conc_corners. baseline: league averages per team per match.
    model_type: 'preferred' or 'fallback'."""
    fields = ["shots", "sot", "corners"] + (["xg"] if model_type == "preferred" else [])
    w = {}
    for f in fields:
        w[f] = weighted([m[f] for m in sample])
        w["conc_" + f] = weighted([m["conc_" + f] for m in sample])
    ratios = {}
    for f in fields:
        ratios[f] = w[f] / baseline[f]
        ratios["conc_" + f] = w["conc_" + f] / baseline[f]   # xGA ratio uses league avg xG
    weights = C.PREFERRED_ATTACK if model_type == "preferred" else C.FALLBACK_ATTACK
    attack_raw = sum(k * ratios[f] for f, k in weights.items())
    dw_raw = sum(k * ratios["conc_" + f] for f, k in weights.items())
    attack, a_cap = cap(attack_raw, C.SCORE_MIN, C.SCORE_MAX)
    dw, d_cap = cap(dw_raw, C.SCORE_MIN, C.SCORE_MAX)
    return {"weighted": w, "ratios": ratios, "attack_raw": attack_raw, "attack": attack,
            "attack_capped": a_cap, "dw_raw": dw_raw, "dw": dw, "dw_capped": d_cap}


def expected_goals(home, away, baseline):
    """home/away: outputs of team_scores. Returns dict with raw/final xG, total and cap flags."""
    hg, ag = baseline["home_goals"], baseline["away_goals"]
    raw_h = hg * home["attack"] * away["dw"]
    raw_a = ag * away["attack"] * home["dw"]
    shr_h = C.SHRINK_MODEL * raw_h + C.SHRINK_LEAGUE * hg
    shr_a = C.SHRINK_MODEL * raw_a + C.SHRINK_LEAGUE * ag
    fin_h, cap_h = cap(shr_h, C.HOME_XG_MIN, C.HOME_XG_MAX)
    fin_a, cap_a = cap(shr_a, C.AWAY_XG_MIN, C.AWAY_XG_MAX)
    total, cap_t = cap(fin_h + fin_a, C.TOTAL_MIN, C.TOTAL_MAX)
    return {"raw_home": raw_h, "raw_away": raw_a, "shrunk_home": shr_h, "shrunk_away": shr_a,
            "home": fin_h, "away": fin_a, "total": total,
            "caps": {"home_xg": cap_h, "away_xg": cap_a, "total": cap_t}}


def poisson_overs(lam):
    """P(Over 1.5), P(Over 2.5), P(Over 3.5) for Poisson(lam), validated as nested."""
    p = [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(4)]
    out = {1.5: 1 - sum(p[:2]), 2.5: 1 - sum(p[:3]), 3.5: 1 - sum(p[:4])}
    if not out[1.5] >= out[2.5] >= out[3.5]:
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
