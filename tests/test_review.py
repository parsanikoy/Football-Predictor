import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpredict import model as M, review  # noqa: E402

FIELDS = ("xg", "shots", "sot", "corners")
BASE = {"xg": 1.4, "shots": 12.5, "sot": 4.3, "corners": 5.0, "home_goals": 1.55, "away_goals": 1.25}


def rand_team(rng, n=10):
    rows = []
    for _ in range(n):
        r = {}
        for f in FIELDS:
            r[f] = BASE[f] * rng.uniform(0.3, 2.2)
            r["conc_" + f] = BASE[f] * rng.uniform(0.3, 2.2)
        rows.append(r)
    return rows


def stored(i, rng, goals):
    return {"match_id": f"m{i:04d}", "league": "L", "match": "A v B", "kickoff": f"2026-09-01T{i % 24:02d}:00:00Z"
            .replace("09-01", f"{9 + i // 600:02d}-{1 + (i // 24) % 25:02d}"), "score": "", "goals": goals,
            "inputs": {"baseline": dict(BASE), "home": rand_team(rng), "away": rand_team(rng)}}


class TestReview(unittest.TestCase):
    def test_v1_matches_production_model(self):
        rng = random.Random(7)
        for _ in range(200):   # includes many capped cases
            inp = {"baseline": BASE, "home": rand_team(rng), "away": rand_team(rng)}
            H = M.team_scores(inp["home"][:5], BASE, "preferred")
            A = M.team_scores(inp["away"][:5], BASE, "preferred")
            E = M.expected_goals(H, A, BASE)
            got = review.predict(inp, review.V1)
            self.assertAlmostEqual(got["total"], E["total"], places=12)
            for ln, p in M.poisson_overs(E["total"]).items():
                self.assertAlmostEqual(got["p"][ln], p, places=12)

    def test_missing_or_short_inputs_are_not_guessed(self):
        rng = random.Random(1)
        inp = {"baseline": BASE, "home": rand_team(rng, 6), "away": rand_team(rng)}
        self.assertIsNotNone(review.predict(inp, review.V1))
        self.assertIsNone(review.predict(inp, review.VARIANTS["Sample: 10 matches, decaying weights"]))
        inp["home"][0]["xg"] = None
        self.assertIsNone(review.predict(inp, review.V1))
        self.assertIsNotNone(review.predict(inp, review.VARIANTS["Inputs: no xG (SOT 45 / shots 35 / corners 20)"]))

    def test_store_upsert(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            rng = random.Random(2)
            rows = [stored(i, rng, 2) for i in range(3)]
            self.assertEqual(review.update_store(rows, p), (3, 0))
            rows[0]["goals"] = 5
            self.assertEqual(review.update_store(rows[:1], p), (0, 1))
            s = review.load_store(p)
            self.assertEqual(len(s), 3)
            self.assertEqual(s["m0000"]["goals"], 5)

    def test_small_sample_never_suggests(self):
        rng = random.Random(3)
        store = {r["match_id"]: r for r in (stored(i, rng, rng.randint(0, 6)) for i in range(120))}
        ev = review.evaluate(store)
        self.assertFalse(ev["enough_total"])
        self.assertFalse(any(r["passed"] for r in ev["results"]))

    def test_suggest_needs_two_consecutive_passes(self):
        def ev(passed):
            r = {"variant": "X", "passed": passed, "enough_data": True,
                 "cal": {"brier_gain": .01, "n": 400}, "test": {"brier_gain": .01, "lo": .001, "hi": .02, "n": 300,
                                                                "logloss_gain": .01}}
            return {"n_total": 700, "results": [r]}
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.csv"
            self.assertTrue(review.apply_history(ev(True), "2026-11-01", h)["results"][0]["status"].startswith("Passed once"))
            self.assertTrue(review.apply_history(ev(True), "2026-11-08", h)["results"][0]["status"].startswith("SUGGESTED"))
            # re-running the same day replaces that day's record rather than counting as a new review
            self.assertTrue(review.apply_history(ev(True), "2026-11-08", h)["results"][0]["status"].startswith("SUGGESTED"))
            self.assertFalse(review.apply_history(ev(False), "2026-11-15", h)["results"][0]["status"].startswith("SUGGESTED"))
            self.assertTrue(review.apply_history(ev(True), "2026-11-22", h)["results"][0]["status"].startswith("Passed once"))


if __name__ == "__main__":
    unittest.main()
