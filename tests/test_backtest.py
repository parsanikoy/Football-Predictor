import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpredict import backtest as B, history as H, model as M  # noqa: E402


def row(date, home, away, hg, ag, stats=None, league="epl", season="2024/2025", odds=None):
    st = stats or {"home": {"xg": 1.4, "shots": 13.0, "sot": 4.0, "corners": 5.0},
                   "away": {"xg": 1.1, "shots": 11.0, "sot": 3.0, "corners": 4.0}}
    return {"league": league, "season": season, "date": date, "time": "", "home": home, "away": away,
            "hg": hg, "ag": ag, "stats": st, "odds": odds or {}}


def random_league(seed=1, rounds=12):
    rnd = random.Random(seed)
    teams = [f"T{i}" for i in range(6)]
    rows = []
    for rd in range(rounds):
        rnd.shuffle(teams)
        for i in range(0, 6, 2):
            st = {s: {"xg": rnd.uniform(0.3, 2.8), "shots": float(rnd.randint(5, 22)),
                      "sot": float(rnd.randint(1, 9)), "corners": float(rnd.randint(1, 11))} for s in ("home", "away")}
            rows.append(row(f"2024-{8 + rd // 4:02d}-{1 + (rd % 4) * 7:02d}", teams[i], teams[i + 1],
                            rnd.randint(0, 4), rnd.randint(0, 3), st, odds={"avg": (1.9, 1.95)}))
    return rows


class TestBacktest(unittest.TestCase):
    def test_live_variant_matches_live_model(self):
        """The backtest's live variant must reproduce src/fpredict/model.py on the same inputs."""
        v = B.Variant.live()
        snaps = B.eligible(B.snapshots(random_league(rounds=16)), v.n, v.fields())
        self.assertGreater(len(snaps), 5)
        for s, (h, a, t), P in B.Evaluator(snaps, v.fields()).predict(v):
            base = s["base"]
            H_ = M.team_scores(s["home"][:v.n], base)
            A_ = M.team_scores(s["away"][:v.n], base)
            E = M.expected_goals(H_, A_, base)
            self.assertAlmostEqual(h, E["home"])
            self.assertAlmostEqual(a, E["away"])
            for ln, p in M.over_probs(E["home"], E["away"]).items():
                self.assertAlmostEqual(P[ln], p)

    def test_no_same_day_or_future_leakage(self):
        rows = [row("2024-08-10", "A", "B", 3, 3), row("2024-08-10", "C", "A", 0, 0), row("2024-08-17", "A", "C", 1, 0)]
        snaps = {(s["row"]["home"], s["row"]["date"]): s for s in B.snapshots(rows)}
        self.assertEqual(snaps[("C", "2024-08-10")]["home"], [])     # A's same-day match not visible
        self.assertIsNone(snaps[("A", "2024-08-10")]["base"])
        later = snaps[("A", "2024-08-17")]
        self.assertEqual(len(later["home"]), 2)
        self.assertEqual(later["base"]["n"], 2)
        self.assertAlmostEqual(later["base"]["home_goals"], 1.5)

    def test_season_reset_and_carry_over(self):
        rows = [row("2024-05-01", "A", "B", 1, 1, season="2023/2024"), row("2024-08-17", "A", "B", 1, 0)]
        self.assertEqual(B.snapshots(rows)[1]["home"], [])
        self.assertEqual(len(B.snapshots(rows, carry_over=True)[1]["home"]), 1)
        self.assertIsNone(B.snapshots(rows, carry_over=True)[1]["base"])   # league averages always reset

    def test_missing_stat_is_ineligible_not_zero(self):
        rows = random_league(rounds=8)
        del rows[0]["stats"]["home"]["xg"]
        snaps = B.snapshots(rows)
        elig = B.eligible(snaps, 5, ("xg",))
        for s in elig:
            for side in ("home", "away"):
                self.assertTrue(all(r["xg"] is not None for r in s[side][:5]))

    def test_distributions(self):
        p = B.over_probs(1.4, 1.1, "poisson")
        self.assertAlmostEqual(p[2.5], 1 - math.exp(-2.5) * (1 + 2.5 + 2.5 ** 2 / 2))
        nb = B.over_probs(1.4, 1.1, "negbin", 1e6)
        self.assertAlmostEqual(nb[2.5], p[2.5], places=4)
        dc0 = B.over_probs(1.4, 1.1, "dc", 0.0)
        self.assertAlmostEqual(dc0[1.5], p[1.5])
        dc = B.over_probs(1.4, 1.1, "dc", -0.1)
        # negative rho: 0-0 up by h*a*0.1*p00, but 1-0 and 0-1 down by the same amount each -> P(<=1) falls
        h, a = 1.4, 1.1
        p00 = math.exp(-h - a)
        self.assertAlmostEqual(dc[1.5] - p[1.5], h * a * 0.1 * p00)
        for d in (p, nb, dc):
            self.assertGreaterEqual(d[1.5], d[2.5])
            self.assertGreaterEqual(d[2.5], d[3.5])

    def test_margin_methods(self):
        for m in ("proportional", "shin", "power"):
            self.assertAlmostEqual(B.fair_over(1.9, 1.9, m), 0.5, places=6)
        self.assertAlmostEqual(B.fair_over(1.6, 2.3, "proportional"), M.implied_probability(1.6, 2.3)[0])
        # Shin and power move probability away from the long shot (favourite-longshot bias)
        prop = B.fair_over(1.3, 3.4, "proportional")
        self.assertGreater(B.fair_over(1.3, 3.4, "shin"), prop)
        self.assertGreater(B.fair_over(1.3, 3.4, "power"), prop)

    def test_bets_and_metrics(self):
        snaps = B.eligible(B.snapshots(random_league(rounds=16)), 10, B.Variant.live().fields())
        preds = B.Evaluator(snaps, B.Variant.live().fields()).predict(B.Variant.live())
        b = B.bet_metrics(preds, "avg", "proportional", -100, ("over",))
        self.assertEqual(b["n"], len(preds))
        wins = sum(1 for s, _, _ in preds if B.outcome(s, 2.5))
        self.assertAlmostEqual(b["profit"], wins * 0.9 - (len(preds) - wins))
        m = B.prob_metrics([(0.5, 1), (0.5, 0)])
        self.assertAlmostEqual(m["brier"], 0.25)
        self.assertAlmostEqual(m["logloss"], math.log(2))

    def test_weight_grid_sums_to_one(self):
        g = list(B.weight_grid(("a", "b", "c"), 0.05))
        self.assertEqual(len(g), 231)
        self.assertTrue(all(abs(sum(w for _, w in x) - 1) < 1e-9 for x in g))

    def test_footballdata_parse(self):
        text = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST,HC,AC,Avg>2.5,Avg<2.5,PC>2.5,PC<2.5\n"
                "E0,16/08/2024,20:00,Man United,Fulham,1,0,14,10,5,2,7,8,1.53,2.52,,\n"
                "E0,17/08/24,15:00,Ipswich,Liverpool,0,2,7,,2,,,,1.6,2.4,1.62,2.45\n")
        r = H.fd_parse(text, "epl", "2024/2025")
        self.assertEqual(r[0]["date"], "2024-08-16")
        self.assertEqual(r[0]["stats"]["away"]["corners"], 8.0)
        self.assertEqual(r[0]["odds"], {"avg": (1.53, 2.52)})
        self.assertNotIn("shots", r[1]["stats"]["away"])          # blank stays missing, never zero
        self.assertEqual(r[1]["odds"]["pin_close"], (1.62, 2.45))

    def test_odds_join(self):
        pitch = [row("2025-08-16", "Wolverhampton Wanderers", "Manchester City", 0, 4),
                 row("2025-08-17", "Leeds United", "Everton", 1, 0),
                 row("2025-08-18", "Arsenal", "Chelsea", 2, 2)]
        fd = [row("2025-08-16", "Wolves", "Man City", 0, 4, odds={"avg": (1.7, 2.2)}),
              row("2025-08-18", "Leeds", "Everton", 1, 0, odds={"avg": (2.1, 1.8)}),   # date within a day
              row("2025-08-18", "Arsenal", "Chelsea", 1, 2, odds={"avg": (1.9, 1.9)})]  # score differs
        n, pairs = H.join_odds(pitch, fd)
        self.assertEqual(n, 2)
        self.assertEqual(pitch[0]["odds"]["avg"], (1.7, 2.2))
        self.assertEqual(pitch[1]["odds"]["avg"], (2.1, 1.8))
        self.assertEqual(pitch[2]["odds"], {})
        self.assertIn(("Wolverhampton Wanderers", "Wolves"), pairs)


if __name__ == "__main__":
    unittest.main()
