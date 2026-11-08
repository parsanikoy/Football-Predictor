"""Prediction log (docs/METHODOLOGY.md §26). One row per fixture × goal line per run.
Final scores are filled later by `fpredict settle`; never invented."""
import csv, pathlib
from . import config as C

LOG = pathlib.Path(__file__).resolve().parents[2] / "data" / "prediction_log.csv"
COLUMNS = ["prediction_time", "model_version", "league", "match_id", "match", "home", "away", "kickoff",
           "model_type", "exp_home", "exp_away", "exp_total", "line", "model_prob", "bookmaker", "odds",
           "under_odds", "odds_timestamp", "raw_implied", "margin_adjusted", "edge_pp", "recommended",
           "final_score", "total_goals", "outcome", "closing_odds"]


def _read(path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def append(res, path=LOG):
    rows = _read(path)
    n = 0
    for f in res["fixtures"]:
        if f["status"] != "modelled":
            continue
        rec = res["recs"].get(f["key"])
        for ln in C.LINES:
            e = f.get("edges", {}).get(ln)
            d = e[2] if e else None
            rows.append({
                "prediction_time": res["generated_at"], "model_version": C.MODEL_VERSION,
                "league": f["league_name"], "match_id": f["key"], "match": f["label"], "home": f["home"],
                "away": f["away"], "kickoff": f["kickoff"], "model_type": f["model_type"],
                "exp_home": f"{f['E']['home']:.4f}", "exp_away": f"{f['E']['away']:.4f}",
                "exp_total": f"{f['E']['total']:.4f}", "line": ln, "model_prob": f"{f['P'][ln]:.4f}",
                "bookmaker": d["title"] if d else "", "odds": d["over"] if d else "",
                "under_odds": (d["under"] or "") if d else "", "odds_timestamp": (d["updated"] or "") if d else "",
                "raw_implied": f"{d['raw']:.4f}" if d else "",
                "margin_adjusted": f"{d['implied']:.4f}" if d and d["type"] == "margin-adjusted" else "",
                "edge_pp": f"{e[0]:.2f}" if e else "",
                "recommended": "Y" if rec and rec[1] == ln else "",
                "final_score": "", "total_goals": "", "outcome": "", "closing_odds": ""})
            n += 1
    _write(path, rows)
    return n


def settle(pitch, now_iso, path=LOG):
    """Fill final scores and outcomes for finished matches. Returns (settled, still_pending)."""
    rows = _read(path)
    cache, settled, pending = {}, 0, 0
    for r in rows:
        if r["final_score"] or r["kickoff"] > now_iso:
            pending += not r["final_score"]
            continue
        if r["match_id"] not in cache:
            m = pitch.match(r["match_id"])
            m = m.get("match", m)
            done = m.get("status") == "finished" and m.get("score_home") is not None
            cache[r["match_id"]] = (m["score_home"], m["score_away"]) if done else None
        sc = cache[r["match_id"]]
        if not sc:
            pending += 1
            continue
        tot = sc[0] + sc[1]
        r.update(final_score=f"{sc[0]}-{sc[1]}", total_goals=tot, outcome="WIN" if tot > float(r["line"]) else "LOSS")
        settled += 1
    _write(path, rows)
    return settled, pending
