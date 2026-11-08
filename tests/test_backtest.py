import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fpredict import backtest  # noqa: E402

TEAMS = ["t1", "t2", "t3", "t4"]


def stats(xg=1.4, shots=12, sot=4, corners=5):
    items = [{"key": k, "home": str(v), "away": str(v)} for k, v in
             (("expected_goals", xg), ("total_shots", shots), ("ShotsOnTarget", sot), ("corners", corners))]
    return {"periods": [{"period": "All", "groups": [{"items": items}]}]}


class FakePitch:
    """Round-robin of 4 teams, one round per week. The target match (last) has extreme stats and a
    9-0 score: if anything from it leaked into its own prediction, the prediction would change."""
    def __init__(self, rounds=7):
        self.matches = []
        pairs = [("t1", "t2"), ("t3", "t4"), ("t1", "t3"), ("t2", "t4"), ("t1", "t4"), ("t2", "t3")]
        for r in range(rounds):
            day = str(dt.date(2025, 9, 1) + dt.timedelta(weeks=r))
            for i, (h, a) in enumerate(pairs[(2 * r) % 6:(2 * r) % 6 + 2]):
                self.matches.append({"id": f"m{r}{i}", "date": day, "time_utc": f"{day}T15:00:00Z",
                                     "status": "finished", "score_home": 2, "score_away": 1,
                                     "home_team": {"id": h, "name": h.upper()}, "away_team": {"id": a, "name": a.upper()}})
        self.matches[-1].update(score_home=9, score_away=0)

    def league_matches(self, lid, season=None):
        return {"league": {"season": "2026"}, "matches": self.matches}

    def match_stats(self, mid, cacheable=True):
        return stats(xg=5.0, shots=40, sot=20, corners=15) if mid == self.matches[-1]["id"] else stats()


class TestBacktest(unittest.TestCase):
    def run_bt(self, pitch):
        last = pitch.matches[-1]["date"]
        return backtest.run(pitch, ["epl"], last, last, log=lambda *_: None)

    def test_no_leakage_from_target_match(self):
        res = self.run_bt(FakePitch())
        self.assertEqual(len(res["rows"]), 2)
        for r in res["rows"]:
            # All earlier matches are identical and league-average, so the model must predict exactly
            # league-average goals (2 + 1 = 3), unaffected by the target match's 9-0 and huge stats.
            self.assertAlmostEqual(r["exp_total"], 3.0, places=6)
            self.assertAlmostEqual(r["league_avg_total"], 3.0, places=6)
            for ln in (1.5, 2.5, 3.5):
                self.assertAlmostEqual(r["p"][ln], r["bench"][ln], places=9)

    def test_insufficient_history_is_skipped_not_guessed(self):
        res = self.run_bt(FakePitch(rounds=4))   # each team has < 5 earlier matches
        self.assertEqual(res["rows"], [])
        self.assertTrue(all(x["status"] == "blocked" for x in res["skipped"]))

    def test_scores(self):
        self.assertAlmostEqual(backtest.brier(0.7, 1), 0.09)
        self.assertAlmostEqual(backtest.brier(0.7, 0), 0.49)
        self.assertLess(backtest.log_loss(0.9, 1), backtest.log_loss(0.6, 1))
        self.assertTrue(backtest.log_loss(1.0, 0) < 100)   # clipped, never infinite

    def test_report_renders(self):
        res = self.run_bt(FakePitch())
        md = backtest.report(res)
        self.assertIn("Accuracy by line", md)
        self.assertIn("No odds were used", md)


if __name__ == "__main__":
    unittest.main()
