# Predictor Pre-Game Feed (NFL + CFB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the NFL and CFB predictor sites a read-only `GET /api/kalshi-feed` that serves each upcoming game's *frozen, genuinely pre-game* prediction (win probability plus the margin and total distributions) and reliability buckets computed only from graded pre-game snapshots, so the Algo Trade Hub (rollout step 7b) can compare them with Kalshi prices without leakage.

**Architecture:** Both repos already snapshot predictions into SQLite (`tracking/store.py`, `game_predictions`, `INSERT OR IGNORE`, pre-kickoff check) on a 5-minute tracking tick. This plan (1) stores the distribution behind each snapshot plus a `backfilled` flag and classifies legacy rows, (2) freezes each game's snapshot inside a 48-hour window before kickoff, across the current *and next* week, so Thursday-night games are no longer missed, (3) serves the feed straight from the tracking database, never recomputing a prediction, and (4) for NFL only, fixes the week-4 `/batch` HTTP 500 (NaN lines). CFB gets the same three changes; its code is a near-verbatim port of NFL's.

**Tech Stack:** Python 3.11 (Docker image; local venvs are 3.13), FastAPI, pandas, SQLite, pytest.

**Spec:** `algo-trade-hub-prod/docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md` §3.2 (read-only sports consumer, calibration within 10 pp per bucket) and §5a ("Sports predictions — each predictor's stored pre-game predictions … the adapter must verify prediction timestamps are before kickoff"). Rollout step 7 in `docs/superpowers/plans/2026-09-24-rollout-tracker.md` (hub repo, branch `plan/2026-09-25-docs-vps-and-gate` or `main` once merged). The hub side is the companion plan `2026-09-25-sports-edges-llm-reviewer.md`.

## Kevin's decisions (2026-09-25) — apply throughout

- **Deployment target is the VPS (step 5, [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md)), not Azure.**
  - Each predictor repo's deploy workflow has a `vps` job, added by the migration and switched on by the `VPS_HOST` variable. It runs `ssh deploy@$VPS_HOST deploy nfl|cfb <sha>` against `/opt/stack`, which health-checks the service and rolls back on failure.
  - The tracking SQLite DBs live on the VPS volumes: `/opt/stack/volumes/nfl-cache` and `cfb-cache`, copied over from Azure Files by `bin/pull-azure-volumes.sh`.
  - The Task 8 deploy check is `curl https://nfl.<domain>/api/kalshi-feed` and `https://cfb.<domain>/api/kalshi-feed`.
  - Don't add or change any Azure step. The Azure steps in those workflows are disabled at cutover (`vps-stack/bin/set-github-secrets.sh --disable-azure`), and an Azure check is acceptable only as an interim check while the VPS isn't serving yet.
  - **Azure is legacy.** The predictor sites still run there until the cutover (Azure for Students credit ends around **2026-10-27**). After that no Azure host exists, so nothing may depend on an `*.azurecontainerapps.io` URL beyond it.

## Global Constraints

- **Repos:** `/Users/sigey/Documents/Projects.nosync/NFL_Predictor` (Tasks 1–4) and `/Users/sigey/Documents/Projects.nosync/CFB_Predictor` (Tasks 5–7); Task 8 touches both. No other repo.
- **Branch per repo:** `plan/2026-09-25-kalshi-feed`, created from `main`. Both checkouts currently carry an uncommitted `.github/workflows/deploy-azure-*.yml` change from the VPS migration: do not stage, stash, reset or commit it (`git add` only the paths each task names).
- **Test command (from each repo root):** `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` (the package is not pip-installed in `.venv`). Baselines at `NFL_Predictor@3c16861`: 111 passed; `CFB_Predictor@f88fc05`: 128 passed.
- **The feed never recomputes a prediction.** It reads `game_predictions` only. A row is served only if `backfilled = 0`, `resolved = 0`, `snapshotted_at < commence_time` and `commence_time > now`.
- **Backfilled rows are graded but never "pre-game".** `record_resolved_game_predictions` sets `backfilled = 1`; calibration buckets skip them; `/api/track-record` keeps its numbers and adds `n_backfilled`.
- **Snapshot policy:** first snapshot inside `SNAPSHOT_LEAD_HOURS` (env, default `48`) before kickoff wins and is kept forever (existing `INSERT OR IGNORE`).
- **Feed JSON contract** (the hub's `tradehub/sports/feed.py` parses exactly this): `{"sport", "generated_at", "lead_hours", "games": [{"game_id", "season", "week", "home", "away", "start_utc", "p_home", "margin_mu", "sigma", "total_mu", "total_sigma", "home_spread_line", "total_line", "model_version", "snapshotted_at", "backfilled": false}], "calibration": {"n_buckets": 10, "winner": [...], "spread": [...], "total": [...]}}`, bucket = `{"lo", "hi", "n", "mean_prob", "hit_rate"}`. Timestamps are ISO 8601 with `+00:00`.
- **No new dependencies; no secrets** in code or tests; never push. Deploying is Kevin's step (Task 8).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Handoff contract (hub rollout tracker): one commit per task, evidence report at `docs/superpowers/reports/2026-09-25-predictor-pregame-feed.md` in each repo, stop and record instead of improvising.

## Validation already done (2026-09-25)

Every task below was implemented exactly as written in scratch worktrees (`NFL_Predictor@3c16861`, `CFB_Predictor@f88fc05`); each RED step failed as stated and each GREEN step passed:
- **NFL:** 111 → **129 passed** (18 new tests). **CFB:** 128 → **144 passed** (16 new tests).
- **Local end-to-end smoke** (fresh tracking DB, real schedules and models, tick then `GET /api/kalshi-feed`):
  - NFL (`SNAPSHOT_LEAD_HOURS=96`, since no NFL game kicks off within 48 h of the 05:40Z Friday run): the tick took 10 s; the feed served **15** week-3 games with `margin_mu`, `sigma`, `total_mu`, `total_sigma` and `model_version` (`ridge@2026-09-04T22:12:49.750941+00:00`). The same tick backfilled **33** already-played games, and all 33 were flagged `backfilled=1`, so the calibration buckets were empty (n = 0), as intended for a fresh DB.
  - CFB (default 48 h, local copy of the CFBD cache, sportsbook odds stubbed because no keys were used): the tick took 109 s (most of it backfilling), and the feed served **70** games. **260** already-played games were backfilled and flagged.
- **Live evidence behind the design:**
  - Live NFL `/api/predictions/2026/4/batch` returns **500**. Cause: `data/public_snapshot.json` holds `NaN` cover/over probabilities for games whose `spread_line` is NaN (weeks 4–18 on GitHub main). Task 4 fixes both the source and the serving path.
  - Live `/api/track-record`: NFL 33 resolved, CFB 261 resolved. The local replay suggests most of those were backfilled, not tracked pre-game: CFB backfilled 260 locally against 261 live resolved.
- **Hub consumption:** the hub plan's adapter parsed both local feeds and matched **15/15** NFL and **70/70** CFB games to open Kalshi events (see the hub plan).
- **Not verified here:** a deploy (Kevin's step), and the production tracking DBs, which live on the Azure/VPS volumes and were not read.

## Review Focus

- `_flag_legacy_backfills` must run once, only when the `backfilled` column is first added, and must `commit()` itself: `_connect()` is also used without `with conn`, and an uncommitted UPDATE would be rolled back on close. (Tasks 1, 5)
- Classification rule: `record_game_predictions` only ever wrote rows with `snapshotted_at < commence_time` (as stored), so a legacy row at or after it can only be a backfill. This holds even for NFL rows written before `3c16861`, whose `commence_time` is date-only midnight UTC (earlier than the real kickoff). (Tasks 1, 5)
- The lead window filters only on the upper bound (`kickoff <= now + lead`); past games still reach `record_game_predictions`, which rejects them itself. The existing tick test depends on this. (Tasks 2, 6)
- `/api/kalshi-feed` must not call schedules, models or the network. (Tasks 3, 7)

## Why these design choices

- **Frozen first snapshot, not the latest one.** The hub has to trade on the same series of predictions that its calibration check grades. The live `/batch` is recomputed (ATL@GB was tracked pre-game at 0.594, and the batch shows 0.684 now), so it cannot be trusted for either.
- **48 h lead window across two weeks.** `current_season_and_week()` anchors on the date of week 1's first kickoff. Since `3c16861` that is a UTC date (NFL: Friday 2026-09-11), so each NFL "week" now starts on Friday: Thursday-night games would be snapshotted only after kickoff and then rejected, and never tracked. CFB weeks roll over on Saturday, so week-N+1 games were frozen on the previous Saturday, before that day's results. A per-game lead window fixes both, and 48 h still lands after Monday Night Football for Thursday games.
- **Calibration exposed by the feed, not by `/track-record`.** The public track-record shape is used by the Sports_Predictor frontend and stays unchanged apart from `n_backfilled`.

---

## File Structure

**NFL_Predictor**
- Modify `src/nfl_predictor/tracking/store.py`: feed columns, the `backfilled` flag and legacy classification, `get_feed_predictions()`, `get_calibration()`, `n_backfilled`. (Task 1)
- Modify `src/nfl_predictor/models/manifest.py`: `model_version()`, and `load_models()` returns it. (Task 2)
- Modify `src/nfl_predictor/api/routes.py`: `SNAPSHOT_LEAD_HOURS`, `_games_to_snapshot()`, the tick uses it, `model_version` in predictions (Task 2); `GET /api/kalshi-feed` (Task 3); `_json_safe()` on snapshot serving (Task 4).
- Modify `src/nfl_predictor/models/game_outcome.py`: NaN lines are treated as missing. (Task 4)
- Tests: `tests/test_kalshi_feed_store.py` (T1), `tests/test_snapshot_window.py` (T2), `tests/test_kalshi_feed_api.py` (T3), `tests/test_missing_lines.py` (T4).

**CFB_Predictor**: the same shape: `tracking/store.py` (T5), `models/manifest.py` + `api/routes.py` (T6), `api/routes.py` feed endpoint (T7); tests `tests/test_kalshi_feed_store.py`, `tests/test_snapshot_window.py`, `tests/test_kalshi_feed_api.py`. CFB's remote public snapshot has no NaN, so it needs no Task 4 equivalent.

**Both:** `docs/superpowers/reports/2026-09-25-predictor-pregame-feed.md` (Task 8).

---

## Task 1: NFL store: distribution columns, backfilled flag, feed rows, calibration

**Files:**
- Modify: `src/nfl_predictor/tracking/store.py`
- Test: `tests/test_kalshi_feed_store.py` (new)

**Interfaces:**
- Consumes: the existing `game_predictions` table, `record_game_predictions(games)`, `record_resolved_game_predictions(games)`, `reconcile_game_predictions(df)`, `get_track_record()`.
- Produces:
  - `store.get_feed_predictions(now: datetime | None = None) -> list[dict]`: rows in the feed contract's `games` shape, sorted by `(start_utc, game_id)`.
  - `store.get_calibration(n_buckets: int = 10) -> dict`: `{"n_buckets", "winner", "spread", "total"}`.
  - New nullable columns `predicted_margin, sigma, predicted_total, total_sigma` (REAL), `model_version` (TEXT), and `backfilled INTEGER NOT NULL DEFAULT 0`. Game dicts passed to both `record_*` functions may carry the five distribution keys.
  - `get_track_record()["games"]["n_backfilled"]: int`.

- [ ] **Step 1: Write the failing tests**: `tests/test_kalshi_feed_store.py`:

```python
import contextlib
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import pytest

from nfl_predictor.tracking import store

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    from nfl_predictor import config

    db_path = tmp_path / "tracking.db"
    monkeypatch.setattr(config, "TRACKING_DB_PATH", db_path)
    monkeypatch.setattr(store, "TRACKING_DB_PATH", db_path)
    yield


def _upcoming(**overrides):
    game = {
        "game_id": "2026_03_BAL_DAL", "home_team": "DAL", "away_team": "BAL",
        "commence_time": "2099-09-27 20:25:00", "season": 2026, "week": 3,
        "home_win_prob": 0.41, "away_win_prob": 0.59,
        "home_cover_prob": 0.47, "away_cover_prob": 0.53, "over_prob": 0.52, "under_prob": 0.48,
        "home_spread_line": -2.5, "total_line": 47.5,
        "predicted_margin": -2.9, "sigma": 13.2, "predicted_total": 48.1, "total_sigma": 12.5,
        "model_version": "xgb@2026-09-04T22:12:49+00:00",
    }
    game.update(overrides)
    return game


def _finished(**overrides):
    game = _upcoming(game_id="2026_02_NYJ_BUF", home_team="BUF", away_team="NYJ",
                     commence_time="2026-09-20 17:00:00", home_win_prob=0.7, away_win_prob=0.3,
                     actual_home_score=30, actual_away_score=10)
    game.update(overrides)
    return game


def test_record_game_predictions_persists_feed_fields_and_is_not_backfilled():
    store.record_game_predictions([_upcoming()])

    with contextlib.closing(store._connect()) as conn:
        row = pd.read_sql("SELECT * FROM game_predictions", conn).iloc[0]

    assert row["predicted_margin"] == pytest.approx(-2.9)
    assert row["sigma"] == pytest.approx(13.2)
    assert row["predicted_total"] == pytest.approx(48.1)
    assert row["total_sigma"] == pytest.approx(12.5)
    assert row["model_version"] == "xgb@2026-09-04T22:12:49+00:00"
    assert row["backfilled"] == 0


def test_record_resolved_game_predictions_flags_backfilled():
    store.record_resolved_game_predictions([_finished()])

    with contextlib.closing(store._connect()) as conn:
        row = pd.read_sql("SELECT * FROM game_predictions", conn).iloc[0]

    assert row["backfilled"] == 1
    assert row["resolved"] == 1


def test_legacy_rows_are_classified_when_backfilled_column_is_added():
    """A database created before this change has no backfilled column. Rows
    whose snapshot was taken at or after kickoff can only have come from
    record_resolved_game_predictions, so they are flagged on migration."""
    conn = sqlite3.connect(str(store.TRACKING_DB_PATH))
    conn.execute(
        """CREATE TABLE game_predictions (
            game_id TEXT PRIMARY KEY, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
            commence_time TEXT NOT NULL, snapshotted_at TEXT NOT NULL,
            home_win_prob REAL NOT NULL, away_win_prob REAL NOT NULL,
            home_cover_prob REAL, away_cover_prob REAL, over_prob REAL, under_prob REAL,
            resolved INTEGER NOT NULL DEFAULT 0, actual_home_score INTEGER, actual_away_score INTEGER,
            moneyline_hit INTEGER)"""
    )
    conn.executemany(
        "INSERT INTO game_predictions (game_id, home_team, away_team, commence_time, snapshotted_at,"
        " home_win_prob, away_win_prob, resolved) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        [
            ("pregame", "DAL", "BAL", "2026-09-13 00:00:00", "2026-09-12T15:00:00+00:00", 0.6, 0.4),
            ("backfill", "BUF", "NYJ", "2026-09-13 00:00:00", "2026-09-24T02:00:00+00:00", 0.6, 0.4),
        ],
    )
    conn.commit()
    conn.close()

    with contextlib.closing(store._connect()) as conn:
        flags = dict(conn.execute("SELECT game_id, backfilled FROM game_predictions").fetchall())

    assert flags == {"pregame": 0, "backfill": 1}


def test_feed_predictions_returns_only_upcoming_pregame_rows():
    store.record_game_predictions([_upcoming()])
    store.record_resolved_game_predictions([_finished()])

    rows = store.get_feed_predictions(now=NOW)

    assert [r["game_id"] for r in rows] == ["2026_03_BAL_DAL"]
    row = rows[0]
    assert row["home"] == "DAL" and row["away"] == "BAL"
    assert row["start_utc"] == "2099-09-27T20:25:00+00:00"
    assert row["p_home"] == pytest.approx(0.41)
    assert row["margin_mu"] == pytest.approx(-2.9) and row["sigma"] == pytest.approx(13.2)
    assert row["total_mu"] == pytest.approx(48.1) and row["total_sigma"] == pytest.approx(12.5)
    assert row["model_version"] == "xgb@2026-09-04T22:12:49+00:00"
    assert row["backfilled"] is False
    assert datetime.fromisoformat(row["snapshotted_at"]) < datetime.fromisoformat(row["start_utc"])


def test_feed_predictions_drop_games_that_have_started():
    store.record_game_predictions([_upcoming()])

    assert store.get_feed_predictions(now=datetime(2100, 1, 1, tzinfo=timezone.utc)) == []


def test_feed_predictions_keep_null_distribution_fields_as_none():
    legacy = _upcoming()
    for key in ("predicted_margin", "sigma", "predicted_total", "total_sigma", "model_version"):
        legacy.pop(key)
    store.record_game_predictions([legacy])

    row = store.get_feed_predictions(now=NOW)[0]

    assert row["margin_mu"] is None and row["sigma"] is None
    assert row["total_mu"] is None and row["model_version"] is None


def test_calibration_uses_only_pregame_resolved_rows():
    store.record_game_predictions([
        _upcoming(game_id=f"g{i}", home_win_prob=0.65, away_win_prob=0.35) for i in range(4)
    ])
    store.reconcile_game_predictions(pd.DataFrame([
        {"game_id": "g0", "home_score": 24, "away_score": 17},
        {"game_id": "g1", "home_score": 24, "away_score": 17},
        {"game_id": "g2", "home_score": 24, "away_score": 17},
        {"game_id": "g3", "home_score": 10, "away_score": 17},
    ]))
    # A backfilled 0.65 miss must not count.
    store.record_resolved_game_predictions([
        _finished(game_id="bf", home_win_prob=0.65, away_win_prob=0.35, actual_home_score=0, actual_away_score=7)
    ])

    calibration = store.get_calibration()

    bucket = next(b for b in calibration["winner"] if b["lo"] == 0.6)
    assert bucket == {"lo": 0.6, "hi": 0.7, "n": 4, "mean_prob": pytest.approx(0.65), "hit_rate": 0.75}
    assert len(calibration["winner"]) == 10
    empty = next(b for b in calibration["winner"] if b["lo"] == 0.1)
    assert empty == {"lo": 0.1, "hi": 0.2, "n": 0, "mean_prob": None, "hit_rate": None}


def test_calibration_grades_spread_and_total_against_recorded_lines():
    store.record_game_predictions([_upcoming(game_id="s1", home_spread_line=3.0, home_cover_prob=0.55,
                                             total_line=40.0, over_prob=0.35)])
    store.reconcile_game_predictions(pd.DataFrame([{"game_id": "s1", "home_score": 27, "away_score": 20}]))

    calibration = store.get_calibration()

    spread = next(b for b in calibration["spread"] if b["lo"] == 0.5)
    total = next(b for b in calibration["total"] if b["lo"] == 0.3)
    assert (spread["n"], spread["hit_rate"]) == (1, 1.0)   # margin 7 > 3
    assert (total["n"], total["hit_rate"]) == (1, 1.0)     # 47 > 40


def test_track_record_reports_backfilled_count():
    store.record_resolved_game_predictions([_finished()])

    games = store.get_track_record()["games"]

    assert games["n_resolved"] == 1
    assert games["n_backfilled"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_store.py`
Expected: `9 failed` (`KeyError: 'predicted_margin'`, `AttributeError: ... has no attribute 'get_feed_predictions'`, and similar).

- [ ] **Step 3: Implement** in `src/nfl_predictor/tracking/store.py`, as six replacements.

(a) Schema migration at the end of `_connect()`'s `game_predictions` column loop:

Replace this block:

```python
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(game_predictions)")}
    for column in ("home_spread_line", "total_line", "ats_hit", "total_hit", "season", "week"):
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} REAL" if column in ("home_spread_line", "total_line")
                         else f"ALTER TABLE game_predictions ADD COLUMN {column} INTEGER")
```

with:

```python
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(game_predictions)")}
    for column in ("home_spread_line", "total_line", "ats_hit", "total_hit", "season", "week"):
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} REAL" if column in ("home_spread_line", "total_line")
                         else f"ALTER TABLE game_predictions ADD COLUMN {column} INTEGER")
    # Kalshi feed: the predicted distribution behind each frozen snapshot,
    # plus whether the row was backfilled after the game was already over.
    for column, sql_type in _FEED_COLUMNS.items():
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} {sql_type}")
    if "backfilled" not in existing_cols:
        conn.execute("ALTER TABLE game_predictions ADD COLUMN backfilled INTEGER NOT NULL DEFAULT 0")
        _flag_legacy_backfills(conn)
```

(b) Helpers, inserted directly above `_require_pre_kickoff`:

Replace this block:

```python
def _require_pre_kickoff(commence_time: str) -> None:
```

with:

```python
_FEED_COLUMNS = {
    "predicted_margin": "REAL",
    "sigma": "REAL",
    "predicted_total": "REAL",
    "total_sigma": "REAL",
    "model_version": "TEXT",
}


def _parse_utc(value: str) -> datetime:
    """ISO timestamp -> aware UTC datetime. Naive values are UTC (that is how
    both commence_time and snapshotted_at are written)."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_is_pregame(snapshotted_at: str, commence_time: str) -> bool:
    try:
        return _parse_utc(snapshotted_at) < _parse_utc(commence_time)
    except (TypeError, ValueError):
        return False


def _flag_legacy_backfills(conn: sqlite3.Connection) -> None:
    """One-time classification when the backfilled column is first added.
    record_game_predictions only ever writes rows snapshotted before the
    stored commence_time (_require_pre_kickoff), so a row snapshotted at or
    after it can only have come from record_resolved_game_predictions."""
    rows = conn.execute("SELECT game_id, snapshotted_at, commence_time FROM game_predictions").fetchall()
    backfilled = [(game_id,) for game_id, snap, start in rows if not _snapshot_is_pregame(snap, start)]
    conn.executemany("UPDATE game_predictions SET backfilled = 1 WHERE game_id = ?", backfilled)
    conn.commit()


def _optional_float(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _require_pre_kickoff(commence_time: str) -> None:
```

(c) `record_game_predictions` persists the distribution and writes `backfilled = 0`:

Replace this block:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
        )
        for game in valid_games
    ]
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
```

with:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            game.get("predicted_margin"), game.get("sigma"), game.get("predicted_total"), game.get("total_sigma"),
            game.get("model_version"),
        )
        for game in valid_games
    ]
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 predicted_margin, sigma, predicted_total, total_sigma, model_version, backfilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
```

(d) `record_resolved_game_predictions` writes `backfilled = 1`:

Replace this block:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            1, int(game["actual_home_score"]), int(game["actual_away_score"]), moneyline_hit, ats_hit, total_hit,
        ))
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 resolved, actual_home_score, actual_away_score, moneyline_hit, ats_hit, total_hit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
```

with:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            1, int(game["actual_home_score"]), int(game["actual_away_score"]), moneyline_hit, ats_hit, total_hit,
            game.get("predicted_margin"), game.get("sigma"), game.get("predicted_total"), game.get("total_sigma"),
            game.get("model_version"),
        ))
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 resolved, actual_home_score, actual_away_score, moneyline_hit, ats_hit, total_hit,
                 predicted_margin, sigma, predicted_total, total_sigma, model_version, backfilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
```

(e) `n_backfilled` in the games summary (two blocks):

Replace this block:

```python
            "n_resolved": 0, "pct_moneyline_correct": None, "pct_ats_correct": None,
            "pct_totals_correct": None, "weekly_trend": [],
        }
```

with:

```python
            "n_resolved": 0, "n_backfilled": 0, "pct_moneyline_correct": None, "pct_ats_correct": None,
            "pct_totals_correct": None, "weekly_trend": [],
        }
```

Replace this block:

```python
    return {
        "n_resolved": int(len(resolved)),
        "pct_moneyline_correct": float(resolved["moneyline_hit"].mean()),
```

with:

```python
    return {
        "n_resolved": int(len(resolved)),
        # Rows written after the game was over (record_resolved_game_predictions):
        # graded like the rest, but never a live pre-game call.
        "n_backfilled": int((resolved["backfilled"] == 1).sum()),
        "pct_moneyline_correct": float(resolved["moneyline_hit"].mean()),
```

(f) The feed and calibration readers, inserted directly above `_summarize_games`:

Replace this block:

```python
def _summarize_games(resolved: pd.DataFrame) -> dict:
```

with:

```python
def get_feed_predictions(now: datetime | None = None) -> list[dict]:
    """Frozen pre-game snapshots for games that have not started yet: the
    rows the trade hub may compare against Kalshi prices. Backfilled rows
    and any row not snapshotted strictly before kickoff are excluded."""
    now = now or datetime.now(timezone.utc)
    with contextlib.closing(_connect()) as conn:
        rows = pd.read_sql("SELECT * FROM game_predictions WHERE resolved = 0 AND backfilled = 0", conn)
    feed = []
    for _, row in rows.iterrows():
        try:
            start = _parse_utc(row["commence_time"])
            snapshotted = _parse_utc(row["snapshotted_at"])
        except (TypeError, ValueError):
            continue
        if start <= now or snapshotted >= start:
            continue
        feed.append({
            "game_id": row["game_id"],
            "season": None if pd.isna(row["season"]) else int(row["season"]),
            "week": None if pd.isna(row["week"]) else int(row["week"]),
            "home": row["home_team"],
            "away": row["away_team"],
            "start_utc": start.isoformat(),
            "p_home": float(row["home_win_prob"]),
            "margin_mu": _optional_float(row["predicted_margin"]),
            "sigma": _optional_float(row["sigma"]),
            "total_mu": _optional_float(row["predicted_total"]),
            "total_sigma": _optional_float(row["total_sigma"]),
            "home_spread_line": _optional_float(row["home_spread_line"]),
            "total_line": _optional_float(row["total_line"]),
            "model_version": row["model_version"] if isinstance(row["model_version"], str) else None,
            "snapshotted_at": snapshotted.isoformat(),
            "backfilled": False,
        })
    return sorted(feed, key=lambda r: (r["start_utc"], r["game_id"]))


def _calibration_buckets(pairs: list[tuple[float, int]], n_buckets: int) -> list[dict]:
    buckets = []
    for i in range(n_buckets):
        lo, hi = i / n_buckets, (i + 1) / n_buckets
        last = i == n_buckets - 1
        inside = [(p, y) for p, y in pairs if lo <= p < hi or (last and p == 1.0)]
        buckets.append({
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "n": len(inside),
            "mean_prob": sum(p for p, _ in inside) / len(inside) if inside else None,
            "hit_rate": sum(y for _, y in inside) / len(inside) if inside else None,
        })
    return buckets


def get_calibration(n_buckets: int = 10) -> dict:
    """Reliability buckets over resolved, genuinely pre-game snapshots:
    home win probability vs home won, home cover probability vs covered
    (at the recorded line), over probability vs went over. Ties and pushes
    are left out."""
    with contextlib.closing(_connect()) as conn:
        rows = pd.read_sql("SELECT * FROM game_predictions WHERE resolved = 1 AND backfilled = 0", conn)
    winner: list[tuple[float, int]] = []
    spread: list[tuple[float, int]] = []
    total: list[tuple[float, int]] = []
    for _, row in rows.iterrows():
        if not _snapshot_is_pregame(row["snapshotted_at"], row["commence_time"]):
            continue
        home, away = row["actual_home_score"], row["actual_away_score"]
        if pd.isna(home) or pd.isna(away):
            continue
        margin, points = float(home - away), float(home + away)
        if margin != 0:
            winner.append((float(row["home_win_prob"]), int(margin > 0)))
        line, prob = row["home_spread_line"], row["home_cover_prob"]
        if pd.notna(line) and pd.notna(prob) and margin != float(line):
            spread.append((float(prob), int(margin > float(line))))
        line, prob = row["total_line"], row["over_prob"]
        if pd.notna(line) and pd.notna(prob) and points != float(line):
            total.append((float(prob), int(points > float(line))))
    return {
        "n_buckets": n_buckets,
        "winner": _calibration_buckets(winner, n_buckets),
        "spread": _calibration_buckets(spread, n_buckets),
        "total": _calibration_buckets(total, n_buckets),
    }


def _summarize_games(resolved: pd.DataFrame) -> dict:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_store.py` → Expected: `9 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `120 passed`

- [ ] **Step 5: Commit**

```bash
git checkout -b plan/2026-09-25-kalshi-feed
git add src/nfl_predictor/tracking/store.py tests/test_kalshi_feed_store.py
git commit -m "feat(tracking): store snapshot distributions, flag backfills, feed + calibration readers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: NFL: freeze snapshots inside a 48 h lead window (this week + next) and record `model_version`

**Files:**
- Modify: `src/nfl_predictor/models/manifest.py`, `src/nfl_predictor/api/routes.py`
- Test: `tests/test_snapshot_window.py` (new)

**Interfaces:**
- Consumes: `schedules.fetch_upcoming_games(season, week)`; `store.record_game_predictions` (Task 1 accepts the distribution keys).
- Produces:
  - `manifest.model_version(manifest: dict) -> str`, giving `"<chosen_candidate>@<trained_at>"`; `load_models()["model_version"]`.
  - `routes.SNAPSHOT_LEAD_HOURS: float` (env `SNAPSHOT_LEAD_HOURS`, default 48).
  - `routes._games_to_snapshot(season, week, now, lead_hours=None) -> pd.DataFrame`.
  - `_predict_game_from_models(...)["model_version"]`.
  - Each tick prediction dict carries the game's own `week`.

- [ ] **Step 1: Write the failing tests**: `tests/test_snapshot_window.py`:

```python
from datetime import datetime, timedelta, timezone

import pandas as pd

from nfl_predictor.api import routes
from nfl_predictor.models import manifest

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _game(game_id, week, hours_from_now):
    kickoff = (NOW + timedelta(hours=hours_from_now)).replace(tzinfo=None)
    return {"game_id": game_id, "season": 2026, "week": week, "gameday": pd.Timestamp(kickoff),
            "home_team": "CLE", "away_team": "PIT", "home_score": None, "away_score": None,
            "spread_line": -3.0, "total_line": 38.5}


def test_games_to_snapshot_takes_both_weeks_but_only_inside_the_lead_window(monkeypatch):
    weeks = {
        3: pd.DataFrame([_game("in_window", 3, 24), _game("too_early", 3, 100)]),
        4: pd.DataFrame([_game("next_week_soon", 4, 30), _game("next_week_later", 4, 200)]),
    }
    monkeypatch.setattr(routes.schedules, "fetch_upcoming_games", lambda season, week: weeks.get(week, pd.DataFrame()))

    games = routes._games_to_snapshot(2026, 3, NOW, lead_hours=48)

    assert list(games["game_id"]) == ["in_window", "next_week_soon"]


def test_games_to_snapshot_handles_an_empty_next_week(monkeypatch):
    weeks = {3: pd.DataFrame([_game("in_window", 3, 24)])}
    monkeypatch.setattr(routes.schedules, "fetch_upcoming_games", lambda season, week: weeks.get(week, pd.DataFrame()))

    games = routes._games_to_snapshot(2026, 3, NOW, lead_hours=48)

    assert list(games["game_id"]) == ["in_window"]


def test_tracking_tick_records_distribution_and_each_games_own_week(monkeypatch):
    recorded = []
    monkeypatch.setattr(routes, "_games_to_snapshot", lambda season, week, now, lead_hours=None: pd.DataFrame(
        [_game("2026_04_PIT_CLE", 4, 30)]))
    monkeypatch.setattr(routes, "_load_models_cached", lambda: {"model_version": "xgb@t"})
    monkeypatch.setattr(routes, "_load_game_history", lambda season: pd.DataFrame())
    monkeypatch.setattr(routes, "_predict_game_from_models", lambda *a, **k: {
        "home_win_prob": 0.4, "away_win_prob": 0.6, "predicted_margin": -3.4, "sigma": 13.2,
        "predicted_total": 39.8, "total_sigma": 12.5, "model_version": "xgb@t",
    })
    monkeypatch.setattr(routes.store, "record_game_predictions", lambda games: recorded.extend(games) or len(games))
    monkeypatch.setattr(routes, "_get_player_props_live", lambda season, week: [])
    monkeypatch.setattr(routes.store, "record_player_prop_predictions", lambda rows: 0)
    monkeypatch.setattr(routes.schedules, "fetch_current_season_partial",
                        lambda: pd.DataFrame(columns=["game_id", "home_score", "away_score"]))
    monkeypatch.setattr(routes.store, "reconcile_game_predictions", lambda df: 0)
    monkeypatch.setattr(routes.store, "backfill_unresolved_games", lambda module: 0)

    routes.background_tracking_tick(season=2026, week=3)

    assert len(recorded) == 1
    row = recorded[0]
    assert row["week"] == 4
    assert row["commence_time"] == str(_game("x", 4, 30)["gameday"])
    assert row["predicted_margin"] == -3.4 and row["sigma"] == 13.2
    assert row["model_version"] == "xgb@t"


def test_predict_game_from_models_reports_model_version(monkeypatch):
    class _FakeTotalModel:
        def predict(self, _X):
            return [45.0]

    monkeypatch.setattr(
        routes.feature_build, "build_features_for_game",
        lambda home, away, games_df: pd.Series({"rating_diff": 50.0, "home_rest_days": 7.0, "away_rest_days": 7.0}),
    )
    models = {
        "feature_cols": ["rating_diff", "home_rest_days", "away_rest_days"],
        "chosen_candidate": "elo", "sigma": 12.0, "total_sigma": 10.0,
        "total_model": _FakeTotalModel(), "model_version": "elo@2026-09-04T22:12:49+00:00",
    }

    result = routes._predict_game_from_models(models, "KC", "BAL", pd.DataFrame())

    assert result["model_version"] == "elo@2026-09-04T22:12:49+00:00"


def test_model_version_combines_candidate_and_training_time():
    assert manifest.model_version(
        {"chosen_candidate": "xgb", "trained_at": "2026-09-04T22:12:49.750941+00:00"}
    ) == "xgb@2026-09-04T22:12:49.750941+00:00"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_snapshot_window.py`
Expected: `5 failed` (`AttributeError: module 'nfl_predictor.api.routes' has no attribute '_games_to_snapshot'`, `KeyError: 'model_version'`, `AttributeError: ... has no attribute 'model_version'`).

- [ ] **Step 3: Implement**

`src/nfl_predictor/models/manifest.py`:

Replace this block:

```python
def load_models() -> dict:
    """Load all saved artifacts and their feature metadata."""
    manifest = load_manifest()
```

with:

```python
def model_version(manifest: dict) -> str:
    """Identifies the trained model behind a prediction: candidate + training time."""
    return f"{manifest['chosen_candidate']}@{manifest['trained_at']}"


def load_models() -> dict:
    """Load all saved artifacts and their feature metadata."""
    manifest = load_manifest()
```

Replace this block:

```python
        "chosen_candidate": manifest["chosen_candidate"],
        "sigma": manifest["sigma"],
```

with:

```python
        "chosen_candidate": manifest["chosen_candidate"],
        "model_version": model_version(manifest),
        "sigma": manifest["sigma"],
```

`src/nfl_predictor/api/routes.py`, imports:

Replace this block:

```python
import json
import logging
from datetime import date
from functools import lru_cache
```

with:

```python
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
```

`_predict_game_from_models` returns the version:

Replace this block:

```python
    result["sigma"] = models["sigma"]
    result["total_sigma"] = models["total_sigma"]
    return result
```

with:

```python
    result["sigma"] = models["sigma"]
    result["total_sigma"] = models["total_sigma"]
    result["model_version"] = models.get("model_version")
    return result
```

The lead window, and the tick uses it:

Replace this block:

```python
def background_tracking_tick(season: int, week: int) -> None:
    """Snapshot this week's upcoming-game (and player-prop) predictions,
    then reconcile anything now resolved. Called on a timer from
    api/main.py's lifespan the same way PL_Predictor's own
    background_tracking_tick is."""
    games = schedules.fetch_upcoming_games(season, week)
    if not games.empty:
```

with:

```python
# How close to kickoff a game's prediction is frozen. The first snapshot
# inside this window is kept forever (INSERT OR IGNORE), so it is the one the
# track record grades and the Kalshi feed serves. 48h lands after the prior
# week's Monday night game for every slot (Thu/Sat/Sun/Mon).
SNAPSHOT_LEAD_HOURS = float(os.getenv("SNAPSHOT_LEAD_HOURS", "48"))


def _games_to_snapshot(season: int, week: int, now: datetime, lead_hours: float | None = None) -> pd.DataFrame:
    """Upcoming games from this week and next whose kickoff is within the
    lead window. Next week is included because current_season_and_week()
    rolls over on the UTC date of week 1's first kickoff (a Friday), which
    would otherwise leave Thursday night games out until after kickoff."""
    lead = timedelta(hours=SNAPSHOT_LEAD_HOURS if lead_hours is None else lead_hours)
    frames = [f for f in (schedules.fetch_upcoming_games(season, wk) for wk in (week, week + 1)) if not f.empty]
    if not frames:
        return pd.DataFrame()
    games = pd.concat(frames, ignore_index=True)
    kickoff = pd.to_datetime(games["gameday"], utc=True, errors="coerce")
    horizon = pd.Timestamp(now + lead)
    return games[kickoff.notna() & (kickoff <= horizon)].drop_duplicates("game_id").reset_index(drop=True)


def background_tracking_tick(season: int, week: int) -> None:
    """Snapshot upcoming-game (and player-prop) predictions inside the lead
    window, then reconcile anything now resolved. Called on a timer from
    api/main.py's lifespan the same way PL_Predictor's own
    background_tracking_tick is."""
    games = _games_to_snapshot(season, week, datetime.now(timezone.utc))
    if not games.empty:
```

Each game's own week (next-week games must not be labelled with the current week):

Replace this block:

```python
                predictions.append(
                    {
                        "game_id": game["game_id"], "home_team": game["home_team"], "away_team": game["away_team"],
                        "commence_time": str(game["gameday"]), "season": season, "week": week,
                        "home_spread_line": game.get("spread_line"), "total_line": game.get("total_line"),
                        **pred,
                    }
                )
```

with:

```python
                predictions.append(
                    {
                        "game_id": game["game_id"], "home_team": game["home_team"], "away_team": game["away_team"],
                        "commence_time": str(game["gameday"]), "season": season,
                        "week": int(game["week"]) if pd.notna(game.get("week")) else week,
                        "home_spread_line": game.get("spread_line"), "total_line": game.get("total_line"),
                        **pred,
                    }
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_snapshot_window.py tests/test_background_tracking.py` → Expected: `6 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `125 passed`

- [ ] **Step 5: Commit**

```bash
git add src/nfl_predictor/models/manifest.py src/nfl_predictor/api/routes.py tests/test_snapshot_window.py
git commit -m "feat(tracking): freeze snapshots 48h before kickoff across this and next week; record model_version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: NFL `GET /api/kalshi-feed`

**Files:**
- Modify: `src/nfl_predictor/api/routes.py`
- Test: `tests/test_kalshi_feed_api.py` (new)

**Interfaces:**
- Consumes: `store.get_feed_predictions()`, `store.get_calibration()` (Task 1), `SNAPSHOT_LEAD_HOURS` (Task 2).
- Produces: `GET /api/kalshi-feed`, returning the feed contract in Global Constraints with `"sport": "nfl"`.

- [ ] **Step 1: Write the failing tests**: `tests/test_kalshi_feed_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from nfl_predictor.api.main import app
from nfl_predictor.tracking import store


@pytest.fixture
def client(monkeypatch, tmp_path):
    from nfl_predictor import config

    db_path = tmp_path / "tracking.db"
    monkeypatch.setattr(config, "TRACKING_DB_PATH", db_path)
    monkeypatch.setattr(store, "TRACKING_DB_PATH", db_path)
    return TestClient(app)


def test_kalshi_feed_serves_frozen_pregame_rows_and_calibration(client):
    store.record_game_predictions([{
        "game_id": "2026_04_PIT_CLE", "home_team": "CLE", "away_team": "PIT",
        "commence_time": "2099-10-02 00:15:00", "season": 2026, "week": 4,
        "home_win_prob": 0.40, "away_win_prob": 0.60, "predicted_margin": -3.4, "sigma": 13.2,
        "predicted_total": 39.8, "total_sigma": 12.5, "model_version": "xgb@t",
    }])

    response = client.get("/api/kalshi-feed")

    assert response.status_code == 200
    body = response.json()
    assert body["sport"] == "nfl"
    assert body["lead_hours"] == 48
    assert [g["game_id"] for g in body["games"]] == ["2026_04_PIT_CLE"]
    game = body["games"][0]
    assert game["start_utc"] == "2099-10-02T00:15:00+00:00"
    assert game["p_home"] == 0.40 and game["margin_mu"] == -3.4 and game["backfilled"] is False
    assert set(body["calibration"]) == {"n_buckets", "winner", "spread", "total"}
    assert body["generated_at"].endswith("+00:00")


def test_kalshi_feed_is_empty_but_valid_with_no_snapshots(client):
    body = client.get("/api/kalshi-feed").json()

    assert body["games"] == []
    assert body["calibration"]["winner"][0] == {"lo": 0.0, "hi": 0.1, "n": 0, "mean_prob": None, "hit_rate": None}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_api.py`
Expected: `2 failed` (`assert 404 == 200`, then `KeyError: 'games'`).

- [ ] **Step 3: Implement**: add the route directly above `get_game_verdict`:

Replace this block:

```python
@router.get("/games/{game_id}/verdict")
```

with:

```python
@router.get("/kalshi-feed")
def get_kalshi_feed():
    """Read-only feed for the Algo Trade Hub: frozen pre-game snapshots for
    games that have not kicked off, plus reliability buckets over graded
    pre-game snapshots. Served from the tracking database only, so it
    never recomputes a prediction."""
    return {
        "sport": "nfl",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lead_hours": SNAPSHOT_LEAD_HOURS,
        "games": store.get_feed_predictions(),
        "calibration": store.get_calibration(),
    }


@router.get("/games/{game_id}/verdict")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_api.py` → Expected: `2 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `127 passed`

- [ ] **Step 5: Commit**

```bash
git add src/nfl_predictor/api/routes.py tests/test_kalshi_feed_api.py
git commit -m "feat(api): GET /api/kalshi-feed serves frozen pre-game snapshots and calibration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: NFL: NaN lines no longer break `/batch` (live week-4 HTTP 500)

**Files:**
- Modify: `src/nfl_predictor/models/game_outcome.py`, `src/nfl_predictor/api/routes.py`
- Test: `tests/test_missing_lines.py` (new)

**Interfaces:**
- Produces: `game_outcome._line_or_none(line) -> float | None`; `routes._json_safe(value)`. `_snapshot_week()` now returns a sanitized copy (NaN/inf become `None`).

**Root cause (verified 2026-09-25):** nflverse leaves `spread_line`/`total_line` as NaN for games without a line. `margin_to_probabilities` checks `is not None`, so NaN turns into NaN probabilities. `public_snapshot.json` stores them, and Starlette refuses to serialize NaN, so GET `/api/predictions/2026/4/batch` returns 500 on the live site. Old weeks in the snapshot are reused verbatim by `public_snapshot.py`, so serving must sanitize too.

- [ ] **Step 1: Write the failing tests**: `tests/test_missing_lines.py`:

```python
import math

from fastapi.testclient import TestClient

from nfl_predictor.api import routes
from nfl_predictor.api.main import app
from nfl_predictor.models import game_outcome


def test_nan_lines_are_treated_as_missing():
    """nflverse leaves spread_line/total_line as NaN (not None) for games
    without a line yet; they must not turn into NaN probabilities."""
    result = game_outcome.margin_to_probabilities(
        -3.0, 13.0, spread_line=float("nan"), total_line=float("nan"), predicted_total=40.0, total_sigma=12.0,
    )

    assert result["home_cover_prob"] is None and result["away_cover_prob"] is None
    assert "over_prob" not in result
    assert math.isclose(result["home_win_prob"] + result["away_win_prob"], 1.0)


def test_batch_from_a_snapshot_with_nan_values_serves_null_not_500(monkeypatch):
    snapshot = {"season": 2026, "weeks": {"4": {"games": [], "player_props": [], "predictions": {
        "2026_04_GB_TB": {"home_win_prob": 0.55, "away_win_prob": 0.45,
                          "home_cover_prob": float("nan"), "over_prob": float("inf")},
    }}}}
    monkeypatch.setattr(routes, "PUBLIC_MODE", True)
    monkeypatch.setattr(routes, "_public_snapshot", lambda: snapshot)

    response = TestClient(app).get("/api/predictions/2026/4/batch")

    assert response.status_code == 200
    assert response.json()["2026_04_GB_TB"] == {
        "home_win_prob": 0.55, "away_win_prob": 0.45, "home_cover_prob": None, "over_prob": None,
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_missing_lines.py`
Expected: `2 failed` (`assert nan is None`; `ValueError: Out of range float values are not JSON compliant`).

- [ ] **Step 3: Implement**

`src/nfl_predictor/models/game_outcome.py`:

Replace this block:

```python
from __future__ import annotations

import numpy as np
```

with:

```python
from __future__ import annotations

import math

import numpy as np
```

Replace this block:

```python
def margin_to_probabilities(
```

with:

```python
def _line_or_none(line: float | None) -> float | None:
    if line is None or math.isnan(float(line)):
        return None
    return float(line)


def margin_to_probabilities(
```

Replace this block:

```python
    home_win_prob = float(1.0 - norm.cdf(0.0, loc=predicted_margin, scale=sigma))
    result = {"home_win_prob": home_win_prob, "away_win_prob": 1.0 - home_win_prob}

    if spread_line is not None:
```

with:

```python
    # nflverse leaves a missing line as NaN, not None: same meaning.
    spread_line = _line_or_none(spread_line)
    total_line = _line_or_none(total_line)
    home_win_prob = float(1.0 - norm.cdf(0.0, loc=predicted_margin, scale=sigma))
    result = {"home_win_prob": home_win_prob, "away_win_prob": 1.0 - home_win_prob}

    if spread_line is not None:
```

`src/nfl_predictor/api/routes.py`:

Replace this block:

```python
import json
import logging
import os
```

with:

```python
import json
import logging
import math
import os
```

Replace this block:

```python
def _snapshot_week(season: int, week: int) -> dict | None:
    snap = _public_snapshot()
    if snap.get("season") != season:
        return None
    return snap.get("weeks", {}).get(str(week))
```

with:

```python
def _json_safe(value):
    """NaN/inf -> None, recursively. Snapshots written before missing lines
    were handled contain NaN, which Starlette refuses to serialize (500)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _snapshot_week(season: int, week: int) -> dict | None:
    snap = _public_snapshot()
    if snap.get("season") != season:
        return None
    week_snap = snap.get("weeks", {}).get(str(week))
    return None if week_snap is None else _json_safe(week_snap)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_missing_lines.py` → Expected: `2 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `129 passed`

- [ ] **Step 5: Commit**

```bash
git add src/nfl_predictor/models/game_outcome.py src/nfl_predictor/api/routes.py tests/test_missing_lines.py
git commit -m "fix: NaN spread/total lines no longer produce NaN probabilities or a /batch 500

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: CFB store: the same columns, flag, feed rows and calibration

Work in `/Users/sigey/Documents/Projects.nosync/CFB_Predictor` from here on (`git checkout -b plan/2026-09-25-kalshi-feed` from `main` first). `cfb_predictor/tracking/store.py`'s `game_predictions` code is a verbatim port of NFL's, so the edits are the same text as Task 1. They are repeated in full here.

**Files:**
- Modify: `src/cfb_predictor/tracking/store.py`
- Test: `tests/test_kalshi_feed_store.py` (new)

**Interfaces:** identical to Task 1 (`get_feed_predictions`, `get_calibration`, the new columns, `n_backfilled`).

- [ ] **Step 1: Write the failing tests**: `tests/test_kalshi_feed_store.py`:

```python
import contextlib
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import pytest

from cfb_predictor.tracking import store

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    from cfb_predictor import config

    db_path = tmp_path / "tracking.db"
    monkeypatch.setattr(config, "TRACKING_DB_PATH", db_path)
    monkeypatch.setattr(store, "TRACKING_DB_PATH", db_path)
    yield


def _upcoming(**overrides):
    game = {
        "game_id": "401871100", "home_team": "Stanford", "away_team": "Georgia Tech",
        "commence_time": "2099-09-27 20:25:00", "season": 2026, "week": 3,
        "home_win_prob": 0.41, "away_win_prob": 0.59,
        "home_cover_prob": 0.47, "away_cover_prob": 0.53, "over_prob": 0.52, "under_prob": 0.48,
        "home_spread_line": -2.5, "total_line": 47.5,
        "predicted_margin": -2.9, "sigma": 13.2, "predicted_total": 48.1, "total_sigma": 12.5,
        "model_version": "ridge@2026-08-20T10:00:00+00:00",
    }
    game.update(overrides)
    return game


def _finished(**overrides):
    game = _upcoming(game_id="401869941", home_team="Coastal Carolina", away_team="Liberty",
                     commence_time="2026-09-20 17:00:00", home_win_prob=0.7, away_win_prob=0.3,
                     actual_home_score=30, actual_away_score=10)
    game.update(overrides)
    return game


def test_record_game_predictions_persists_feed_fields_and_is_not_backfilled():
    store.record_game_predictions([_upcoming()])

    with contextlib.closing(store._connect()) as conn:
        row = pd.read_sql("SELECT * FROM game_predictions", conn).iloc[0]

    assert row["predicted_margin"] == pytest.approx(-2.9)
    assert row["sigma"] == pytest.approx(13.2)
    assert row["predicted_total"] == pytest.approx(48.1)
    assert row["total_sigma"] == pytest.approx(12.5)
    assert row["model_version"] == "ridge@2026-08-20T10:00:00+00:00"
    assert row["backfilled"] == 0


def test_record_resolved_game_predictions_flags_backfilled():
    store.record_resolved_game_predictions([_finished()])

    with contextlib.closing(store._connect()) as conn:
        row = pd.read_sql("SELECT * FROM game_predictions", conn).iloc[0]

    assert row["backfilled"] == 1
    assert row["resolved"] == 1


def test_legacy_rows_are_classified_when_backfilled_column_is_added():
    """A database created before this change has no backfilled column. Rows
    whose snapshot was taken at or after kickoff can only have come from
    record_resolved_game_predictions, so they are flagged on migration."""
    conn = sqlite3.connect(str(store.TRACKING_DB_PATH))
    conn.execute(
        """CREATE TABLE game_predictions (
            game_id TEXT PRIMARY KEY, home_team TEXT NOT NULL, away_team TEXT NOT NULL,
            commence_time TEXT NOT NULL, snapshotted_at TEXT NOT NULL,
            home_win_prob REAL NOT NULL, away_win_prob REAL NOT NULL,
            home_cover_prob REAL, away_cover_prob REAL, over_prob REAL, under_prob REAL,
            resolved INTEGER NOT NULL DEFAULT 0, actual_home_score INTEGER, actual_away_score INTEGER,
            moneyline_hit INTEGER)"""
    )
    conn.executemany(
        "INSERT INTO game_predictions (game_id, home_team, away_team, commence_time, snapshotted_at,"
        " home_win_prob, away_win_prob, resolved) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        [
            ("pregame", "Stanford", "Georgia Tech", "2026-09-13 00:00:00", "2026-09-12T15:00:00+00:00", 0.6, 0.4),
            ("backfill", "Coastal Carolina", "Liberty", "2026-09-13 00:00:00", "2026-09-24T02:00:00+00:00", 0.6, 0.4),
        ],
    )
    conn.commit()
    conn.close()

    with contextlib.closing(store._connect()) as conn:
        flags = dict(conn.execute("SELECT game_id, backfilled FROM game_predictions").fetchall())

    assert flags == {"pregame": 0, "backfill": 1}


def test_feed_predictions_returns_only_upcoming_pregame_rows():
    store.record_game_predictions([_upcoming()])
    store.record_resolved_game_predictions([_finished()])

    rows = store.get_feed_predictions(now=NOW)

    assert [r["game_id"] for r in rows] == ["401871100"]
    row = rows[0]
    assert row["home"] == "Stanford" and row["away"] == "Georgia Tech"
    assert row["start_utc"] == "2099-09-27T20:25:00+00:00"
    assert row["p_home"] == pytest.approx(0.41)
    assert row["margin_mu"] == pytest.approx(-2.9) and row["sigma"] == pytest.approx(13.2)
    assert row["total_mu"] == pytest.approx(48.1) and row["total_sigma"] == pytest.approx(12.5)
    assert row["model_version"] == "ridge@2026-08-20T10:00:00+00:00"
    assert row["backfilled"] is False
    assert datetime.fromisoformat(row["snapshotted_at"]) < datetime.fromisoformat(row["start_utc"])


def test_feed_predictions_drop_games_that_have_started():
    store.record_game_predictions([_upcoming()])

    assert store.get_feed_predictions(now=datetime(2100, 1, 1, tzinfo=timezone.utc)) == []


def test_feed_predictions_keep_null_distribution_fields_as_none():
    legacy = _upcoming()
    for key in ("predicted_margin", "sigma", "predicted_total", "total_sigma", "model_version"):
        legacy.pop(key)
    store.record_game_predictions([legacy])

    row = store.get_feed_predictions(now=NOW)[0]

    assert row["margin_mu"] is None and row["sigma"] is None
    assert row["total_mu"] is None and row["model_version"] is None


def test_calibration_uses_only_pregame_resolved_rows():
    store.record_game_predictions([
        _upcoming(game_id=f"g{i}", home_win_prob=0.65, away_win_prob=0.35) for i in range(4)
    ])
    store.reconcile_game_predictions(pd.DataFrame([
        {"game_id": "g0", "home_score": 24, "away_score": 17},
        {"game_id": "g1", "home_score": 24, "away_score": 17},
        {"game_id": "g2", "home_score": 24, "away_score": 17},
        {"game_id": "g3", "home_score": 10, "away_score": 17},
    ]))
    # A backfilled 0.65 miss must not count.
    store.record_resolved_game_predictions([
        _finished(game_id="bf", home_win_prob=0.65, away_win_prob=0.35, actual_home_score=0, actual_away_score=7)
    ])

    calibration = store.get_calibration()

    bucket = next(b for b in calibration["winner"] if b["lo"] == 0.6)
    assert bucket == {"lo": 0.6, "hi": 0.7, "n": 4, "mean_prob": pytest.approx(0.65), "hit_rate": 0.75}
    assert len(calibration["winner"]) == 10
    empty = next(b for b in calibration["winner"] if b["lo"] == 0.1)
    assert empty == {"lo": 0.1, "hi": 0.2, "n": 0, "mean_prob": None, "hit_rate": None}


def test_calibration_grades_spread_and_total_against_recorded_lines():
    store.record_game_predictions([_upcoming(game_id="s1", home_spread_line=3.0, home_cover_prob=0.55,
                                             total_line=40.0, over_prob=0.35)])
    store.reconcile_game_predictions(pd.DataFrame([{"game_id": "s1", "home_score": 27, "away_score": 20}]))

    calibration = store.get_calibration()

    spread = next(b for b in calibration["spread"] if b["lo"] == 0.5)
    total = next(b for b in calibration["total"] if b["lo"] == 0.3)
    assert (spread["n"], spread["hit_rate"]) == (1, 1.0)   # margin 7 > 3
    assert (total["n"], total["hit_rate"]) == (1, 1.0)     # 47 > 40


def test_track_record_reports_backfilled_count():
    store.record_resolved_game_predictions([_finished()])

    games = store.get_track_record()["games"]

    assert games["n_resolved"] == 1
    assert games["n_backfilled"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_store.py`
Expected: `9 failed`.

- [ ] **Step 3: Implement** in `src/cfb_predictor/tracking/store.py`:

Replace this block:

```python
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(game_predictions)")}
    for column in ("home_spread_line", "total_line", "ats_hit", "total_hit", "season", "week"):
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} REAL" if column in ("home_spread_line", "total_line")
                         else f"ALTER TABLE game_predictions ADD COLUMN {column} INTEGER")
```

with:

```python
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(game_predictions)")}
    for column in ("home_spread_line", "total_line", "ats_hit", "total_hit", "season", "week"):
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} REAL" if column in ("home_spread_line", "total_line")
                         else f"ALTER TABLE game_predictions ADD COLUMN {column} INTEGER")
    # Kalshi feed: the predicted distribution behind each frozen snapshot,
    # plus whether the row was backfilled after the game was already over.
    for column, sql_type in _FEED_COLUMNS.items():
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} {sql_type}")
    if "backfilled" not in existing_cols:
        conn.execute("ALTER TABLE game_predictions ADD COLUMN backfilled INTEGER NOT NULL DEFAULT 0")
        _flag_legacy_backfills(conn)
```

Replace this block:

```python
def _require_pre_kickoff(commence_time: str) -> None:
```

with:

```python
_FEED_COLUMNS = {
    "predicted_margin": "REAL",
    "sigma": "REAL",
    "predicted_total": "REAL",
    "total_sigma": "REAL",
    "model_version": "TEXT",
}


def _parse_utc(value: str) -> datetime:
    """ISO timestamp -> aware UTC datetime. Naive values are UTC (that is how
    both commence_time and snapshotted_at are written)."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_is_pregame(snapshotted_at: str, commence_time: str) -> bool:
    try:
        return _parse_utc(snapshotted_at) < _parse_utc(commence_time)
    except (TypeError, ValueError):
        return False


def _flag_legacy_backfills(conn: sqlite3.Connection) -> None:
    """One-time classification when the backfilled column is first added.
    record_game_predictions only ever writes rows snapshotted before the
    stored commence_time (_require_pre_kickoff), so a row snapshotted at or
    after it can only have come from record_resolved_game_predictions."""
    rows = conn.execute("SELECT game_id, snapshotted_at, commence_time FROM game_predictions").fetchall()
    backfilled = [(game_id,) for game_id, snap, start in rows if not _snapshot_is_pregame(snap, start)]
    conn.executemany("UPDATE game_predictions SET backfilled = 1 WHERE game_id = ?", backfilled)
    conn.commit()


def _optional_float(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _require_pre_kickoff(commence_time: str) -> None:
```

Replace this block:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
        )
        for game in valid_games
    ]
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
```

with:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            game.get("predicted_margin"), game.get("sigma"), game.get("predicted_total"), game.get("total_sigma"),
            game.get("model_version"),
        )
        for game in valid_games
    ]
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 predicted_margin, sigma, predicted_total, total_sigma, model_version, backfilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
```

Replace this block:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            1, int(game["actual_home_score"]), int(game["actual_away_score"]), moneyline_hit, ats_hit, total_hit,
        ))
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 resolved, actual_home_score, actual_away_score, moneyline_hit, ats_hit, total_hit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
```

with:

```python
            game.get("home_spread_line"), game.get("total_line"), game.get("season"), game.get("week"),
            1, int(game["actual_home_score"]), int(game["actual_away_score"]), moneyline_hit, ats_hit, total_hit,
            game.get("predicted_margin"), game.get("sigma"), game.get("predicted_total"), game.get("total_sigma"),
            game.get("model_version"),
        ))
    with contextlib.closing(_connect()) as conn, conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO game_predictions
                (game_id, home_team, away_team, commence_time, snapshotted_at,
                 home_win_prob, away_win_prob, home_cover_prob, away_cover_prob, over_prob, under_prob,
                 home_spread_line, total_line, season, week,
                 resolved, actual_home_score, actual_away_score, moneyline_hit, ats_hit, total_hit,
                 predicted_margin, sigma, predicted_total, total_sigma, model_version, backfilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
```

Replace this block:

```python
            "n_resolved": 0, "pct_moneyline_correct": None, "pct_ats_correct": None,
            "pct_totals_correct": None, "weekly_trend": [],
        }
```

with:

```python
            "n_resolved": 0, "n_backfilled": 0, "pct_moneyline_correct": None, "pct_ats_correct": None,
            "pct_totals_correct": None, "weekly_trend": [],
        }
```

Replace this block:

```python
    return {
        "n_resolved": int(len(resolved)),
        "pct_moneyline_correct": float(resolved["moneyline_hit"].mean()),
```

with:

```python
    return {
        "n_resolved": int(len(resolved)),
        # Rows written after the game was over (record_resolved_game_predictions):
        # graded like the rest, but never a live pre-game call.
        "n_backfilled": int((resolved["backfilled"] == 1).sum()),
        "pct_moneyline_correct": float(resolved["moneyline_hit"].mean()),
```

Replace this block:

```python
def _summarize_games(resolved: pd.DataFrame) -> dict:
```

with:

```python
def get_feed_predictions(now: datetime | None = None) -> list[dict]:
    """Frozen pre-game snapshots for games that have not started yet: the
    rows the trade hub may compare against Kalshi prices. Backfilled rows
    and any row not snapshotted strictly before kickoff are excluded."""
    now = now or datetime.now(timezone.utc)
    with contextlib.closing(_connect()) as conn:
        rows = pd.read_sql("SELECT * FROM game_predictions WHERE resolved = 0 AND backfilled = 0", conn)
    feed = []
    for _, row in rows.iterrows():
        try:
            start = _parse_utc(row["commence_time"])
            snapshotted = _parse_utc(row["snapshotted_at"])
        except (TypeError, ValueError):
            continue
        if start <= now or snapshotted >= start:
            continue
        feed.append({
            "game_id": row["game_id"],
            "season": None if pd.isna(row["season"]) else int(row["season"]),
            "week": None if pd.isna(row["week"]) else int(row["week"]),
            "home": row["home_team"],
            "away": row["away_team"],
            "start_utc": start.isoformat(),
            "p_home": float(row["home_win_prob"]),
            "margin_mu": _optional_float(row["predicted_margin"]),
            "sigma": _optional_float(row["sigma"]),
            "total_mu": _optional_float(row["predicted_total"]),
            "total_sigma": _optional_float(row["total_sigma"]),
            "home_spread_line": _optional_float(row["home_spread_line"]),
            "total_line": _optional_float(row["total_line"]),
            "model_version": row["model_version"] if isinstance(row["model_version"], str) else None,
            "snapshotted_at": snapshotted.isoformat(),
            "backfilled": False,
        })
    return sorted(feed, key=lambda r: (r["start_utc"], r["game_id"]))


def _calibration_buckets(pairs: list[tuple[float, int]], n_buckets: int) -> list[dict]:
    buckets = []
    for i in range(n_buckets):
        lo, hi = i / n_buckets, (i + 1) / n_buckets
        last = i == n_buckets - 1
        inside = [(p, y) for p, y in pairs if lo <= p < hi or (last and p == 1.0)]
        buckets.append({
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "n": len(inside),
            "mean_prob": sum(p for p, _ in inside) / len(inside) if inside else None,
            "hit_rate": sum(y for _, y in inside) / len(inside) if inside else None,
        })
    return buckets


def get_calibration(n_buckets: int = 10) -> dict:
    """Reliability buckets over resolved, genuinely pre-game snapshots:
    home win probability vs home won, home cover probability vs covered
    (at the recorded line), over probability vs went over. Ties and pushes
    are left out."""
    with contextlib.closing(_connect()) as conn:
        rows = pd.read_sql("SELECT * FROM game_predictions WHERE resolved = 1 AND backfilled = 0", conn)
    winner: list[tuple[float, int]] = []
    spread: list[tuple[float, int]] = []
    total: list[tuple[float, int]] = []
    for _, row in rows.iterrows():
        if not _snapshot_is_pregame(row["snapshotted_at"], row["commence_time"]):
            continue
        home, away = row["actual_home_score"], row["actual_away_score"]
        if pd.isna(home) or pd.isna(away):
            continue
        margin, points = float(home - away), float(home + away)
        if margin != 0:
            winner.append((float(row["home_win_prob"]), int(margin > 0)))
        line, prob = row["home_spread_line"], row["home_cover_prob"]
        if pd.notna(line) and pd.notna(prob) and margin != float(line):
            spread.append((float(prob), int(margin > float(line))))
        line, prob = row["total_line"], row["over_prob"]
        if pd.notna(line) and pd.notna(prob) and points != float(line):
            total.append((float(prob), int(points > float(line))))
    return {
        "n_buckets": n_buckets,
        "winner": _calibration_buckets(winner, n_buckets),
        "spread": _calibration_buckets(spread, n_buckets),
        "total": _calibration_buckets(total, n_buckets),
    }


def _summarize_games(resolved: pd.DataFrame) -> dict:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_store.py` → Expected: `9 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `137 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cfb_predictor/tracking/store.py tests/test_kalshi_feed_store.py
git commit -m "feat(tracking): store snapshot distributions, flag backfills, feed + calibration readers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: CFB: 48 h lead window across this and next week, and `model_version`

**Files:**
- Modify: `src/cfb_predictor/models/manifest.py`, `src/cfb_predictor/api/routes.py`
- Test: `tests/test_snapshot_window.py` (new)

**Interfaces:** as Task 2, with `games_data.fetch_upcoming_games` in place of `schedules`. CFBD start dates are already tz-aware UTC.

- [ ] **Step 1: Write the failing tests**: `tests/test_snapshot_window.py`:

```python
from datetime import datetime, timedelta, timezone

import pandas as pd

from cfb_predictor.api import routes
from cfb_predictor.models import manifest

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _game(game_id, week, hours_from_now):
    kickoff = pd.Timestamp(NOW + timedelta(hours=hours_from_now))  # CFBD start dates are tz-aware UTC
    return {"game_id": game_id, "season": 2026, "week": week, "gameday": kickoff,
            "home_team": "Stanford", "away_team": "Georgia Tech", "home_score": None, "away_score": None}


def test_games_to_snapshot_takes_both_weeks_but_only_inside_the_lead_window(monkeypatch):
    weeks = {
        4: pd.DataFrame([_game("in_window", 4, 40), _game("too_early", 4, 100)]),
        5: pd.DataFrame([_game("next_week_soon", 5, 47), _game("next_week_later", 5, 200)]),
    }
    monkeypatch.setattr(routes.games_data, "fetch_upcoming_games", lambda season, week: weeks.get(week, pd.DataFrame()))

    games = routes._games_to_snapshot(2026, 4, NOW, lead_hours=48)

    assert list(games["game_id"]) == ["in_window", "next_week_soon"]


def test_games_to_snapshot_handles_an_empty_next_week(monkeypatch):
    weeks = {4: pd.DataFrame([_game("in_window", 4, 24)])}
    monkeypatch.setattr(routes.games_data, "fetch_upcoming_games", lambda season, week: weeks.get(week, pd.DataFrame()))

    games = routes._games_to_snapshot(2026, 4, NOW, lead_hours=48)

    assert list(games["game_id"]) == ["in_window"]


def test_tracking_tick_records_distribution_and_each_games_own_week(monkeypatch):
    recorded = []
    monkeypatch.setattr(routes, "_games_to_snapshot", lambda season, week, now, lead_hours=None: pd.DataFrame(
        [_game("401871049", 5, 30)]))
    monkeypatch.setattr(routes, "_load_models_cached", lambda: {"model_version": "ridge@t"})
    monkeypatch.setattr(routes, "_load_game_history", lambda season: pd.DataFrame())
    monkeypatch.setattr(routes.sportsbook_api, "fetch_game_odds", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(routes, "_predict_game_from_models", lambda *a, **k: {
        "home_win_prob": 0.4, "away_win_prob": 0.6, "predicted_margin": -3.4, "sigma": 16.0,
        "predicted_total": 55.0, "total_sigma": 14.0, "model_version": "ridge@t",
    })
    monkeypatch.setattr(routes.store, "record_game_predictions", lambda games: recorded.extend(games) or len(games))
    monkeypatch.setattr(routes, "_get_player_props_live", lambda season, week: [])
    monkeypatch.setattr(routes.store, "record_player_prop_predictions", lambda rows: 0)
    monkeypatch.setattr(routes.games_data, "fetch_current_season_partial",
                        lambda: pd.DataFrame(columns=["game_id", "home_score", "away_score"]))
    monkeypatch.setattr(routes.store, "reconcile_game_predictions", lambda df: 0)
    monkeypatch.setattr(routes.store, "backfill_unresolved_games", lambda module: 0)

    routes.background_tracking_tick(season=2026, week=4)

    assert len(recorded) == 1
    row = recorded[0]
    assert row["week"] == 5
    assert row["predicted_margin"] == -3.4 and row["sigma"] == 16.0
    assert row["model_version"] == "ridge@t"


def test_predict_game_from_models_reports_model_version(monkeypatch):
    class _FakeTotalModel:
        def predict(self, _X):
            return [55.0]

    monkeypatch.setattr(
        routes.feature_build, "build_features_for_game",
        lambda home, away, games_df: pd.Series({"rating_diff": 50.0, "home_rest_days": 7.0, "away_rest_days": 7.0}),
    )
    models = {
        "feature_cols": ["rating_diff", "home_rest_days", "away_rest_days"],
        "chosen_candidate": "elo", "sigma": 16.0, "total_sigma": 14.0,
        "total_model": _FakeTotalModel(), "model_version": "elo@2026-08-20T10:00:00+00:00",
    }

    result = routes._predict_game_from_models(models, "Stanford", "Georgia Tech", pd.DataFrame())

    assert result["model_version"] == "elo@2026-08-20T10:00:00+00:00"


def test_model_version_combines_candidate_and_training_time():
    assert manifest.model_version(
        {"chosen_candidate": "ridge", "trained_at": "2026-08-20T10:00:00+00:00"}
    ) == "ridge@2026-08-20T10:00:00+00:00"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_snapshot_window.py`
Expected: `5 failed`.

- [ ] **Step 3: Implement**

`src/cfb_predictor/models/manifest.py`:

Replace this block:

```python
def load_models() -> dict:
    manifest = load_manifest()
```

with:

```python
def model_version(manifest: dict) -> str:
    """Identifies the trained model behind a prediction: candidate + training time."""
    return f"{manifest['chosen_candidate']}@{manifest['trained_at']}"


def load_models() -> dict:
    manifest = load_manifest()
```

Replace this block:

```python
        "chosen_candidate": manifest["chosen_candidate"],
        "sigma": manifest["sigma"],
```

with:

```python
        "chosen_candidate": manifest["chosen_candidate"],
        "model_version": model_version(manifest),
        "sigma": manifest["sigma"],
```

`src/cfb_predictor/api/routes.py`:

Replace this block:

```python
import json
import logging
import time
from datetime import date
```

with:

```python
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
```

Replace this block:

```python
    result["total_sigma"] = models["total_sigma"]
    return result
```

with:

```python
    result["total_sigma"] = models["total_sigma"]
    result["model_version"] = models.get("model_version")
    return result
```

Replace this block:

```python
def background_tracking_tick(season: int, week: int) -> None:
    """Snapshot this week's upcoming-game (and player-prop) predictions,
    then reconcile anything now resolved. Called on a timer from
    api/main.py's lifespan."""
    try:
        models = _load_models_cached()
    except Exception as exc:
        logger.warning("background_tracking_tick skipped: %s", exc)
        return

    games = games_data.fetch_upcoming_games(season, week)
```

with:

```python
# How close to kickoff a game's prediction is frozen. The first snapshot
# inside this window is kept forever (INSERT OR IGNORE), so it is the one the
# track record grades and the Kalshi feed serves. 48h puts Saturday games'
# snapshots on Thursday, after the previous Saturday's results are in.
SNAPSHOT_LEAD_HOURS = float(os.getenv("SNAPSHOT_LEAD_HOURS", "48"))


def _games_to_snapshot(season: int, week: int, now: datetime, lead_hours: float | None = None) -> pd.DataFrame:
    """Upcoming games from this week and next whose kickoff is within the
    lead window. Next week is included because current_season_and_week()
    rolls over on the weekday of week 1's first kickoff, not on a fixed
    football-week boundary."""
    lead = timedelta(hours=SNAPSHOT_LEAD_HOURS if lead_hours is None else lead_hours)
    frames = [f for f in (games_data.fetch_upcoming_games(season, wk) for wk in (week, week + 1)) if not f.empty]
    if not frames:
        return pd.DataFrame()
    games = pd.concat(frames, ignore_index=True)
    kickoff = pd.to_datetime(games["gameday"], utc=True, errors="coerce")
    horizon = pd.Timestamp(now + lead)
    return games[kickoff.notna() & (kickoff <= horizon)].drop_duplicates("game_id").reset_index(drop=True)


def background_tracking_tick(season: int, week: int) -> None:
    """Snapshot upcoming-game (and player-prop) predictions inside the lead
    window, then reconcile anything now resolved. Called on a timer from
    api/main.py's lifespan."""
    try:
        models = _load_models_cached()
    except Exception as exc:
        logger.warning("background_tracking_tick skipped: %s", exc)
        return

    games = _games_to_snapshot(season, week, datetime.now(timezone.utc))
```

Replace this block:

```python
                        "home_spread_line": spread_line, "total_line": total_line,
                        "season": season, "week": week,
                        **pred,
```

with:

```python
                        "home_spread_line": spread_line, "total_line": total_line,
                        "season": season, "week": int(game["week"]) if pd.notna(game.get("week")) else week,
                        **pred,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_snapshot_window.py tests/test_background_tracking.py` → Expected: `6 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `142 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cfb_predictor/models/manifest.py src/cfb_predictor/api/routes.py tests/test_snapshot_window.py
git commit -m "feat(tracking): freeze snapshots 48h before kickoff across this and next week; record model_version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: CFB `GET /api/kalshi-feed`

**Files:**
- Modify: `src/cfb_predictor/api/routes.py`
- Test: `tests/test_kalshi_feed_api.py` (new)

**Interfaces:** as Task 3, with `"sport": "cfb"`. CFB rows usually have `home_spread_line`/`total_line` null (the shared odds key is out of quota) but always carry `margin_mu`/`sigma`/`total_mu`/`total_sigma`.

- [ ] **Step 1: Write the failing tests**: `tests/test_kalshi_feed_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from cfb_predictor.api.main import app
from cfb_predictor.tracking import store


@pytest.fixture
def client(monkeypatch, tmp_path):
    from cfb_predictor import config

    db_path = tmp_path / "tracking.db"
    monkeypatch.setattr(config, "TRACKING_DB_PATH", db_path)
    monkeypatch.setattr(store, "TRACKING_DB_PATH", db_path)
    return TestClient(app)


def test_kalshi_feed_serves_frozen_pregame_rows_and_calibration(client):
    store.record_game_predictions([{
        "game_id": "401871049", "home_team": "New Mexico State", "away_team": "Western Kentucky",
        "commence_time": "2099-10-02 00:15:00", "season": 2026, "week": 4,
        "home_win_prob": 0.40, "away_win_prob": 0.60, "predicted_margin": -3.4, "sigma": 13.2,
        "predicted_total": 39.8, "total_sigma": 12.5, "model_version": "xgb@t",
    }])

    response = client.get("/api/kalshi-feed")

    assert response.status_code == 200
    body = response.json()
    assert body["sport"] == "cfb"
    assert body["lead_hours"] == 48
    assert [g["game_id"] for g in body["games"]] == ["401871049"]
    game = body["games"][0]
    assert game["start_utc"] == "2099-10-02T00:15:00+00:00"
    assert game["p_home"] == 0.40 and game["margin_mu"] == -3.4 and game["backfilled"] is False
    assert set(body["calibration"]) == {"n_buckets", "winner", "spread", "total"}
    assert body["generated_at"].endswith("+00:00")


def test_kalshi_feed_is_empty_but_valid_with_no_snapshots(client):
    body = client.get("/api/kalshi-feed").json()

    assert body["games"] == []
    assert body["calibration"]["winner"][0] == {"lo": 0.0, "hi": 0.1, "n": 0, "mean_prob": None, "hit_rate": None}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_api.py`
Expected: `2 failed` (`assert 404 == 200`).

- [ ] **Step 3: Implement**: add the route above `get_game_verdict`:

Replace this block:

```python
@router.get("/games/{game_id}/verdict")
```

with:

```python
@router.get("/kalshi-feed")
def get_kalshi_feed():
    """Read-only feed for the Algo Trade Hub: frozen pre-game snapshots for
    games that have not kicked off, plus reliability buckets over graded
    pre-game snapshots. Served from the tracking database only, so it
    never recomputes a prediction."""
    return {
        "sport": "cfb",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lead_hours": SNAPSHOT_LEAD_HOURS,
        "games": store.get_feed_predictions(),
        "calibration": store.get_calibration(),
    }


@router.get("/games/{game_id}/verdict")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q tests/test_kalshi_feed_api.py` → Expected: `2 passed`
Run: `PYTHONPATH=$PWD/src .venv/bin/python -m pytest -q` → Expected: `144 passed`

- [ ] **Step 5: Commit**

```bash
git add src/cfb_predictor/api/routes.py tests/test_kalshi_feed_api.py
git commit -m "feat(api): GET /api/kalshi-feed serves frozen pre-game snapshots and calibration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Evidence reports, local smoke, and Kevin's deploy checklist

**Files:**
- Create: `docs/superpowers/reports/2026-09-25-predictor-pregame-feed.md` in **each** repo.

- [ ] **Step 1: Local smoke, NFL** (from `NFL_Predictor`; it writes only `data/tracking.db` in the checkout, which is gitignored. Move any existing `data/tracking.db` to `_attic/` first and restore it afterwards):

```bash
cat > /tmp/smoke_feed.py <<'EOF'
import json, sys
from fastapi.testclient import TestClient
pkg = sys.argv[1]
routes = __import__(f"{pkg}.api.routes", fromlist=["x"])
app = __import__(f"{pkg}.api.main", fromlist=["x"]).app
season, week = routes.current_season_and_week()
routes._get_player_props_live = lambda s, w: []          # props don't affect the feed
routes.background_tracking_tick(season, week)
body = TestClient(app).get("/api/kalshi-feed").json()
print(season, week, "feed games:", len(body["games"]), "lead:", body["lead_hours"])
print(json.dumps(body["games"][:1], indent=1))
EOF
PUBLIC_MODE=false PYTHONPATH=$PWD/src .venv/bin/python /tmp/smoke_feed.py nfl_predictor
```
Expected: `feed games: N` with N ≥ 1 when any game kicks off within 48 h (on 2026-09-25 at 05:40Z it took `SNAPSHOT_LEAD_HOURS=96` to reach Sunday's slate, and that gave 15). Every row has non-null `sigma` and `model_version`, and `snapshotted_at < start_utc`.

- [ ] **Step 2: Same for CFB** (`cd` to `CFB_Predictor`). The tick needs `CFBD_API_KEY` in the environment, or a fresh `data/cache/games/2026.parquet`. The sportsbook odds call may log a warning without keys, which is fine:

```bash
PUBLIC_MODE=false PYTHONPATH=$PWD/src .venv/bin/python /tmp/smoke_feed.py cfb_predictor
```
Expected: `feed games: N` (70 on 2026-09-25).

- [ ] **Step 3: Write the report** in each repo (`docs/superpowers/reports/2026-09-25-predictor-pregame-feed.md`) with, per task, the RED and GREEN commands and the tail of their output, the smoke output, and any deviation with its reason.

- [ ] **Step 4: Commit** (in each repo):

```bash
git add docs/superpowers/reports/2026-09-25-predictor-pregame-feed.md
git commit -m "docs: evidence report for the Kalshi pre-game feed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Hand off to Kevin (not the agent):** review and merge each branch, then deploy through the repo workflow's `vps` job to the VPS (`nfl.<domain>`/`cfb.<domain>`; see "Kevin's decisions" above; an Azure check is only an interim fallback before cutover). After deploying:
  - `curl -s https://<nfl host>/api/kalshi-feed | head -c 400` must return JSON with `"sport": "nfl"`. Do the same for CFB.
  - The first container start runs `_connect()`, which adds the columns and flags legacy backfills in the **persistent** DB. Check with `/api/track-record` → `games.n_backfilled`.
  - The next GitHub snapshot refresh rewrites `public_snapshot.json` without NaN. Until then Task 4's serving guard covers it: `/api/predictions/2026/4/batch` should return 200.
  - Leave the tracker running at least 48 h before the hub's first live sports run (hub plan 7b), so the feed has games.

---

## Follow-ups (not in this plan; the sports after NFL/CFB)

Each needs its own small plan built on the same feed contract before the hub adds its adapter:

- **NBA_Predictor** (`nba.<domain>`):
  - Leakage suspect: `/hub/track-record` reports a 0.858 hit rate on 1,365 games, which is implausible pre-game.
  - It serves the latest prediction with no pre-tip cutoff, and `game_date` carries no tip time.
  - Needed:
    - a stored first-snapshot table with `snapshotted_at` and a tip-off time (from the NBA CDN schedule);
    - a `backfilled` flag;
    - `/kalshi-feed` with `margin_mu`/`sigma`/`total_mu`/`total_sigma` (the app already predicts margin and total);
    - a track record recomputed from pre-tip rows only.
  - Kalshi `KXNBAGAME`/`SPREAD`/`TOTAL` use away+home with all 30 codes matching.
- **PL_Predictor** (`pl.<domain>`):
  - It has the best hygiene (`commence_time` and a `backfilled` flag already exist).
  - Public mode returns empty `/api/fixtures`; it needs `/api/fixtures/gameweek` or a `/kalshi-feed` returning home/draw/away and `snapshotted_at`.
  - Kalshi `KXEPLGAME` is **home first** with 3 outcomes (`-TIE`), and its team codes drift, so it needs a versioned alias table.
- **F1_Predictor** (`f1.<domain>`):
  - `/api/races/{s}/{r}/prediction` has no snapshot timestamp. It needs a frozen pre-qualifying/pre-race snapshot with `snapshotted_at`, plus `p_win` per driver.
  - Kalshi `KXF1RACE-<RACE><YY>-<DRIVER>` needs a driver-code alias table.
- **Sports_Predictor:** support `?sport=&game=` deep links, so the hub's `source_url` opens the game (it currently lands on the home page).
- **CFB lines:** `home_spread_line`/`total_line` are null while the shared odds key is out of quota, so CFB spread/total calibration stays empty. The hub prices those markets from the distribution but will not promote them to candidates until the buckets fill.

## Self-Review

- **Spec coverage:**
  - §5a "stored pre-game predictions … timestamps before kickoff": Tasks 1/3/5/7 serve only rows with `snapshotted_at < start`, drop backfills, and never recompute.
  - §3.2 "calibrated (within 10 pp) in the probability bucket": the feed's `calibration` (Tasks 1/5) is what the hub's filter reads.
  - The `/track-record` recompute concern: backfills are flagged, counted (`n_backfilled`) and excluded from calibration.
  - The NFL batch 500 is fixed in Task 4. NBA/PL/F1 are listed as follow-ups with their specific fixes.
- **Placeholder scan:** every code step has complete code (new files in full; edits as exact replace blocks). The generator that rendered this plan replayed every block against the base commits and got files byte-identical to the verified worktrees.
- **Type consistency:**
  - `get_feed_predictions`/`get_calibration`/`SNAPSHOT_LEAD_HOURS`/`_games_to_snapshot`/`model_version` have the same names in Tasks 1–7.
  - The feed keys match the hub's `tradehub/sports/feed.py::parse_feed` (`game_id, home, away, start_utc, p_home, margin_mu, sigma, total_mu, total_sigma, model_version, snapshotted_at, backfilled, season, week`; `calibration.winner|spread|total`).
