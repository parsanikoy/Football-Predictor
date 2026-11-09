"""Command line:  python -m fpredict run|settle|leagues  (see README.md)."""
import argparse, datetime as dt, os, pathlib, sys

from . import config as C
from . import analysis, log, report
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
    sub.add_parser("settle", help="fill final scores into the prediction log")
    sub.add_parser("leagues", help="list configured leagues")
    h = sub.add_parser("history", help="download historical data for backtesting")
    h.add_argument("--source", choices=("footballdata", "pitchapi"), default="footballdata")
    h.add_argument("--leagues", default=",".join(C.LEAGUES))
    h.add_argument("--seasons", default="2017/2018:2025/2026", help="'A:B' range or comma list, e.g. 2023/2024")
    b = sub.add_parser("backtest", help="replay the model on past seasons (docs/BACKTESTING.md)")
    b.add_argument("--source", choices=("footballdata", "pitchapi"), default="footballdata",
                   help="footballdata: shots/SOT/corners + O/U 2.5 odds (fallback model); pitchapi: adds xG")
    b.add_argument("--leagues", default=",".join(C.LEAGUES))
    b.add_argument("--seasons", help="'A:B' range or comma list (default: 2017/2018:2025/2026 for footballdata, "
                                     "2021/2022:2025/2026 for pitchapi)")
    b.add_argument("--test-seasons", help="held-out seasons (default: the last season in --seasons)")
    b.add_argument("--model", choices=("preferred", "fallback"), help="default: preferred if the data has xG")
    b.add_argument("--max-n", type=int, default=10, help="largest sample size the search may try")
    b.add_argument("--carry-over", action="store_true", help="let team samples include previous-season matches")
    b.add_argument("--odds", default="avg", choices=("avg", "max", "b365", "pin", "pin_close", "avg_close"))
    b.add_argument("--margin", default="proportional", choices=("proportional", "shin", "power"))
    b.add_argument("--min-edge", type=float, default=C.MIN_EDGE_PP)
    b.add_argument("--both-sides", action="store_true", help="also bet Unders (V1 only recommends Overs)")
    b.add_argument("--no-search", action="store_true", help="score V1 only")
    b.add_argument("--passes", type=int, default=2)
    b.add_argument("--out", help="report path (default reports/backtests/<date>_<source>_<model>.md)")
    a = p.parse_args(argv)
    load_dotenv()

    if a.cmd == "leagues":
        for k, (n, s, l) in C.LEAGUES.items():
            print(f"{k:11} {n:26} odds={s:32} pitch={l}")
        return 0
    if a.cmd in ("history", "backtest"):
        return backtest_cmd(a, p)
    pitch = PitchClient()
    if a.cmd == "settle":
        s, pend = log.settle(pitch, analysis.iso(analysis.utcnow()))
        print(f"settled {s} rows; {pend} rows still pending")
        return 0

    odds = None
    if not a.no_odds:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            print("ERROR: ODDS_API_KEY is not set. Ask the user for their Odds API key, or rerun with --no-odds.",
                  file=sys.stderr)
            return 2
        odds = OddsClient(key, "totals,alternate_totals" if a.full_odds else "alternate_totals")
    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in C.LEAGUES]
    if bad:
        p.error(f"unknown league(s): {bad}")
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


def backtest_cmd(a, p):
    from . import backtest_run as R, history as H
    leagues = [x.strip() for x in a.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in C.LEAGUES]
    if bad:
        p.error(f"unknown league(s): {bad}")
    err = lambda m: print(m, file=sys.stderr)
    if a.cmd == "history":
        for lg in leagues:
            for s in R.parse_seasons(a.seasons):
                try:
                    rows = H.load_footballdata(lg, s) if a.source == "footballdata" else H.load_pitch(lg, s, log=err)
                    err(f"{lg} {s}: {len(rows)} matches")
                except Exception as e:
                    err(f"{lg} {s}: failed ({e})")
        return 0
    seasons = R.parse_seasons(a.seasons or ("2017/2018:2025/2026" if a.source == "footballdata"
                                            else "2021/2022:2025/2026"))
    test = R.parse_seasons(a.test_seasons) if a.test_seasons else seasons[-1:]
    res = R.run(a.source, leagues, seasons, test, model=a.model, max_n=a.max_n, carry_over=a.carry_over,
                odds_src=a.odds, margin=a.margin, min_edge=a.min_edge,
                sides=("over", "under") if a.both_sides else ("over",), do_search=not a.no_search,
                passes=a.passes, log=err)
    out = pathlib.Path(a.out) if a.out else (ROOT / "reports" / "backtests" /
                                             f"{dt.date.today()}_{a.source}_{res['model']}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(R.report(res))
    out.with_suffix(".best.json").write_text(R.best_json(res))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
