# Backtesting (METHODOLOGY §27)

The harness replays the model over past seasons, exactly as it would have run before each kick-off, with
every coefficient exposed as a parameter. Every run compares the live configuration in `src/fpredict/config.py`
(currently Version 2) with the best variant its search finds. It exists to test alternative inputs and
weightings **before** anyone proposes changing `config.py`. It never changes the live model.

## Commands

```bash
# 1. download history (cached in data/history/, git-ignored)
PYTHONPATH=src python3 -m fpredict history --source footballdata --seasons 2017/2018:2025/2026
PYTHONPATH=src python3 -m fpredict history --source pitchapi --leagues epl --seasons 2021/2022:2025/2026

# 2. backtest: search on calibration seasons, score once on held-out test seasons
PYTHONPATH=src python3 -m fpredict backtest --source footballdata --seasons 2017/2018:2025/2026 \
    --test-seasons 2024/2025,2025/2026
```

Useful options: `--leagues epl,laliga`, `--model standard|xg` (xg: research mode that also searches an xG weight; needs `--source pitchapi`), `--max-n 20` (longest sample the
search may try), `--carry-over` (team samples may reach into last season), `--odds avg|max|b365|pin|pin_close|avg_close`,
`--margin proportional|shin|power`, `--min-edge 4`, `--both-sides` (also bet Unders), `--no-search` (score the live model only).
Output: `reports/backtests/<date>_<source>_<model>.md` plus `.best.json` with the chosen variant.

## Data sources

| source | inputs | odds | seasons | cost |
|---|---|---|---|---|
| football-data.co.uk | goals, shots, SOT, corners (no xG) → the live model's inputs | O/U 2.5 only: market average and maximum, Bet365, Pinnacle, closing prices from 2019/20 | 2017/18+ used here (files go back further) | free, one file per league-season |
| PitchAPI | adds xG/xGA → `--model xg` research | joined from football-data.co.uk by league, date ±1 day, score and team name | 2021/22 onwards | one request per match (~30 s and ~380 requests per league-season, cached) |

Network: the cloud environment must allow `www.football-data.co.uk` and `football-data.co.uk`.

## What is held fixed so the comparison is honest

- **Point in time.** A match's prediction uses only matches on earlier dates, and league averages from earlier
  dates in the same season, as the live model does. Same-day results are never used.
- **Same matches for every variant.** Only matches where both teams have at least `--max-n` previous league
  matches (default 10) with every input present are scored. The live model's score on its own eligible set is also reported.
- **Missing data is never zero-filled.** A match with a missing stat makes the affected team-matches ineligible.
- **Calibration vs test (§27).** The coordinate search runs only on calibration seasons. The chosen variant
  and the live model are then scored once on the test seasons. Re-running the search after looking at test results and
  then quoting those test results again breaks this; move the test window forward instead.
- **Live fidelity.** `tests/test_backtest.py` checks that the harness's live variant reproduces `model.py` exactly.

## What the search varies (research motivation in brackets)

| dimension | candidates |
|---|---|
| sample size & recency | the live weights; for n in 3…max-n: equal, linear, exponential half-life 2/4/8 matches (Dixon & Coles 1997; Ley et al. 2019) |
| input weights | full simplex grid, step 0.05 (standard) or 0.1 (xg) (Mead et al. 2023; Wheatcroft 2020) |
| shrinkage | model weight 0.40–1.00 |
| caps | caps on / off |
| distribution | Poisson; Dixon–Coles low-score correction ρ ∈ {−0.2…+0.1}; negative binomial k ∈ {2…50} (Dixon & Coles 1997; Boshnakov et al. 2017) |

Selection objective: log loss averaged over the 1.5/2.5/3.5 lines (choose on calibration quality rather than
hit rate; Walsh & Joshi 2024). Margin removal (proportional / Shin / power; Štrumbelj 2014) and the qualifying
edge threshold are reported as separate comparisons; they do not change the probabilities.

## Report contents

Test-season Brier score and log loss per line with paired difference ± standard error; a league-over-rate
benchmark; the market's own log loss (margin removed three ways); calibration table; log loss by league;
betting simulation (flat stakes, at most one bet per match): ROI ± 2·SE, hit rate, maximum drawdown,
closing-line value against Pinnacle closing, results by edge band, league, edge threshold and margin method.

## Limitations

- Historical odds are market averages/maximums and Pinnacle, not the UK books the live model uses; only the
  2.5 line exists in the files, so Over 1.5/3.5 can be scored for accuracy but not for betting.
- With `max` odds the Over and Under prices can come from different books, so the margin-free probability is approximate.
- Several leagues have split seasons or play-offs (Scotland, Belgium); those matches are included as league matches.
- One test window is one sample. Small log-loss differences need their standard error; ROI over a few hundred
  bets cannot separate a small edge from zero.

## History

The Version 2 coefficients came from `reports/backtests/2026-11-09_footballdata_fallback_2005-2026.md` (reports
dated 2026-11-09 compare against Version 1, which was live at the time and is labelled V1 in them).
