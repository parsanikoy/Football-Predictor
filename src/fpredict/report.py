"""Markdown report in the output format of docs/METHODOLOGY.md §21–§22."""
from . import config as C
from . import model as M

FIELD_NAMES = {"shots": "total shots",
               "conc_shots": "total shots conceded", "sot": "shots on target",
               "conc_sot": "shots on target conceded", "corners": "corners", "conc_corners": "corners conceded"}


def pp(e):
    return f"{'+' if e >= 0 else ''}{e:.1f}pp"


def ko(t):
    return t[:16].replace("T", " ")


def build(res):
    F = res["fixtures"]
    modelled = [f for f in F if f["status"] == "modelled"]
    blocked = [f for f in F if f["status"] == "blocked"]
    recs, fx_by = res["recs"], {f["key"]: f for f in F}
    L = []
    w = L.append
    w(f"# Football Total-Goals Model ({C.MODEL_VERSION}) — {res['window'][0]} to {res['window'][1]}\n")
    w(f"Generated {res['generated_at']}. Stats: PitchAPI. Odds: The Odds API (UK region) plus any user-supplied prices."
      f"{' Odds API credits remaining: ' + str(res['odds_remaining']) + '.' if res['odds_remaining'] else ''}\n")

    # ---- summary
    w("## ANALYSIS SUMMARY\n")
    w(f"- Matches supplied (eligible-league fixtures in window): {len(F) + len(res['excluded'])}")
    w(f"- Matches eligible (not started): {len(F)}")
    w(f"- Matches excluded: {len(res['excluded'])}" + "".join(f"\n  - {a} ({b}): {c}" for a, b, c in res["excluded"]))
    w(f"- Matches successfully modelled: {len(modelled)}")
    w(f"- Matches blocked by missing data: {len(blocked)}")
    w(f"- Model type: {C.MODEL_LABEL} ({C.MODEL_VERSION}) for all modelled matches")
    no_odds = [f["label"] for f in modelled if not f.get("edges")]
    w(f"- Modelled matches with no UK sportsbook price on any line: {len(no_odds)}")
    w(f"- Qualifying selections (edge ≥ +{C.MIN_EDGE_PP}pp, one per match): {len(recs)}")
    caps = cap_list(modelled)
    w(f"- Caps applied: {len(caps)}" + ("".join(f"\n  - {c}" for c in caps)))
    for lg, ctx in res["contexts"].items():
        cov = ", ".join(f"{k} {a // 2}/{b // 2}" for k, (a, b) in ctx["coverage"].items() if a != b)
        if cov:
            w(f"- Baseline coverage note ({ctx['name']}): some matches lack fields: {cov} matches")
    if res["mapping_notes"]:
        w("- Fuzzy team-name matches (verify): " + "; ".join(f"{a}: '{b}' → '{c}'" for a, b, c in res["mapping_notes"]))
    w("\nEdges use margin-adjusted implied probability where both Over and Under are quoted, otherwise raw "
      "implied probability (labelled). Exchanges are excluded from rankings (pre-commission prices, no multi-match bets).\n")

    # ---- model results
    w("## MODEL RESULTS\n")
    w("| Rank | Match | League | Market | Model % | Bookmaker | Odds | Implied % | Edge | Rating |")
    w("|------|-------|--------|--------|---------|-----------|------|-----------|------|--------|")
    rows = [(e, f, ln, d) for f in modelled for ln, (e, bk, d) in f.get("edges", {}).items()]
    rows.sort(key=lambda t: -t[0])
    for i, (e, f, ln, d) in enumerate(rows, 1):
        raw = "" if d["type"] == "margin-adjusted" else " (raw; margin not removed)"
        w(f"| {i} | {f['label']} | {f['league_name']} | Over {ln} | {f['P'][ln] * 100:.1f} | {d['title']} | "
          f"{d['over']:.2f} | {d['implied'] * 100:.1f}{raw} | {pp(e)} | {M.rating(e)} |")

    # ---- recommendations
    w("\n## RECOMMENDED LINE BY MATCH\n")
    if not recs:
        w(f"No line reached +{C.MIN_EDGE_PP}pp.\n")
    else:
        w("| Match | Recommended line | Model % | Implied % | Model edge |")
        w("|-------|------------------|---------|-----------|------------|")
        for key, (e, ln, bk, d) in sorted(recs.items(), key=lambda t: -t[1][0]):
            f = fx_by[key]
            w(f"| {f['label']} ({ko(f['kickoff'])} UTC) | Over {ln} @ {d['over']:.2f} {d['title']} | "
              f"{f['P'][ln] * 100:.1f} | {d['implied'] * 100:.1f} | {pp(e)} |")
        w("")
        for key, (e, ln, bk, d) in sorted(recs.items(), key=lambda t: -t[1][0])[:5]:
            f = fx_by[key]
            w(f"- {f['label']}: the model estimates Over {ln} at {f['P'][ln] * 100:.1f}%. Drivers: {f['home']} "
              f"Attack {f['H']['attack']:.2f} vs {f['away']} Defensive Weakness {f['A']['dw']:.2f}; {f['away']} "
              f"Attack {f['A']['attack']:.2f} vs {f['home']} Defensive Weakness {f['H']['dw']:.2f}; expected goals "
              f"{f['E']['home']:.2f} + {f['E']['away']:.2f} = {f['E']['total']:.2f}.")

    # ---- single bookmaker
    w("\n## SINGLE BOOKMAKER ASSESSMENT\n")
    b = res["books"]
    if not recs:
        w("No qualifying selections, so no bookmaker is recommended.\n")
    else:
        if b["recommended"]:
            r = b["recommended"]
            w(f"Recommended bookmaker: **{r['title']}**\n")
            w(f"Reason: offers all {len(recs)} selected matches and lines, with the strongest mean model edge "
              f"({pp(r['mean_edge'])}) among bookmakers that cover the complete set.\n")
        else:
            w(f"Recommended bookmaker: **none**. No bookmaker in the data offers all {len(recs)} selections, "
              "so none satisfies the one-bookmaker rule.\n")
            top = b["rows"][0] if b["rows"] else None
            if top and top["have"]:
                w(f"Largest subset at one bookmaker: **{top['title']}** ({len(top['have'])}/{len(recs)}). "
                  "Not offered there: " + "; ".join(fx_by[k]["label"] for k in top["missing"]) + ".\n")
        w("BOOKMAKER COMPARISON\n")
        w("| Bookmaker | All matches? | All selected markets? | Pricing assessment | Eligible? |")
        w("|-----------|--------------|-----------------------|-------------------|-----------|")
        for r in b["rows"]:
            allm = "Yes" if not r["missing"] else f"No ({len(r['have'])}/{len(recs)})"
            price = f"mean edge {pp(r['mean_edge'])} on offered selections" if r["have"] else "offers none"
            w(f"| {r['title']} | {allm} | {allm} | {price} | {'Yes' if r['eligible'] else 'No'} |")
        w("\nThe final combined price was not available from the data source. The bookmaker comparison therefore "
          "uses available individual component prices rather than an observed final combined quote. The data source "
          "does not confirm which multi-match formats each bookmaker supports.\n")

    # ---- missing data
    need = []
    for f in blocked:
        for side, date, opp, field in f["missing"]:
            team = f.get(side, side) if side in ("home", "away") else side
            fixture = f"{date} v {opp}" if opp != "-" else f["label"]
            nm = FIELD_NAMES.get(field, field)
            why = "Model input"
            need.append(f"| {f['label']} | {team} | {fixture} | {nm} | {why} |")
    for f in modelled:
        if not f.get("edges"):
            need.append(f"| {f['label']} | (both) | {ko(f['kickoff'])} | Over/Under 1.5, 2.5, 3.5 decimal odds "
                        f"and bookmaker | To calculate implied probability and model edge |")
        else:
            gaps = [str(ln) for ln in C.LINES if ln not in f["edges"]]
            if gaps:
                need.append(f"| {f['label']} | (both) | {ko(f['kickoff'])} | Over/Under {', '.join(gaps)} decimal "
                            f"odds and bookmaker | Line not priced by any UK sportsbook in the feed |")
    if need:
        w("## DATA I STILL NEED FROM YOU\n")
        w("| Match | Team | Date/fixture | Missing field | Why required |")
        w("|-------|------|--------------|---------------|--------------|")
        L.extend(need)
        w("")

    # ---- audit
    w("## MODEL INPUTS AND AUDIT TRAIL\n")
    rw = "/".join(f"{x * 100:.1f}" for x in C.RECENCY_WEIGHTS)
    wt = " / ".join(f"{k} {v:.2f}" for k, v in C.ATTACK_WEIGHTS.items())
    w(f"{C.MODEL_LABEL}. Last {C.SAMPLE_SIZE} league matches, recency weights {rw}% (most recent first; "
      f"half-life {C.RECENCY_HALF_LIFE} matches). Score weights {wt}. Scores capped {C.SCORE_MIN}–{C.SCORE_MAX}. "
      f"Final expected goals = {C.SHRINK_MODEL} × raw + {C.SHRINK_LEAGUE} × league average; home capped "
      f"{C.HOME_XG_MIN}–{C.HOME_XG_MAX}, away {C.AWAY_XG_MIN}–{C.AWAY_XG_MAX}, total {C.TOTAL_MIN}–{C.TOTAL_MAX}. "
      f"Probabilities: Poisson home and away goals with the Dixon–Coles low-score correction (rho {C.DC_RHO}). "
      "Coefficients were chosen by historical backtest (METHODOLOGY §25); the backtest found no betting edge "
      "against market prices.\n")
    w("| League | Season | Matches | Avg shots/team | Avg SOT/team | Avg corners/team | Avg home goals | Avg away goals |")
    w("|---|---|---|---|---|---|---|---|")
    for lg, c in res["contexts"].items():
        bs = c["baseline"]
        fmt = lambda k, n=3: "n/a" if bs.get(k) is None else f"{bs[k]:.{n}f}" + (" (User supplied)" if k in bs["sources"] else "")
        w(f"| {c['name']} | {c['season']} | {c['n_finished']} | {fmt('shots', 2)} | {fmt('sot', 2)} | "
          f"{fmt('corners', 2)} | {fmt('home_goals')} | {fmt('away_goals')} |")
    order = sorted(modelled, key=lambda f: (f["key"] not in recs, -(recs.get(f["key"], (0,))[0]), f["kickoff"]))
    for f in order:
        audit(w, f)
    return "\n".join(L) + "\n"


def cap_list(modelled):
    out = []
    for f in modelled:
        for side, S in (("home", f["H"]), ("away", f["A"])):
            if S["attack_capped"]:
                out.append(f"{f['label']}: {f[side]} Attack Score {S['attack_raw']:.3f} → {S['attack']:.2f}")
            if S["dw_capped"]:
                out.append(f"{f['label']}: {f[side]} Defensive Weakness {S['dw_raw']:.3f} → {S['dw']:.2f}")
        E = f["E"]
        if E["caps"]["home_xg"]:
            out.append(f"{f['label']}: home expected goals {E['shrunk_home']:.3f} → {E['home']:.2f}")
        if E["caps"]["away_xg"]:
            out.append(f"{f['label']}: away expected goals {E['shrunk_away']:.3f} → {E['away']:.2f}")
        if E["caps"]["total"]:
            out.append(f"{f['label']}: expected total goals capped at {E['total']:.2f}")
    return out


def audit(w, f):
    w(f"\n### {f['label']} — {f['league_name']}, {ko(f['kickoff'])} UTC\n")
    w(f"Model type: {C.MODEL_LABEL} ({C.MODEL_VERSION})\n")
    for side, S in (("home", f["H"]), ("away", f["A"])):
        w(f"**{f[side]}**: {C.SAMPLE_SIZE} most recent completed {f['league_name']} matches\n")
        w("| # | Date | Opponent | H/A | Score | Shots | Shots conc. | SOT | SOT conc. | Corners | Corners conc. | Reds for/against | Source |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(f["samples"][side], 1):
            v = lambda k, n=0: "-" if r[k] is None else f"{r[k]:.{n}f}"
            src = "PitchAPI" + ("; User supplied: " + ", ".join(r["user_fields"]) if r["user_fields"] else "")
            w(f"| {i} | {r['date']} | {r['opponent']} | {r['venue']} | {r['score']} | "
              f"{v('shots')} | {v('conc_shots')} | {v('sot')} | {v('conc_sot')} | {v('corners')} | {v('conc_corners')} | "
              f"{'-' if r['red_for'] is None else int(r['red_for'])}/{'-' if r['red_against'] is None else int(r['red_against'])} | {src} |")
        W, R = S["weighted"], S["ratios"]
        w("\n" + ", ".join(f"weighted {k} {W[k]:.3f} (ratio {R[k]:.3f})" for k in W) + "  ")
        w(f"Attack Score {S['attack']:.3f}" + (f" (capped from {S['attack_raw']:.3f})" if S["attack_capped"] else "") +
          f"; Defensive Weakness Score {S['dw']:.3f}" + (f" (capped from {S['dw_raw']:.3f})" if S["dw_capped"] else "") + "\n")
    E, b = f["E"], f["baseline"]
    w(f"Raw home expected goals = {b['home_goals']:.3f} × {f['H']['attack']:.3f} × {f['A']['dw']:.3f} = {E['raw_home']:.3f}; "
      f"raw away = {b['away_goals']:.3f} × {f['A']['attack']:.3f} × {f['H']['dw']:.3f} = {E['raw_away']:.3f}  ")
    w(f"Final home {E['home']:.3f}, final away {E['away']:.3f}, expected total = {E['total']:.3f}"
      f"{' (caps: ' + ', '.join(k for k, v in E['caps'].items() if v) + ')' if any(E['caps'].values()) else ''}  ")
    w(f"P(Over 1.5) {f['P'][1.5] * 100:.1f}% ≥ P(Over 2.5) {f['P'][2.5] * 100:.1f}% ≥ P(Over 3.5) {f['P'][3.5] * 100:.1f}% (validated)\n")
    if f["odds"]:
        w("| Bookmaker | Line | Over | Under | Implied % | Type | Edge | Updated | Source |")
        w("|---|---|---|---|---|---|---|---|---|")
        for bk, lines in sorted(f["odds"].items()):
            for ln, d in sorted(lines.items()):
                w(f"| {d['title']}{' (exchange)' if d['exchange'] else ''} | {ln} | {d['over']} | {d['under'] or '-'} | "
                  f"{d['implied'] * 100:.1f} | {d['type']} | {pp(M.edge_pp(f['P'][ln], d['implied']))} | "
                  f"{(d['updated'] or '-')[:16]} | {d['source']} |")
