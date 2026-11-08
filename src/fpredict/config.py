"""Version 1 configuration. Every coefficient here is a PROVISIONAL assumption
that has NOT been validated by historical backtesting (see docs/METHODOLOGY.md §25)."""

MODEL_VERSION = "V1"

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

# Recency weights, most recent first (§9)
RECENCY_WEIGHTS = (0.30, 0.25, 0.20, 0.15, 0.10)
SAMPLE_SIZE = 5

# Score weights (§7, §8)
PREFERRED_ATTACK = {"xg": 0.50, "sot": 0.25, "shots": 0.15, "corners": 0.10}
FALLBACK_ATTACK = {"sot": 0.45, "shots": 0.35, "corners": 0.20}

# Caps (§11, §13)
SCORE_MIN, SCORE_MAX = 0.65, 1.50
HOME_XG_MIN, HOME_XG_MAX = 0.35, 3.25
AWAY_XG_MIN, AWAY_XG_MAX = 0.25, 2.75
TOTAL_MIN, TOTAL_MAX = 0.75, 5.25

# Shrinkage (§13)
SHRINK_MODEL = 0.75
SHRINK_LEAGUE = 0.25

# Qualifying edge in percentage points (§17)
MIN_EDGE_PP = 4.0

# Exchanges: prices are pre-commission and they do not offer multi-match bets.
EXCHANGES = {"betfair_ex_uk", "betfair_ex_eu", "matchbook", "smarkets"}

# PitchAPI stat keys
STAT_KEYS = {"xg": "expected_goals", "shots": "total_shots", "sot": "ShotsOnTarget",
             "corners": "corners", "red": "red_cards"}
CORE_FIELDS = ("shots", "sot", "corners")   # needed by both models
XG_FIELD = "xg"                              # needed by preferred model only

ODDS_BASE = "https://api.the-odds-api.com/v4"
PITCH_BASE = "https://api.pitchapi.dev/v1"
USER_AGENT = "football-predictor/1.0"
