"""Version 2 configuration (docs/METHODOLOGY.md §25). Coefficients were chosen by the historical backtest:
tuned on 2005/06-2023/24 and checked on held-out 2024/25-2025/26
(reports/backtests/2026-11-09_footballdata_fallback_2005-2026.md). Do not change them without the user's
agreement; record any change in docs/METHODOLOGY.md."""

MODEL_VERSION = "V2"
MODEL_LABEL = "Version 2 shots / shots on target / corners model"

# key -> (display name, The Odds API sport key, PitchAPI league id)
LEAGUES = {
    "epl":        ("English Premier League",   "soccer_epl",                    "l_4WFCIZ"),
    "laliga":     ("Spanish La Liga",          "soccer_spain_la_liga",          "l_0ErfuF"),
    "seriea":     ("Italian Serie A",          "soccer_italy_serie_a",          "l_0ALvwF"),
    "bundesliga": ("German Bundesliga",        "soccer_germany_bundesliga",     "l_1Isor4"),
    "ligue1":     ("French Ligue 1",           "soccer_france_ligue_one",       "l_3FJFUl"),
    "portugal":   ("Portuguese Primeira Liga", "soccer_portugal_primeira_liga", "l_4QexZg"),
    "eredivisie": ("Dutch Eredivisie",         "soccer_netherlands_eredivisie", "l_4H43wr"),
    "belgium":    ("Belgian Pro League",       "soccer_belgium_first_div",      "l_2L6d1F"),
    "turkey":     ("Turkish Super Lig",        "soccer_turkey_super_league",    "l_0S1uaf"),
    "scotland":   ("Scottish Premiership",     "soccer_spl",                    "l_1LMdEO"),
}
SPORT_TO_LEAGUE = {v[1]: k for k, v in LEAGUES.items()}

LINES = (1.5, 2.5, 3.5)

# Sample and recency (§4, §9): the last 10 league matches, weight halving every 8 matches, normalised
SAMPLE_SIZE = 10
RECENCY_HALF_LIFE = 8
_RAW = [0.5 ** (i / RECENCY_HALF_LIFE) for i in range(SAMPLE_SIZE)]
RECENCY_WEIGHTS = tuple(w / sum(_RAW) for w in _RAW)   # most recent first; 0.143 ... 0.066

# Score weights (§7): the same weights build the Attack and the Defensive Weakness Score
ATTACK_WEIGHTS = {"sot": 0.35, "shots": 0.45, "corners": 0.20}

# Caps (§11, §13)
SCORE_MIN, SCORE_MAX = 0.65, 1.50
HOME_XG_MIN, HOME_XG_MAX = 0.35, 3.25
AWAY_XG_MIN, AWAY_XG_MAX = 0.25, 2.75
TOTAL_MIN, TOTAL_MAX = 0.75, 5.25

# Shrinkage (§13)
SHRINK_MODEL = 0.55
SHRINK_LEAGUE = 0.45

# Goal distribution (§14): Dixon-Coles low-score correction on independent Poisson home/away goals
DC_RHO = -0.10

# Qualifying edge in percentage points (§17)
MIN_EDGE_PP = 4.0

# Exchanges: prices are pre-commission and they do not offer multi-match bets.
EXCHANGES = {"betfair_ex_uk", "betfair_ex_eu", "matchbook", "smarkets"}

# PitchAPI stat keys. xG is retrieved only for backtest research (`fpredict backtest --model xg`);
# the live model does not use it.
STAT_KEYS = {"xg": "expected_goals", "shots": "total_shots", "sot": "ShotsOnTarget",
             "corners": "corners", "red": "red_cards"}
MODEL_FIELDS = ("shots", "sot", "corners")   # every one is required for both teams in all 10 matches

ODDS_BASE = "https://api.the-odds-api.com/v4"
PITCH_BASE = "https://api.pitchapi.dev/v1"
USER_AGENT = "football-predictor/1.0"
