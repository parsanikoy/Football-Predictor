"""Command line:  python -m fpredict run|backtest|review|settle|leagues  (see README.md)."""
import argparse, datetime as dt, os, pathlib, sys

from . import config as C
from . import analysis, backtest, log, report, review
from .odds import OddsClient
from .stats import PitchClient

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_dotenv():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main(argv=None):
    p = argparse.ArgumentParser(prog="fpredict")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="analyse fixtures in a date window")
    today = dt.date.today()
    r.add_argument("--from", dest="date_from", default=str(today))
    r.add_argument("--to", dest="date_to", default=str(today + dt.timedelta(days=7)))
    r.add_argument("--leagues", default=",".join(C.LEAGUES), help="comma list of: " + ",".join(C.LEAGUES))
    r.add_argument("--only", action="append", default=[], help="substring of 'Home v Away' to include (repeatable)")
    r.add_argument("--fallback", action="append", default=[],
                   help="match substring (or 'all') the USER has approved for the fallback model")
    r.add_argument("--user-data", default=str(ROOT / "data" / "user_supplied.json"))
    r.add_argument("--no-odds", action="store_true", help="skip The Odds API (use user-supplied odds only)")
    r.add_argument("--full-odds", action="store_true",
                   help="also request the main totals market (2 credits per match instead of 1; adds bookmakers "
                        "such as Grosvenor that only quote there)")
    r.add_argument("--no-log", action="store_true", help="do not append to data/prediction_log.csv")
    r.add_argument("--out", help="report path (default reports/<date>_<from>_<to>.md)")
    b = sub.add_parser("backtest", help="score pre-kick-off predictions for finished matches (no odds)")
    b.add_argument("--from", dest="date_from", default=str(today - dt.timedelta(days=7)))
    b.add_argument("--to", dest="date_to", default=str(today))
    b.add_argument("--leagues", default=",".join(C.LEAGUES), help="comma list of: " + ",".join(C.LEAGUES))
    b.add_argument("--only", action="append", default=[], help="substring of 'Home v Away' to include (repeatable)")
    b.add_argument("--fallback", action="append", default=[],
                   help="match substring (or 'all') the USER has approved for the fallback model")
    b.add_argument("--user-data", default=str(ROOT / "data" / "user_supplied.json"))
    b.add_argument("--out", help="report path (default reports/backtest_<date>_<from>_<to>.md; CSV alongside)")
    v = sub.add_parser("review", help="weekly: store newly finished matches, backtest alternatives, suggest tweaks")
    v.add_argument("--from", dest="date_from", help="fetch finished matches from this date "
                   "(default: 3 days before the latest stored match; required when the store is empty)")
    v.add_argument("--to", dest="date_to", default=str(today))
    v.add_argument("--no-fetch", action="store_true", help="only re-evaluate the stored matches")
    v.add_argument("--out", help="report path (default reports/review_<date>.md)")
    sub.add_parser("settle", help="fill final scores into the prediction log")
    sub.add_parser("leagues", help="list configured leagues")
    a = p.parse_args(argv)
    load_dotenv()

    if a.cmd == "leagues":
        for k, (n, s, l) in C.LEAGUES.items():
            print(f"{k:11} {n:26} odds={s:32} pitch={l}")
        return 0
    pitch = PitchClient()
    if a.cmd == "settle":
        s, pend = log.settle(pitch, analysis.iso(analysis.utcnow()))
        print(f"settled {s} rows; {pend} rows still pending")
        return 0

    if a.cmd == "review":
        return run_review(a, pitch)
    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in C.LEAGUES]
    if bad:
        p.error(f"unknown league(s): {bad}")
    if a.cmd == "backtest":
        res = backtest.run(pitch, leagues, a.date_from, a.date_to, fallback=a.fallback, only=a.only,
                           user=analysis.load_user_supplied(a.user_data), log=lambda m: print(m, file=sys.stderr))
        out = pathlib.Path(a.out) if a.out else \
            ROOT / "reports" / f"backtest_{res['generated_at'][:10]}_{a.date_from}_{a.date_to}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(backtest.report(res))
        backtest.write_csv(res, out.with_suffix(".csv"))
        print(f"report: {out}\ncsv: {out.with_suffix('.csv')}\nmodelled: {len(res['rows'])}; "
              f"not modelled: {len(res['skipped'])}")
        return 0

    odds = None
    if not a.no_odds:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            print("ERROR: ODDS_API_KEY is not set. Ask the user for their Odds API key, or rerun with --no-odds.",
                  file=sys.stderr)
            return 2
        odds = OddsClient(key, "totals,alternate_totals" if a.full_odds else "alternate_totals")
    res = analysis.run(pitch, odds, leagues, a.date_from, a.date_to, fallback=a.fallback, only=a.only,
                       user=analysis.load_user_supplied(a.user_data), log=lambda m: print(m, file=sys.stderr))
    md = report.build(res)
    out = pathlib.Path(a.out) if a.out else ROOT / "reports" / f"{res['generated_at'][:10]}_{a.date_from}_{a.date_to}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    if not a.no_log:
        print(f"logged {log.append(res)} prediction rows", file=sys.stderr)
    st = {}
    for f in res["fixtures"]:
        st[f["status"]] = st.get(f["status"], 0) + 1
    print(f"report: {out}\nfixtures: {st}\nqualifying selections: {len(res['recs'])}")
    return 0


def run_review(a, pitch):
    added = updated = 0
    window = None
    if not a.no_fetch:
        store = review.load_store()
        start = a.date_from
        if not start:
            if not store:
                print("ERROR: the review store is empty; pass --from <date> for the first review.", file=sys.stderr)
                return 2
            last = max(r["kickoff"] for r in store.values())[:10]
            start = str(dt.date.fromisoformat(last) - dt.timedelta(days=3))
        window = (start, a.date_to)
        res = backtest.run(pitch, list(C.LEAGUES), start, a.date_to, user=analysis.load_user_supplied(
            str(ROOT / "data" / "user_supplied.json")), log=lambda m: print(m, file=sys.stderr))
        added, updated = review.update_store(res["rows"])
        if res["skipped"]:
            print(f"not stored (could not be modelled before kick-off): {len(res['skipped'])}", file=sys.stderr)
    today = analysis.utcnow().strftime("%Y-%m-%d")
    ev = review.apply_history(review.evaluate(review.load_store()), today)
    out = pathlib.Path(a.out) if a.out else ROOT / "reports" / f"review_{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(review.report(ev, today, added, updated, window))
    sug = [r["variant"] for r in ev["results"] if r["status"].startswith("SUGGESTED")]
    print(f"report: {out}\nstored matches: {ev['n_total']} (+{added} new, {updated} refreshed)\n"
          f"suggested changes: {', '.join(sug) if sug else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
