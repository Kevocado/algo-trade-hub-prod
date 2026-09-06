# FPL Scout

A small local tool for Fantasy Premier League decisions:

1. **Predicts each player's points for the next gameweek**, using one
   XGBoost model per position (GK / DEF / MID / FWD) trained on real
   historical gameweek data.
2. **Shows which stats actually drive points, per position** — feature
   importance broken out by role, since a goalkeeper's points come from
   completely different things than a forward's.
3. **Ranks the upcoming gameweek** so you can scout who to bring in, filtered
   by position/price/team.

## Quick start

```bash
pip install -r requirements.txt
python train.py        # trains the 4 position models (~a minute, one-time)
streamlit run app.py    # opens the dashboard
```

Re-run `python train.py` (or click "Retrain models" in the sidebar)
whenever you want the models to pick up more recent seasons' data.

## How it works

- **Training data**: the last 4 completed Premier League seasons, pulled
  from [vaastav's Fantasy-Premier-League
  repo](https://github.com/vaastav/Fantasy-Premier-League) (real per-player,
  per-gameweek stats), cached locally in `data_cache/` after the first run.
- **Features**: for each stat (minutes, points, goals, assists, bps,
  ict_index, xG, xA, etc.), the rolling average over the player's last 3 and
  last 5 gameweeks — plus the upcoming opponent's official FPL difficulty
  rating and home/away. The exact same feature logic (`features.py`) is used
  for training and for live scouting, so there's no train/serve mismatch.
- **Model**: a separate XGBoost regressor per position, validated on the
  most recent held-out season. Feature importance is computed two ways —
  XGBoost's gain score and permutation importance — and shown per position
  in the dashboard.
- **Scouting the next gameweek**: live current-season data comes straight
  from the official FPL API (prices, availability/injury status, fixtures).
  Early in a season (or right after a gameweek), players who haven't played
  much yet are flagged **low data** rather than silently mis-scored.

## Files

| File | Purpose |
|---|---|
| `historical_data.py` | Fetches/caches past-season gameweek data for training |
| `fpl_data.py` | Live FPL API client (current players, prices, fixtures) |
| `features.py` | Shared lag/fixture-difficulty feature engineering |
| `model.py` | Train/save/load per-position models + feature importance |
| `train.py` | CLI: builds the 4 models |
| `scout.py` | Builds the ranked next-gameweek scouting table |
| `app.py` | Streamlit dashboard |

## Notes

`market_scanner_app.py`, `requirements_minimal.txt`, and
`INTEGRATION_PROMPT.md` in this folder are leftovers from an unrelated
project and aren't part of this tool.
