import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpredict import analysis, config as C, model as M  # noqa: E402

BASE = {"shots": 14.0, "sot": 5.0, "corners": 5.0, "home_goals": 1.6, "away_goals": 1.3, "sources": {}}
N = C.SAMPLE_SIZE


def avg_sample(scale=1.0):
    row = {f: BASE[f] * scale for f in C.MODEL_FIELDS}
    row.update({"conc_" + f: BASE[f] * scale for f in C.MODEL_FIELDS})
    return [dict(row) for _ in range(N)]


class TestModel(unittest.TestCase):
    def test_version_2_coefficients(self):
        self.assertEqual(C.MODEL_VERSION, "V2")
        self.assertEqual(N, 10)
        self.assertAlmostEqual(sum(C.RECENCY_WEIGHTS), 1.0)
        self.assertAlmostEqual(C.RECENCY_WEIGHTS[8] / C.RECENCY_WEIGHTS[0], 0.5)   # half-life 8 matches
        self.assertAlmostEqual(sum(C.ATTACK_WEIGHTS.values()), 1.0)
        self.assertAlmostEqual(C.SHRINK_MODEL + C.SHRINK_LEAGUE, 1.0)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(M.weighted([1] * N), 1.0)
        self.assertAlmostEqual(M.weighted([10] + [0] * (N - 1)), 10 * C.RECENCY_WEIGHTS[0])

    def test_missing_value_is_never_zero(self):
        with self.assertRaises(ValueError):
            M.weighted([1, None] + [1] * (N - 2))
        with self.assertRaises(ValueError):
            M.weighted([1] * (N - 1))

    def test_league_average_team_scores_one(self):
        s = M.team_scores(avg_sample(), BASE)
        self.assertAlmostEqual(s["attack"], 1.0)
        self.assertAlmostEqual(s["dw"], 1.0)

    def test_score_caps(self):
        hi = M.team_scores(avg_sample(2.0), BASE)
        lo = M.team_scores(avg_sample(0.3), BASE)
        self.assertEqual((hi["attack"], hi["attack_capped"]), (1.50, True))
        self.assertEqual((lo["dw"], lo["dw_capped"]), (0.65, True))

    def test_expected_goals_shrinkage_and_caps(self):
        avg = M.team_scores(avg_sample(), BASE)
        e = M.expected_goals(avg, avg, BASE)
        self.assertAlmostEqual(e["home"], 1.6)
        self.assertAlmostEqual(e["away"], 1.3)
        top = M.team_scores(avg_sample(3.0), BASE)
        e = M.expected_goals(top, top, BASE)
        # raw away = 1.3 * 1.5 * 1.5 = 2.925 -> shrunk 0.55*2.925 + 0.45*1.3
        self.assertAlmostEqual(e["away"], 0.55 * 2.925 + 0.45 * 1.3)
        self.assertFalse(e["caps"]["away_xg"])

    def test_dixon_coles_probabilities(self):
        h, a = 1.4, 1.1
        p = M.over_probs(h, a)
        lam = h + a
        poisson_o15 = 1 - math.exp(-lam) * (1 + lam)
        # rho -0.10 moves h*a*0.10*P(0-0) of probability out of 1-0/0-1 net, so P(Over 1.5) rises by that much
        self.assertAlmostEqual(p[1.5] - poisson_o15, h * a * 0.10 * math.exp(-lam))
        self.assertAlmostEqual(sum(M.total_goals_dist(h, a, rho=0.0, upto=3)),
                               sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(4)))
        self.assertGreaterEqual(p[1.5], p[2.5])
        self.assertGreaterEqual(p[2.5], p[3.5])

    def test_implied_probability(self):
        self.assertAlmostEqual(M.implied_probability(1.90)[0], 1 / 1.90)
        self.assertEqual(M.implied_probability(1.90)[1], "raw")
        p, kind = M.implied_probability(1.90, 1.90)
        self.assertAlmostEqual(p, 0.5)
        self.assertEqual(kind, "margin-adjusted")

    def test_edge_and_rating(self):
        self.assertAlmostEqual(M.edge_pp(0.612, 0.53), 8.2)
        self.assertEqual(M.rating(-0.1), "No model value")
        self.assertEqual(M.rating(3.99), "Weak")
        self.assertEqual(M.rating(4.0), "Moderate")
        self.assertEqual(M.rating(7.0), "Strong model difference")


def ctx_with(shots_missing=False, matches=N + 1):
    finished = []
    for i in range(matches):
        for home, away in (("A", "X"), ("Y", "B")):
            st = {s: {"xg": 1.5, "shots": 14.0, "sot": 5.0, "corners": 5.0} for s in ("home", "away")}
            if i == 0 and home == "A" and shots_missing:
                del st["away"]["shots"]
            d = f"2026-10-{28 - i:02d}"
            finished.append({"id": f"m{i}{home}", "date": d, "time_utc": f"{d}T15:00:00Z",
                             "home_team": {"id": home, "name": home}, "away_team": {"id": away, "name": away},
                             "score_home": 1, "score_away": 1, "stats": st, "user_fields": []})
    return {"finished": finished, "baseline": dict(BASE)}


def fixture():
    return {"key": "f1", "home_id": "A", "away_id": "B", "home": "A", "away": "B", "label": "A v B",
            "missing": [], "odds": {}, "started": False}


class TestRules(unittest.TestCase):
    def test_complete_data_is_modelled(self):
        fx = analysis.analyse(fixture(), ctx_with())
        self.assertEqual((fx["status"], fx["model_type"]), ("modelled", "V2"))
        self.assertEqual(len(fx["samples"]["home"]), N)

    def test_xg_is_not_required(self):
        ctx = ctx_with()
        for m in ctx["finished"]:
            for side in ("home", "away"):
                m["stats"][side].pop("xg")
        self.assertEqual(analysis.analyse(fixture(), ctx)["status"], "modelled")

    def test_missing_field_blocks(self):
        fx = analysis.analyse(fixture(), ctx_with(shots_missing=True))
        self.assertEqual(fx["status"], "blocked")
        self.assertIn(("home", "2026-10-28", "X", "conc_shots"), fx["missing"])

    def test_too_few_matches_blocks(self):
        fx = analysis.analyse(fixture(), ctx_with(matches=N - 1))
        self.assertEqual(fx["status"], "blocked")
        self.assertIn(("home", "-", "-", f"only {N - 1} of {N} completed league matches this season"), fx["missing"])

    def test_one_bookmaker_rule_requires_full_coverage(self):
        price = lambda o, u: {"title": "", "over": o, "under": u, "raw": 1 / o,
                              "implied": M.implied_probability(o, u)[0], "type": "margin-adjusted",
                              "updated": None, "exchange": False, "source": "test"}
        f1 = {"key": "1", "P": {1.5: .9, 2.5: .7, 3.5: .5},
              "odds": {"bk1": {2.5: price(2.0, 1.8)}, "bk2": {2.5: price(1.9, 1.9)}}}
        f2 = {"key": "2", "P": {1.5: .9, 2.5: .7, 3.5: .5}, "odds": {"bk2": {2.5: price(1.9, 1.9)}}}
        recs = {"1": (10.0, 2.5, "bk1", None), "2": (10.0, 2.5, "bk2", None)}
        out = analysis.bookmaker_assessment([f1, f2], recs)
        self.assertEqual(out["recommended"]["bookmaker"], "bk2")
        del f2["odds"]["bk2"]
        out = analysis.bookmaker_assessment([f1, f2], recs)
        self.assertIsNone(out["recommended"])


if __name__ == "__main__":
    unittest.main()
