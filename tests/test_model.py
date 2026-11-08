import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpredict import analysis, model as M  # noqa: E402

BASE = {"xg": 1.5, "shots": 14.0, "sot": 5.0, "corners": 5.0, "home_goals": 1.6, "away_goals": 1.3,
        "sources": {}}


def avg_sample(scale=1.0):
    row = {f: BASE[f] * scale for f in ("xg", "shots", "sot", "corners")}
    row.update({"conc_" + f: BASE[f] * scale for f in ("xg", "shots", "sot", "corners")})
    return [dict(row) for _ in range(5)]


class TestModel(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(M.weighted([1, 1, 1, 1, 1]), 1.0)
        self.assertAlmostEqual(M.weighted([10, 0, 0, 0, 0]), 3.0)

    def test_missing_value_is_never_zero(self):
        with self.assertRaises(ValueError):
            M.weighted([1, None, 1, 1, 1])
        with self.assertRaises(ValueError):
            M.weighted([1, 1, 1, 1])

    def test_league_average_team_scores_one(self):
        for mode in ("preferred", "fallback"):
            s = M.team_scores(avg_sample(), BASE, mode)
            self.assertAlmostEqual(s["attack"], 1.0)
            self.assertAlmostEqual(s["dw"], 1.0)

    def test_score_caps(self):
        hi = M.team_scores(avg_sample(2.0), BASE, "preferred")
        lo = M.team_scores(avg_sample(0.3), BASE, "preferred")
        self.assertEqual((hi["attack"], hi["attack_capped"]), (1.50, True))
        self.assertEqual((lo["dw"], lo["dw_capped"]), (0.65, True))

    def test_expected_goals_shrinkage_and_caps(self):
        avg = M.team_scores(avg_sample(), BASE, "preferred")
        e = M.expected_goals(avg, avg, BASE)
        self.assertAlmostEqual(e["home"], 1.6)
        self.assertAlmostEqual(e["away"], 1.3)
        top = M.team_scores(avg_sample(3.0), BASE, "preferred")
        e = M.expected_goals(top, top, BASE)
        # raw away = 1.3 * 1.5 * 1.5 = 2.925 -> shrunk 0.75*2.925 + 0.25*1.3 = 2.519 (under 2.75 cap)
        self.assertAlmostEqual(e["away"], 0.75 * 2.925 + 0.25 * 1.3)
        self.assertFalse(e["caps"]["away_xg"])

    def test_poisson_known_values(self):
        p = M.poisson_overs(2.5)
        self.assertAlmostEqual(p[1.5], 1 - math.exp(-2.5) * (1 + 2.5))
        self.assertAlmostEqual(p[2.5], 0.456186, places=5)
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


def ctx_with(xg_missing=False, shots_missing=False):
    finished = []
    for i in range(6):
        for home, away in (("A", "X"), ("Y", "B")):
            st = {s: {"xg": 1.5, "shots": 14.0, "sot": 5.0, "corners": 5.0} for s in ("home", "away")}
            if i == 0 and home == "A":
                if xg_missing:
                    del st["home"]["xg"]
                if shots_missing:
                    del st["away"]["shots"]
            finished.append({"id": f"m{i}{home}", "date": f"2026-10-{20 - i:02d}", "time_utc": f"2026-10-{20 - i:02d}T15:00:00Z",
                             "home_team": {"id": home, "name": home}, "away_team": {"id": away, "name": away},
                             "score_home": 1, "score_away": 1, "stats": st, "user_fields": []})
    return {"finished": finished, "baseline": dict(BASE)}


def fixture():
    return {"key": "f1", "home_id": "A", "away_id": "B", "home": "A", "away": "B", "label": "A v B",
            "missing": [], "odds": {}, "started": False}


class TestRules(unittest.TestCase):
    def test_complete_data_uses_preferred(self):
        fx = analysis.analyse(fixture(), ctx_with(), fallback_ok=False)
        self.assertEqual((fx["status"], fx["model_type"]), ("modelled", "preferred"))

    def test_missing_xg_needs_user_choice(self):
        fx = analysis.analyse(fixture(), ctx_with(xg_missing=True), fallback_ok=False)
        self.assertEqual(fx["status"], "needs_fallback_choice")
        self.assertEqual(fx["missing"], [("home", "2026-10-20", "X", "xg")])

    def test_fallback_only_after_consent(self):
        fx = analysis.analyse(fixture(), ctx_with(xg_missing=True), fallback_ok=True)
        self.assertEqual((fx["status"], fx["model_type"]), ("modelled", "fallback"))

    def test_missing_core_field_blocks(self):
        fx = analysis.analyse(fixture(), ctx_with(shots_missing=True), fallback_ok=True)
        self.assertEqual(fx["status"], "blocked")
        self.assertIn(("home", "2026-10-20", "X", "conc_shots"), fx["missing"])

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
