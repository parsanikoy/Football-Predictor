# Backtest — fallback model (footballdata)

Generated 2026-11-09 21:00 UTC. Method: docs/BACKTESTING.md. These are category-3 findings (METHODOLOGY §25) only for the TEST seasons; calibration-season numbers are in-sample.

## Data

- Source: footballdata; leagues: epl, laliga, seriea, bundesliga, ligue1, portugal, eredivisie, belgium, turkey, scotland
- Seasons: 2005/2006 to 2025/2026; **test (held out): 2024/2025, 2025/2026**
- Matches loaded: 67417. Eligible (both teams ≥ 20 previous league matches incl. previous seasons, every input present): calibration 41034, test 6031
- Every variant is scored on the same matches. V1 alone on its own eligibility (≥ 5 matches): 6322 test matches.

## Variants

- **V1**: fallback; weights sot 0.45 / shots 0.35 / corners 0.20; last 5 matches (V1 30/25/20/15/10); shrink 0.75/0.25; caps on; Poisson
- **Best on calibration seasons**: fallback; weights sot 0.50 / shots 0.40 / corners 0.10; last 20 matches (half-life 8 matches); shrink 0.65/0.35; caps on; Dixon-Coles rho=-0.05
- Calibration mean log loss (3 lines): V1 0.62061 → best 0.61370

Search path (coordinate descent on calibration seasons only):

| step | mean log loss |
|---|---|
| start (V1) | 0.62061 |
| pass 1: recency & sample size (41 candidates) | 0.61387 |
| pass 1: input weights (231 candidates) | 0.61384 |
| pass 1: shrinkage (13 candidates) | 0.61375 |
| pass 1: caps (2 candidates) | 0.61375 |
| pass 1: distribution (12 candidates) | 0.61370 |
| pass 2: recency & sample size (41 candidates) | 0.61370 |
| pass 2: input weights (231 candidates) | 0.61370 |
| pass 2: shrinkage (13 candidates) | 0.61370 |
| pass 2: caps (2 candidates) | 0.61370 |
| pass 2: distribution (12 candidates) | 0.61370 |

## Test seasons: probability accuracy

Lower is better. 'League rate' predicts each league's over-rate so far this season. Δ = best − V1 paired log loss with standard error; |Δ| < 2·SE is not a reliable difference.

| line | n | V1 Brier | V1 log loss | best Brier | best log loss | league-rate log loss | Δ log loss (SE) | mean forecast V1 / best | observed |
|---|---|---|---|---|---|---|---|---|---|
| O1.5 | 6031 | 0.1743 | 0.5339 | 0.1723 | 0.5283 | 0.5449 | -0.0056 (0.0013) | 0.757 / 0.769 | 0.777 |
| O2.5 | 6031 | 0.2514 | 0.6975 | 0.2471 | 0.6883 | 0.7096 | -0.0092 (0.0015) | 0.522 / 0.528 | 0.540 |
| O3.5 | 6031 | 0.2143 | 0.6217 | 0.2111 | 0.6135 | 0.6339 | -0.0082 (0.0015) | 0.307 / 0.310 | 0.309 |

V1 on its own eligibility (≥ 5 matches): O1.5 log loss 0.5348 (n=6322); O2.5 log loss 0.6973 (n=6322); O3.5 log loss 0.6220 (n=6322)

### Market benchmark, Over 2.5 (same test matches)

Margin removed three ways (Štrumbelj 2014). If the market's log loss is lower than the model's, the model has no information the price lacks.

| odds | n | proportional | Shin | power |
|---|---|---|---|---|
| avg | 6031 | 0.6726 | 0.6725 | 0.6725 |
| pin | 4300 | 0.6732 | 0.6732 | 0.6732 |
| pin_close | 4302 | 0.6699 | 0.6699 | 0.6699 |
| avg_close | 6031 | 0.6694 | 0.6693 | 0.6693 |

### Calibration, Over 2.5 (test)

| forecast bin | V1 n | V1 mean forecast | V1 observed | best n | best mean forecast | best observed |
|---|---|---|---|---|---|---|
| 0.0–0.1 | 3 | 0.041 | 1.000 | 3 | 0.041 | 1.000 |
| 0.1–0.2 | 12 | 0.159 | 0.417 | 10 | 0.165 | 0.400 |
| 0.2–0.3 | 52 | 0.272 | 0.481 | 19 | 0.275 | 0.526 |
| 0.3–0.4 | 637 | 0.364 | 0.488 | 254 | 0.374 | 0.449 |
| 0.4–0.5 | 1887 | 0.456 | 0.492 | 1924 | 0.459 | 0.480 |
| 0.5–0.6 | 2087 | 0.548 | 0.560 | 2697 | 0.547 | 0.562 |
| 0.6–0.7 | 1085 | 0.641 | 0.608 | 1037 | 0.636 | 0.609 |
| 0.7–0.8 | 245 | 0.734 | 0.580 | 76 | 0.727 | 0.618 |
| 0.8–0.9 | 23 | 0.834 | 0.478 | 11 | 0.831 | 0.455 |

### Over 2.5 log loss by league (test)

| league | n | V1 | best | league rate |
|---|---|---|---|---|
| epl | 738 | 0.6976 | 0.6892 | 0.7083 |
| laliga | 737 | 0.7052 | 0.6866 | 0.7086 |
| seriea | 712 | 0.7047 | 0.6981 | 0.6982 |
| bundesliga | 551 | 0.6760 | 0.6681 | 0.6984 |
| ligue1 | 590 | 0.7015 | 0.6868 | 0.7140 |
| portugal | 570 | 0.6984 | 0.6917 | 0.7108 |
| eredivisie | 590 | 0.6898 | 0.6823 | 0.7058 |
| belgium | 536 | 0.6970 | 0.6925 | 0.7325 |
| turkey | 555 | 0.6873 | 0.6794 | 0.7103 |
| scotland | 452 | 0.7166 | 0.7104 | 0.7150 |

## Test seasons: betting simulation, Over/Under 2.5

Flat 1-unit stakes at **avg** pre-match odds; edge vs proportional margin-free probability; qualifying edge ≥ 4.0pp; sides: over; at most one bet per match. CLV = expected value of the bet at the margin-free Pinnacle closing price (positive = beat the close). ROI ± 2·SE spanning 0 means the result is consistent with no edge.

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| V1 | 1724 | -106.2 | -6.2% ± +4.7% | 49.6% | 1.94 | 110.1 | -5.69% |
| best | 1612 | -119.0 | -7.4% ± +5.0% | 46.7% | 2.02 | 125.7 | -6.03% |

V1 by qualifying edge threshold (the 4pp rule is a V1 assumption):

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| V1 ≥0pp | 2748 | -176.3 | -6.4% ± +3.6% | 50.3% | 1.91 | 176.3 | -5.94% |
| best ≥0pp | 2870 | -172.7 | -6.0% ± +3.6% | 49.3% | 1.95 | 176.9 | -6.17% |
| V1 ≥2pp | 2226 | -143.7 | -6.5% ± +4.1% | 49.9% | 1.93 | 145.2 | -5.87% |
| best ≥2pp | 2217 | -139.2 | -6.3% ± +4.2% | 48.3% | 1.98 | 145.1 | -6.17% |
| V1 ≥4pp | 1724 | -106.2 | -6.2% ± +4.7% | 49.6% | 1.94 | 110.1 | -5.69% |
| best ≥4pp | 1612 | -119.0 | -7.4% ± +5.0% | 46.7% | 2.02 | 125.7 | -6.03% |
| V1 ≥7pp | 1152 | -103.7 | -9.0% ± +5.8% | 47.5% | 1.96 | 110.5 | -5.67% |
| best ≥7pp | 796 | -88.8 | -11.2% ± +7.3% | 43.8% | 2.07 | 91.6 | -5.92% |
| V1 ≥10pp | 699 | -92.8 | -13.3% ± +7.4% | 44.9% | 1.98 | 100.9 | -5.40% |
| best ≥10pp | 311 | -53.8 | -17.3% ± +11.6% | 40.8% | 2.10 | 58.5 | -5.96% |

V1 by margin-removal method:

| | bets | profit (units) | ROI ± 2·SE | hit rate | avg odds | max drawdown | CLV |
|---|---|---|---|---|---|---|---|
| proportional | 1724 | -106.2 | -6.2% ± +4.7% | 49.6% | 1.94 | 110.1 | -5.69% |
| shin | 1704 | -119.4 | -7.0% ± +4.7% | 48.6% | 1.96 | 125.8 | -5.92% |
| power | 1695 | -117.7 | -6.9% ± +4.8% | 48.4% | 1.97 | 124.0 | -6.03% |

V1 by edge band: 4-7pp: 572 bets, ROI -0.4%; 7-10pp: 453 bets, ROI -2.4%; 10-+pp: 699 bets, ROI -13.3%
V1 by league: eredivisie: 209 bets, ROI -8.7%; portugal: 186 bets, ROI -6.4%; scotland: 125 bets, ROI -2.7%; ligue1: 221 bets, ROI -12.2%; turkey: 128 bets, ROI +3.2%; laliga: 262 bets, ROI -6.2%; belgium: 70 bets, ROI -28.9%; seriea: 139 bets, ROI +4.6%; bundesliga: 230 bets, ROI -3.6%; epl: 154 bets, ROI -7.5%

Best by edge band: 4-7pp: 816 bets, ROI -3.7%; 7-10pp: 485 bets, ROI -7.2%; 10-+pp: 311 bets, ROI -17.3%
Best by league: eredivisie: 184 bets, ROI -11.6%; portugal: 186 bets, ROI -4.1%; laliga: 272 bets, ROI -0.9%; ligue1: 224 bets, ROI -7.4%; belgium: 19 bets, ROI -54.6%; bundesliga: 248 bets, ROI -13.2%; seriea: 119 bets, ROI -7.7%; epl: 151 bets, ROI -7.5%; scotland: 112 bets, ROI -6.5%; turkey: 97 bets, ROI -0.1%

## Reading this report

- The search tried many variants on the calibration seasons, so its calibration score is optimistic. Only the test-season columns estimate real performance, and even those are one sample.
- Small differences in log loss (a few thousandths) are typical between reasonable models; check Δ against its SE.
- Betting ROI is far noisier than log loss. A few hundred bets cannot distinguish a 2% edge from zero.
- Historical odds are football-data.co.uk market averages/maximums and Pinnacle prices, not the UK books the live model compares against; only the 2.5 line is available.
- Do not change config.py from this report without the user's agreement; record any change in METHODOLOGY.md (§27).
