# Football Predictor — total-goals model (Version 1)

An experimental model that estimates **Over 1.5 / 2.5 / 3.5 total goals** probabilities for ten European
domestic leagues and compares them with UK bookmaker prices. It is designed to be run by Claude Code
(see `CLAUDE.md`), but it is a plain Python package you can run yourself.

> The probabilities are statistical estimates from an untested Version 1 model. Positive model edge does not
> mean a bet will win or be profitable. See `docs/METHODOLOGY.md` §25 and §28.

## How it works

1. **Fixtures and stats** come from [PitchAPI](https://pitchapi.dev): each team's five most recent completed
   league matches (xG, xGA, shots, shots on target, corners, both for and against) and current-season
   league averages.
2. **Model** (`src/fpredict/model.py`): recency-weighted metrics → league-relative ratios → Attack and
   Defensive Weakness Scores → expected goals with 75/25 shrinkage → Poisson probabilities.
3. **Odds** come from [The Odds API](https://the-odds-api.com) (UK region, `totals` and `alternate_totals`).
   Margin is removed where both Over and Under are quoted.
4. **Output**: a Markdown report in `reports/` and one row per match and line in `data/prediction_log.csv`.

## Running it

Python 3.9+ with the standard library only; nothing to install.

```bash
ODDS_API_KEY=your-key PYTHONPATH=src python3 -m fpredict run --from 2026-11-20 --to 2026-11-24
PYTHONPATH=src python3 -m fpredict settle      # fill in final scores later
PYTHONPATH=src python3 -m unittest discover -s tests
```

| Option | Meaning |
|---|---|
| `--leagues epl,laliga` | Limit leagues (`python3 -m fpredict leagues` lists the keys) |
| `--only "Liverpool"` | Only fixtures whose "Home v Away" contains this text (repeatable) |
| `--cheap-odds` | 1 Odds API credit per match instead of 2 (a few bookmakers drop out) |
| `--no-odds` | Skip The Odds API; use odds from `data/user_supplied.json` |
| `--fallback "<match>"` / `all` | Use the Shots/SOT/Corners model where xG is missing (only after you agree) |
| `--no-log` | Don't append to the prediction log |

## Keys

- **The Odds API**: supplied at the start of each run as `ODDS_API_KEY`. It is never stored in the repo
  (`.env` is git-ignored). Each priced match costs 2 credits; listing fixtures is free.
- **PitchAPI**: sent as the `X-API-KEY` header. In Claude cloud sessions it is saved as a network secret
  and injected by the proxy. Locally, set `PITCHAPI_KEY`.

## User-supplied data

`data/user_supplied.json` holds values that you supply when a source is missing them. They are labelled
"User supplied" in reports:

```json
{
  "match_stats": {"m_abc123": {"home": {"xg": 1.42}, "away": {"xg": 0.87}}},
  "baselines": {"epl": {"xg": 1.45}},
  "odds": [{"home": "Liverpool", "away": "Manchester United", "bookmaker": "Bet365",
            "line": 2.5, "over": 1.62, "under": 2.3, "captured_at": "2026-11-20T10:00Z"}]
}
```

## Layout

```
CLAUDE.md                 operating instructions for Claude
docs/METHODOLOGY.md       full Version 1 specification (authoritative)
src/fpredict/             config, model, odds and stats clients, analysis, report, log, CLI
data/prediction_log.csv   performance record (§26)
data/team_aliases.json    Odds API → PitchAPI team-name corrections
data/user_supplied.json   values you supply
reports/                  generated reports
tests/                    unit tests
```
