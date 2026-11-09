# Backtest — fallback model (footballdata)

Generated 2026-11-09 20:57 UTC. Method: docs/BACKTESTING.md. These are category-3 findings (METHODOLOGY §25) only for the TEST seasons; calibration-season numbers are in-sample.

## Data

- Source: footballdata; leagues: epl, laliga, seriea, bundesliga, ligue1, portugal, eredivisie, belgium, turkey, scotland
- Seasons: 2005/2006 to 2025/2026; **test (held out): 2024/2025, 2025/2026**
- Matches loaded: 67417. Eligible (both teams ≥ 10 previous league matches this season, every input present): calibration 33533, test 4606
- Every variant is scored on the same matches. V1 alone on its own eligibility (≥ 5 matches): 5520 test matches.

## Variants

- **V1**: fallback; weights sot 0.45 / shots 0.35 / corners 0.20; last 5 matches (V1 30/25/20/15/10); shrink 0.75/0.25; caps on; Poisson
- **Best on calibration seasons**: fallback; weights sot 0.35 / shots 0.45 / corners 0.20; last 10 matches (half-life 8 matches); shrink 0.55/0.45; caps on; Dixon-Coles rho=-0.10
- Calibration mean log loss (3 lines): V1 0.61738 → best 0.61122

Search path (coordinate descent on calibration seasons only):

| step | mean log loss |
|---|---|
| start (V1) | 0.61738 |
| pass 1: recency & sample size (26 candidates) | 0.61191 |
| pass 1: input weights (231 candidates) | 0.61173 |
| pass 1: shrinkage (13 candidates) | 0.61131 |
| pass 1: caps (2 candidates) | 0.61131 |
| pass 1: distribution (12 candidates) | 0.61122 |
| pass 2: recency & sample size (26 candidates) | 0.61122 |
| pass 2: input weights (231 candidates) | 0.61122 |
| pass 2: shrinkage (13 candidates) | 0.61122 |
| pass 2: caps (2 candidates) | 0.61122 |
| pass 2: distribution (12 candidates) | 0.61122 |

## Test seasons: probability accuracy

Lower is better. 'League rate' predicts each league's over-rate so far this season. Δ = best − V1 paired log loss with standard error; |Δ| < 2·SE is not a reliable difference.

| line | n | V1 Brier | V1 log loss | best Brier | best log loss | league-rate log loss | Δ log loss (SE) | mean forecast V1 / best | observed |
|---|---|---|---|---|---|---|---|---|---|
| O1.5 | 4606 | 0.1750 | 0.5342 | 0.1734 | 0.5297 | 0.5341 | -0.0045 (0.0014) | 0.755 / 0.773 | 0.773 |
| O2.5 | 4606 | 0.2499 | 0.6934 | 0.2460 | 0.6851 | 0.6903 | -0.0083 (0.0016) | 0.519 / 0.524 | 0.536 |
| O3.5 | 4606 | 0.2140 | 0.6199 | 0.2108 | 0.6118 | 0.6185 | -0.0081 (0.0016) | 0.304 / 0.306 | 0.313 |

V1 on its own eligibility (≥ 5 matches): O1.5 log loss 0.5326 (n=5520); O2.5 log loss 0.6929 (n=5520); O3.5 log loss 0.6198 (n=5520)

### Market benchmark, Over 2.5 (same test matches)

Margin removed three ways (Štrumbelj 2014). If the market's log loss is lower than the model's, the model has no information the price lacks.

| odds | n | proportional | Shin | power |
|---|---|---|---|---|
| avg | 4606 | 0.6711 | 0.6709 | 0.6709 |
| pin | 2860 | 0.6710 | 0.6709 | 0.6708 |
| pin_close | 2864 | 0.6682 | 0.6681 | 0.6681 |
| avg_close | 4606 | 0.6681 | 0.6679 | 0.6678 |

### Calibration, Over 2.5 (test)

| forecast bin | V1 n | V1 mean forecast | V1 observed | best n | best mean forecast | best observed |
|---|---|---|---|---|---|---|
| 0.2–0.3 | 33 | 0.281 | 0.515 | 0 | - | - |
| 0.3–0.4 | 484 | 0.364 | 0.483 | 152 | 0.380 | 0.474 |
| 0.4–0.5 | 1500 | 0.456 | 0.485 | 1601 | 0.460 | 0.472 |
| 0.5–0.6 | 1631 | 0.547 | 0.559 | 2166 | 0.545 | 0.556 |
| 0.6–0.7 | 787 | 0.639 | 0.614 | 665 | 0.635 | 0.638 |
| 0.7–0.8 | 166 | 0.733 | 0.554 | 22 | 0.719 | 0.591 |
| 0.8–0.9 | 5 | 0.818 | 0.600 | 0 | - | - |

### Over 2.5 log loss by league (test)

| league | n | V1 | best | league rate |
|---|---|---|---|---|
| epl | 560 | 0.6940 | 0.6866 | 0.6881 |
| laliga | 560 | 0.7068 | 0.6928 | 0.6957 |
| seriea | 559 | 0.7039 | 0.6984 | 0.6956 |
| bundesliga | 412 | 0.6641 | 0.6582 | 0.6657 |
| ligue1 | 432 | 0.7044 | 0.6874 | 0.6932 |
| portugal | 431 | 0.6925 | 0.6850 | 0.6935 |
| eredivisie | 431 | 0.6976 | 0.6864 | 0.6898 |
| belgium | 445 | 0.6837 | 0.6845 | 0.6981 |
| turkey | 441 | 0.6873 | 0.6808 | 0.6923 |
| scotland | 335 | 0.6909 | 0.6829 | 0.6868 |

## Test seasons: betting simulation, Over/Under 2.5

Flat 1-unit stakes at **avg** pre-match odds; edge vs proportional margin-free probability; qualifying edge ≥ 4.0pp; sides: over; at most one bet per match. CLV = expected value of the bet at the margin-free Pinnacle closing price (positive = beat the close). ROI ± 2·SE spanning 0 means the result is consistent with no edge.

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| V1 | 1258 | -103.2 | -8.2% ± +5.5% | 48.2% | 1.96 | 107.2 | -5.48% |
| best | 1186 | -110.3 | -9.3% ± +5.9% | 45.0% | 2.06 | 118.9 | -6.11% |

V1 by qualifying edge threshold (the 4pp rule is a V1 assumption):

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| V1 ≥0pp | 2053 | -166.3 | -8.1% ± +4.2% | 49.1% | 1.92 | 166.5 | -5.78% |
| best ≥0pp | 2106 | -154.1 | -7.3% ± +4.3% | 47.9% | 1.98 | 159.4 | -6.09% |
| V1 ≥2pp | 1641 | -139.9 | -8.5% ± +4.8% | 48.6% | 1.94 | 141.5 | -5.71% |
| best ≥2pp | 1628 | -130.5 | -8.0% ± +5.0% | 46.7% | 2.01 | 130.5 | -5.98% |
| V1 ≥4pp | 1258 | -103.2 | -8.2% ± +5.5% | 48.2% | 1.96 | 107.2 | -5.48% |
| best ≥4pp | 1186 | -110.3 | -9.3% ± +5.9% | 45.0% | 2.06 | 118.9 | -6.11% |
| V1 ≥7pp | 812 | -93.2 | -11.5% ± +7.0% | 45.6% | 1.98 | 100.0 | -5.32% |
| best ≥7pp | 605 | -78.5 | -13.0% ± +8.5% | 41.7% | 2.13 | 83.3 | -6.05% |
| V1 ≥10pp | 475 | -77.3 | -16.3% ± +9.1% | 42.7% | 1.99 | 84.7 | -4.79% |
| best ≥10pp | 225 | -39.5 | -17.6% ± +14.2% | 38.7% | 2.20 | 41.7 | -5.88% |

V1 by margin-removal method:

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| proportional | 1258 | -103.2 | -8.2% ± +5.5% | 48.2% | 1.96 | 107.2 | -5.48% |
| shin | 1243 | -117.5 | -9.5% ± +5.6% | 46.9% | 1.98 | 124.0 | -5.82% |
| power | 1236 | -123.5 | -10.0% ± +5.6% | 46.4% | 1.99 | 129.8 | -5.97% |

V1 by edge band: 4-7pp: 446 bets, ROI -2.2%; 7-10pp: 337 bets, ROI -4.7%; 10-+pp: 475 bets, ROI -16.3%
V1 by league: belgium: 57 bets, ROI -6.5%; laliga: 190 bets, ROI -4.3%; eredivisie: 156 bets, ROI -15.5%; seriea: 108 bets, ROI -1.4%; epl: 114 bets, ROI -9.3%; scotland: 90 bets, ROI -7.0%; portugal: 150 bets, ROI -10.4%; ligue1: 151 bets, ROI -18.2%; turkey: 97 bets, ROI -0.9%; bundesliga: 145 bets, ROI -3.3%

Best by edge band: 4-7pp: 581 bets, ROI -5.5%; 7-10pp: 380 bets, ROI -10.3%; 10-+pp: 225 bets, ROI -17.6%
Best by league: laliga: 201 bets, ROI -4.0%; belgium: 24 bets, ROI -13.8%; scotland: 80 bets, ROI -14.9%; seriea: 93 bets, ROI -12.3%; turkey: 78 bets, ROI -4.3%; portugal: 163 bets, ROI -5.3%; epl: 94 bets, ROI -10.8%; eredivisie: 152 bets, ROI -15.4%; ligue1: 137 bets, ROI -12.8%; bundesliga: 164 bets, ROI -7.5%

## Reading this report

- The search tried many variants on the calibration seasons, so its calibration score is optimistic. Only the test-season columns estimate real performance, and even those are one sample.
- Small differences in log loss (a few thousandths) are typical between reasonable models; check Δ against its SE.
- Betting ROI is far noisier than log loss. A few hundred bets cannot distinguish a 2% edge from zero.
- Historical odds are football-data.co.uk market averages/maximums and Pinnacle prices, not the UK books the live model compares against; only the 2.5 line is available.
- Do not change config.py from this report without the user's agreement; record any change in METHODOLOGY.md (§27).
