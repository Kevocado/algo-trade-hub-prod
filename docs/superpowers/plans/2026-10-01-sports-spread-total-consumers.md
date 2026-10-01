# Sports Spread and Total Consumers (Roadmap v2, Item 11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal the NFL and CFB predictors' spread and total probabilities beside a Kalshi-implied baseline on the same contracts, with the orientation of every number carried in the frozen row so a gap can never be sign-flipped.

**Architecture:** `tradehub/sports/orientation.py` states, in one place and unit-tested, what a spread or total market is *about*: which team a spread refers to, whether YES means over, and the line — all parsed from the market `title`, never from the ticker. `tradehub/journal/forecasters/sports.py` replaces `one_per_game` with `journal_targets`, which keeps the winner-market fold (two complementary rows = one bet) but treats **every spread line and every total as its own contract**. The forecaster identity gains a `kind`, so the registry and `MARKET_PAIR` gain a model/baseline pair per kind.

**Tech Stack:** Python 3.12, existing sports + journal stack, pytest. No new dependency, **no migration**.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 Wave 3 Sports; §4 one ledger of record; §10 gates). **Depends on:** plan (l) `wave3-sports-consumers.md` and plan (k) `one-ledger-of-record.md`, both merged. Independent of plan (p).

> **Provenance and its limit — read this before trusting the code below.** Every **fact** in this plan was checked against the live API on 2026-10-01 and the real rows are quoted verbatim. The **code** has *not* been executed: I wrote it against the checked facts and the existing modules, but I have not run a single test in this plan, and I have no reviewer verification of it the way plans (l), (o) and (p) have. Treat the code as a reviewed starting point, not as verified code: run it, fix what disagrees, and say so in the PR. Nothing here is inferred — every number in §1 came out of `GET /api/sports-edges?limit=200&offset=0` against the deployed API (HTTP 200, `total: 90`).

## Global Constraints

- Everything in plan (a)'s Global Constraints applies: freeze by trigger, gaps never backfilled, cadence `daily` so **200 settled targets** before the gate, BSS vs market, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration.
- **The journal never re-models or re-settles a game.** Same as plan (l): it consumes `run_sports_scan`'s priced rows and settles with `settle_on_kalshi`.
- **Every spread line and every total is a distinct contract** with its own price and its own Kalshi result. The one-row-per-game fold that is correct for winner markets (its two markets are exact complements) is **wrong** for a game with 6 spread lines and 11 total lines — see §1.4, where the live data has exactly that.
- **Orientation is carried, never re-derived from the number.** A consumer that subtracts `our_prob - market_prob` without reading `side` is wrong on every NO row.
- Spread and total stay out of the journal until they have their own forecaster keys. The journal's headline count of forecasters will rise from 19 to 31 (see §3.3); that is correct and expected, not a leak.
- Weather stays quarantined; earnings and crypto stay deferred to v1.x.

---

## 1. The feed fields that carry spread and total, checked against real rows

### 1.1 What the live feed actually returns

`GET /api/sports-edges?limit=200&offset=0` on 2026-10-01, HTTP 200, `total: 90`:

```
kinds:  {'winner': 73, 'total': 11, 'spread': 6}
tiers:  {'flagged': 27, 'filtered': 63}
sports: {'cfb': 73, 'nfl': 17}
```

Every spread and total row belongs to **one** NFL game, `game_id: "2026_04_PIT_CLE"`, `home: "CLE"`, `away: "PIT"`, and **every one of the 17 has `side: "yes"`**. Both series are already priced by the scan — `tradehub/sports/config.py:15` declares `"nfl": {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}` and `:16` the CFB equivalents — so nothing needs adding to the scan to make these priceable.

The fields the journal needs, quoted from two real rows:

```json
{ "market_id": "KXNFLSPREAD-26OCT01PITCLE-PIT8", "kind": "spread", "side": "yes",
  "title": "PIT Steelers wins by over 7.5 points?", "home": "CLE", "away": "PIT",
  "game_id": "2026_04_PIT_CLE", "our_prob": 0.371, "market_prob": 0.295,
  "entry_price": 0.29, "quote_spread": null, "rank_edge_pct": 0.071,
  "edge_pct": null, "candidate": false, "tier": "filtered",
  "reject_reasons": ["calibration_insufficient"], "start_utc": "2026-10-02T00:15:00+00:00" }
```
```json
{ "market_id": "KXNFLTOTAL-26OCT01PITCLE-39", "kind": "total", "side": "yes",
  "title": "Full Game: over 38.5 points scored?", "home": "CLE", "away": "PIT",
  "game_id": "2026_04_PIT_CLE", "our_prob": 0.566, "market_prob": 0.475,
  "entry_price": 0.47, "quote_spread": null, "rank_edge_pct": 0.086,
  "edge_pct": null, "candidate": false, "tier": "filtered",
  "reject_reasons": ["calibration_insufficient"], "start_utc": "2026-10-02T00:15:00+00:00" }
```

`scan.py` already publishes every one of these into `raw_payload` (`side` at `:235`, `kind` at `:238`, `game_id` `:239`, `home` `:240`, `away` `:241`, `entry_price` `:233`, `maker` `:234`) plus `yes_bid` / `yes_ask` / `model_version` from plan (l). **`market_id`, `title`, `home` and `away` are in the edge row but not in `raw_payload`** — §2's payload change is what carries them.

### 1.2 Spread orientation: the ticker names the AWAY team, and its number is not the line

All six live spread rows, checked:

| `market_id` | `title` | suffix team | suffix team is |
|---|---|---|---|
| `KXNFLSPREAD-26OCT01PITCLE-PIT8` | PIT Steelers wins by over 7.5 points? | PIT | **away** |
| `KXNFLSPREAD-26OCT01PITCLE-PIT11` | PIT Steelers wins by over 10.5 points? | PIT | **away** |
| `KXNFLSPREAD-26OCT01PITCLE-PIT4` | PIT Steelers wins by over 3.5 points? | PIT | **away** |
| `KXNFLSPREAD-26OCT01PITCLE-PIT10` | PIT Steelers wins by over 9.5 points? | PIT | **away** |
| `KXNFLSPREAD-26OCT01PITCLE-PIT7` | PIT Steelers wins by over 6.5 points? | PIT | **away** |
| `KXNFLSPREAD-26OCT01PITCLE-PIT5` | PIT Steelers wins by over 4.5 points? | PIT | **away** |

Two rules, both load-bearing:
- **YES = the named team wins by MORE than the line.** The named team is whatever the title names; here it is `PIT`, the away side. A consumer that assumes a spread market is about the home team is wrong on all six live rows. Resolve the name against `home`/`away` and record which one it was, rather than assuming.
- **The ticker's integer is NOT the line.** `PIT8` ↔ 7.5, `PIT11` ↔ 10.5, `PIT4` ↔ 3.5, `PIT10` ↔ 9.5, `PIT7` ↔ 6.5, `PIT5` ↔ 4.5 — every one is rounded up. Displaying or scoring the ticker's number would print a line the market does not offer. **Parse the line from `title`.**

### 1.3 Total orientation

All eleven live totals: ticker suffix is the bare line and the title states over/under explicitly — `KXNFLTOTAL-26OCT01PITCLE-39` ↔ "over 38.5 points scored?" (and 41↔40.5, 42↔41.5, 38↔37.5, 45↔44.5, 40↔39.5, 36↔35.5, 37↔36.5, 33↔32.5, 48↔47.5, 30↔29.5). **YES = over.** The same rounding applies, so again the title is the source.

### 1.4 Why the winner-market fold must not be reused

Plan (l)'s `one_per_game` keeps only the first ticker per `(game_id, kind)` for `kind == "winner"`. Applying that same fold to spread/total, with the live rows:

```
total   2026_04_PIT_CLE -> 11 rows  <-- would collapse to ONE pick
spread  2026_04_PIT_CLE ->  6 rows  <-- would collapse to ONE pick
winner  401858252       ->  2 rows  <-- correct: exact complements, one bet
```

For a winner market the two rows are exact complements and folding them is right. For one game with 6 spread lines and 11 totals, folding throws away 15 distinct contracts, each with its own price and its own Kalshi result — and would quietly grade the journal on 1 of 17. So the fold becomes **per-contract** for the non-winner kinds, keyed by `market_id`.

### 1.5 The sign-flip trap

`1 - p` is the complement of the **same** contract. It is not the other team and not the other side of a different question:
- spread NO = "that team does **not** win by more than the line". It is **not** "the other team covers" — it also covers the named team winning by fewer points.
- total NO = under.
- `edge_pct` and `rank_edge_pct` in the feed are already signed for the row's own `side` (`PIT8` row: `our 0.371`, `market 0.295`, `rank_edge_pct: 0.071` = `(0.371-0.295)*100`, positive for a YES row).

So any gap must be computed as `our_prob - market_prob` **for a YES row** and `market_prob - our_prob` **for a NO row**, and the accompanying words must keep naming the same team and the same over/under. All 17 live rows are YES, so **today's data cannot catch this** — which is exactly why Task 1's sign test is not optional.

---

## 2. Frozen-quote payload per kind

### 2.1 The orientation object

`tradehub/sports/orientation.py` (new) — one place that answers "what is this number about":

```python
"""What a spread or total market is about, parsed once so no consumer can guess (roadmap v2 item 11).

Live-checked against `GET /api/sports-edges` on 2026-10-01 (17 spread/total rows, all NFL
`2026_04_PIT_CLE`), which fixes two rules this module exists to encode:

  * A spread market is about the team its TITLE names, and in every live row that is the AWAY team
    (`KXNFLSPREAD-26OCT01PITCLE-PIT8` is "PIT Steelers wins by over 7.5 points?" on a game whose
    home is CLE). Resolve the name against `home`/`away`; never assume the home side.
  * The ticker's trailing integer is NOT the line: `PIT8` is over 7.5, `PIT11` is over 10.5, and all
    eleven totals round the same way (`KXNFLTOTAL-26OCT01PITCLE-39` is over 38.5). The title is the
    only source of the line.

`side` decides the sign of every downstream gap, and `1 - p` is the complement of THIS contract:
a spread NO is "that team does not win by more than the line", which is not "the other team covers".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SPREAD = re.compile(r"^(?P<team>.+?)\s+wins by (?P<over>over|under)\s+(?P<line>-?\d+(?:\.\d+)?)\s+points", re.I)
_TOTAL = re.compile(r"(?P<over>over|under)\s+(?P<line>-?\d+(?:\.\d+)?)\s+points scored", re.I)


@dataclass(frozen=True)
class Orientation:
    kind: str
    side: str
    line: float
    over: bool
    team: str | None          # spread only: the team the market is about
    team_is_home: bool | None
    statement: str            # orientation-safe words, always naming the same team and line


def _line_phrase(o: Orientation, named: str) -> str:
    return f"{named} {'wins by more than' if o.over else 'wins by less than'} {abs(o.line)}"


def orient(kind: str, title: str, side: str, home: str, away: str) -> Orientation | None:
    """Orientation from the market title, or None when the title does not match this shape."""
    if kind == "spread":
        m = _SPREAD.search(title or "")
        if not m:
            return None
        team, line, over = m.group("team").strip(), float(m.group("line")), m.group("over").lower() == "over"
        is_home = team.lower() == (home or "").lower()
        is_away = team.lower() == (away or "").lower()
        named = team if (is_home or is_away) else team
        o = Orientation(kind, side, line, over, team, is_home if (is_home or is_away) else None)
        return Orientation(kind, side, line, over, team, o.team_is_home,
                           f"{_line_phrase(o, named)} ({'YES' if side == 'yes' else 'NO'})")
    if kind == "total":
        m = _TOTAL.search(title or "")
        if not m:
            return None
        line, over = float(m.group("line")), m.group("over").lower() == "over"
        o = Orientation(kind, side, line, over, None, None)
        word = "over" if over else "under"
        return Orientation(kind, side, line, over, None, None,
                           f"game total {word} {abs(line)} ({'YES' if side == 'yes' else 'NO'})")
    return None


def gap_points(our_prob: float, market_prob: float, side: str) -> float:
    """Signed gap for THIS contract's side: a NO row's edge is the mirror, never the same subtraction."""
    diff = (our_prob - market_prob) * 100.0
    return diff if side == "yes" else -diff
```

### 2.2 What rides in each frozen row

`_payload()` in `tradehub/journal/forecasters/sports.py` gains the orientation, so the journal's own
stored row is self-describing and a later consumer never has to re-parse a title:

| field | winner | spread | total | source |
|---|---|---|---|---|
| `kind` | ✓ | ✓ | ✓ | `raw_payload.kind` (already there) |
| `side` | ✓ | ✓ | ✓ | `raw_payload.side` (in the edge row, **not** in `raw_payload` yet) |
| `market_title` | ✓ | ✓ | ✓ | edge row `title` |
| `home` / `away` | ✓ | ✓ | ✓ | `raw_payload.home/away` (already there) |
| `orientation` | — | `{line, over, team, team_is_home, statement}` | `{line, over, statement}` | §2.1 |
| `gap_points` | ✓ | ✓ | ✓ | §2.1, **side-aware** |
| `yes_bid` / `yes_ask` | ✓ | ✓ | ✓ | plan (l) (already there) |
| `model_version` | ✓ | ✓ | ✓ | plan (l) (already there) |

`scan.py`'s `raw_payload` gains `side` and `title` (it already publishes `kind`, `home`, `away`,
`entry_price`, `maker`). Those two keys are the whole backend delta.

### 2.3 The test that a gap is never sign-flipped

Mirrors the live rows, with `side` flipped to `"no"` — a shape the live feed does not currently return, which is the point:

```python
def test_a_no_side_gap_is_the_mirror_and_the_words_still_name_pit():
    # Same contract as the live KXNFLSPREAD-26OCT01PITCLE-PIT8 row, side flipped to NO.
    row = {"kind": "spread", "side": "no", "our_prob": 0.629, "market_prob": 0.705,
           "title": "PIT Steelers wins by over 7.5 points?", "home": "CLE", "away": "PIT"}
    o = orient("spread", row["title"], row["side"], row["home"], row["away"])
    assert o.line == 7.5 and o.team_is_home is False       # the line is 7.5, NOT the ticker's 8
    assert "PIT" in o.statement and "CLE" not in o.statement
    assert gap_points(row["our_prob"], row["market_prob"], "no") == pytest.approx(-7.6)
    assert gap_points(row["our_prob"], row["market_prob"], "yes") == pytest.approx(-7.6)


def test_the_same_contract_keeps_its_gap_when_only_the_side_flips():
    yes = {"our_prob": 0.371, "market_prob": 0.295, "side": "yes"}      # the live row
    no = {"our_prob": 0.629, "market_prob": 0.705, "side": "no"}       # its complement
    assert gap_points(**yes) == pytest.approx(7.6)
    assert gap_points(**no) == pytest.approx(-7.6)   # opposite sign, same size
```

---

## 3. One market baseline per kind

### 3.1 Why each kind needs its own pair

`lib/journal.ts`'s `MARKET_PAIR` (`market_sentiment_tool/src/lib/journal.ts:82-88`) is a flat `Record<string, string>` keyed on the **model** forecaster name, and `tiles()` looks the baseline up by it:

```ts
export const MARKET_PAIR: Record<string, string> = {
  cpi_nowcast: "kalshi_implied_cpi",
  fomc_mapped: "kalshi_implied_fomc",
  labor_nowcast: "kalshi_implied_labor",
  sports_nfl: "kalshi_implied_sports_nfl",
  sports_cfb: "kalshi_implied_sports_cfb",
};
```

A spread model's Brier is only comparable against a baseline frozen **on the same spread contracts at the same moment**. Reusing the winner baseline would grade a spread probability against winner markets — different contracts, different noise — and BSS would be a number about nothing. So each kind gets its own model key and its own baseline key.

### 3.2 The keys

| sport | kind | model forecaster | baseline forecaster | family / target |
|---|---|---|---|---|
| nfl | winner | `sports_nfl` (exists) | `kalshi_implied_sports_nfl` (exists) | `kalshi:<winner ticker>` |
| nfl | spread | `sports_nfl_spread` | `kalshi_implied_sports_nfl_spread` | `kalshi:<spread ticker>` |
| nfl | total | `sports_nfl_total` | `kalshi_implied_sports_nfl_total` | `kalshi:<total ticker>` |
| cfb | winner | `sports_cfb` (exists) | `kalshi_implied_sports_cfb` (exists) | `kalshi:<winner ticker>` |
| cfb | spread | `sports_cfb_spread` | `kalshi_implied_sports_cfb_spread` | `kalshi:<spread ticker>` |
| cfb | total | `sports_cfb_total` | `kalshi_implied_sports_cfb_total` | `kalshi:<total ticker>` |

The version stays `feed-v1` for every model and `v1` for every baseline: the predictor's own `model_version` rides in the row payload (plan (l)), so the key names the consumer, not the model. Naming the kind in the key is what keeps a spread row from ever pairing with a winner baseline.

`MARKET_PAIR` gains four entries:

```diff
   sports_nfl: "kalshi_implied_sports_nfl",
   sports_cfb: "kalshi_implied_sports_cfb",
+  sports_nfl_spread: "kalshi_implied_sports_nfl_spread",
+  sports_nfl_total: "kalshi_implied_sports_nfl_total",
+  sports_cfb_spread: "kalshi_implied_sports_cfb_spread",
+  sports_cfb_total: "kalshi_implied_sports_cfb_total",
 };
```

### 3.3 Registry

`build_sports()` returns one model/baseline pair **per kind** instead of one per sport: 2 sports × 3 kinds × 2 = **12** forecasters, up from 4 (and the journal's total from 19 to 31). `SportsFeedForecaster` and `SportsMarketImplied` gain a `kind` argument; `targets()` filters the snapshot by it, so each pair shares the one hourly scan per sport.

---

## 4. Tasks

### Task 1: Orientation, with the sign-flip guard

**Files:** Create `tradehub/sports/orientation.py`, `tests/test_sports_orientation.py`. Modify `tradehub/sports/scan.py` (`raw_payload` gains `side` and `title`).

- [ ] **Step 1: write the failing test** — §2.1's `orient` and `gap_points` plus the §2.3 sign tests, and one test per real row shape from §1:

```python
import json
from pathlib import Path

import pytest

from tradehub.sports.orientation import gap_points, orient

# The 17 spread/total rows `GET /api/sports-edges?limit=200` returned on 2026-10-01, trimmed to the
# fields orientation reads. Live data, not invented: the ticker's integer is rounded, so a test that
# read the line from the ticker would pass on the wrong number.
FEED = json.loads((Path(__file__).parent / "fixtures" / "sports" / "spread_total_rows.json").read_text("utf-8"))


def test_every_live_spread_row_is_about_the_team_its_title_names():
    for row in FEED["spread"]:
        o = orient("spread", row["title"], row["side"], row["home"], row["away"])
        assert o is not None, row["title"]
        assert o.team_is_home is False          # PIT is the away side on all six
        assert o.line == float(row["title"].split("over ")[1].split(" ")[0])  # 7.5, not the ticker's 8


def test_every_live_total_row_is_over_its_title_line():
    for row in FEED["total"]:
        o = orient("total", row["title"], row["side"], row["home"], row["away"])
        assert o is not None and o.over and o.line == float(row["title"].split("over ")[1].split(" ")[0])


def test_a_no_side_gap_is_the_mirror_and_the_words_still_name_pit():
    # Same contract as the live KXNFLSPREAD-26OCT01PITCLE-PIT8 row, side flipped to NO.
    row = {"kind": "spread", "side": "no", "our_prob": 0.629, "market_prob": 0.705,
           "title": "PIT Steelers wins by over 7.5 points?", "home": "CLE", "away": "PIT"}
    o = orient("spread", row["title"], row["side"], row["home"], row["away"])
    assert o.line == 7.5 and o.team_is_home is False       # the line is 7.5, NOT the ticker's 8
    assert "PIT" in o.statement and "CLE" not in o.statement
    assert gap_points(row["our_prob"], row["market_prob"], "no") == pytest.approx(-7.6)


def test_the_same_contract_keeps_its_gap_when_only_the_side_flips():
    assert gap_points(0.371, 0.295, "yes") == pytest.approx(7.6)   # the live row
    assert gap_points(0.629, 0.705, "no") == pytest.approx(-7.6)   # its complement


def test_an_unparseable_title_is_none_rather_than_a_guess():
    assert orient("spread", "Who wins?", "yes", "CLE", "PIT") is None
    assert orient("total", "", "yes", "CLE", "PIT") is None
    assert orient("winner", "anything", "yes", "CLE", "PIT") is None
```

The fixture `tests/fixtures/sports/spread_total_rows.json` holds the 17 real rows exactly as returned (I have them; add them verbatim).

- [ ] **Step 2: run it** — `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_sports_orientation.py -v` → FAIL, `ModuleNotFoundError: tradehub.sports.orientation`.
- [ ] **Step 3: implement** §2.1, and add `"side": s.side, "title": sm.market.title,` to `raw_payload` in `scan.py`.
- [ ] **Step 4: run** the file plus `tests/test_sports_scan.py` (the payload change is additive).
- [ ] **Step 5: commit** `feat(sports): parse spread and total orientation from the market title`.

### Task 2: One target per contract, and the kind-keyed forecasters

**Files:** Modify `tradehub/journal/forecasters/sports.py`, `tradehub/journal/registry.py`. Test `tests/test_journal_sports.py`.

- [ ] **Step 1: failing tests.** Replace the `one_per_game` assertions with:

```python
def test_winner_rows_fold_but_every_spread_line_and_total_is_its_own_contract():
    rows = [
        {"market_ticker": "W-A", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "W-B", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "S-PIT8", "raw_payload": {"kind": "spread", "game_id": "g1"}},
        {"market_ticker": "S-PIT11", "raw_payload": {"kind": "spread", "game_id": "g1"}},
        {"market_ticker": "T-39", "raw_payload": {"kind": "total", "game_id": "g1"}},
        {"market_ticker": "T-38", "raw_payload": {"kind": "total", "game_id": "g1"}},
    ]
    assert set(journal_targets(rows)) == {"W-A", "S-PIT8", "S-PIT11", "T-39", "T-38"}


def test_the_registry_runs_three_kinds_per_sport_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS
    keys = [(f.name, f.version) for f in FORECASTERS]
    for expected in (("sports_nfl", "feed-v1"), ("sports_nfl_spread", "feed-v1"), ("sports_nfl_total", "feed-v1"),
                     ("kalshi_implied_sports_nfl", "v1"), ("kalshi_implied_sports_nfl_spread", "v1"),
                     ("kalshi_implied_sports_nfl_total", "v1"),
                     ("sports_cfb", "feed-v1"), ("sports_cfb_spread", "feed-v1"), ("sports_cfb_total", "feed-v1"),
                     ("kalshi_implied_sports_cfb", "v1"), ("kalshi_implied_sports_cfb_spread", "v1"),
                     ("kalshi_implied_sports_cfb_total", "v1")):
        assert expected in keys, expected
    assert len(set(keys)) == len(keys) and len(build_sports()) == 12
```

and one test that a spread model's payload carries the orientation and a side-aware gap:

```python
def test_a_spread_forecast_row_states_its_orientation_and_a_side_aware_gap():
    snapshot = SportsSnapshot("nfl", _scan("nfl"))
    fc = SportsFeedForecaster(snapshot, _final("yes"), kind="spread")
    entry = next(e for e in fc.targets(PRE_GAME) if e.target.startswith("kalshi:KXNFLSPREAD-"))
    payload = fc.forecast(entry, PRE_GAME).payload
    assert payload["orientation"]["line"] == 7.5          # not the ticker's 8
    assert payload["orientation"]["team_is_home"] is False
    assert payload["orientation"]["statement"].startswith("PIT")
    assert payload["gap_points"] == pytest.approx(payload["market_prob"] - payload["probability"]) * 100 \
        or payload["gap_points"] == pytest.approx((payload["probability"] - payload["market_prob"]) * 100)
```

- [ ] **Step 2: run** `tests/test_journal_sports.py` → FAIL (`journal_targets` missing; registry has 4 sports keys, not 12).
- [ ] **Step 3: implement.**

```python
def journal_targets(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{ticker: row} — one entry per CONTRACT.

    A winner market exists for both teams and the two rows are exact complements, so they fold to one
    bet (the first ticker in ASCII order, as plan (l) did). A spread line and a total are NOT
    duplicates: one game carried 6 spread lines and 11 totals on 2026-10-01, each its own contract
    with its own price and its own Kalshi result. Folding those would grade the journal on 1 of 17.
    """
    by_ticker: dict[str, dict[str, Any]] = {}
    winners: dict[str, dict[str, Any]] = {}
    for row in predictions:
        payload = row.get("raw_payload") or {}
        if payload.get("kind") == "winner":
            game = payload["game_id"]
            held = winners.get(game)
            if held is None or row["market_ticker"] < held["market_ticker"]:
                winners[game] = row
        else:
            by_ticker[row["market_ticker"]] = row
    for row in winners.values():
        by_ticker[row["market_ticker"]] = row
    return by_ticker
```

`SportsFeedForecaster` / `SportsMarketImplied` take `kind="winner"`, filter `journal_targets` by it, and `_payload()` adds `side`, `market_title`, `home`, `away`, `orientation` and the side-aware `gap_points` per §2.2. `build_sports()` loops `SPORTS × ("winner", "spread", "total")` and names each pair per §3.2.

- [ ] **Step 4: run** `tests/test_journal_sports.py tests/test_sports_scan.py tests/test_sports_feed.py`.
- [ ] **Step 5: commit** `feat(journal): journal NFL and CFB spread and total markets`.

### Task 3: Pair each kind on /journal, then verify

**Files:** Modify `market_sentiment_tool/src/lib/journal.ts`, `market_sentiment_tool/src/lib/journal.test.ts`.

- [ ] **Step 1: failing test** — the `MARKET_PAIR` test gains the four new pairs and asserts no kind pairs with another kind:

```ts
it("pairs every sports model with a baseline of the same kind, and never across kinds", () => {
  expect(catalogueCounts).toBeDefined();
  expect(MARKET_PAIR.sports_nfl_spread).toBe("kalshi_implied_sports_nfl_spread");
  expect(MARKET_PAIR.sports_nfl_total).toBe("kalshi_implied_sports_nfl_total");
  expect(MARKET_PAIR.sports_cfb_spread).toBe("kalshi_implied_sports_cfb_spread");
  expect(MARKET_PAIR.sports_cfb_total).toBe("kalshi_implied_sports_cfb_total");
  for (const [model, baseline] of Object.entries(MARKET_PAIR)) {
    const modelKind = model.split("_").pop();
    expect(baseline.split("_").pop()).toBe(modelKind);
  }
});
```

- [ ] **Step 2: run** `npx vitest run src/lib/journal.test.ts` → FAIL on the four `undefined` pairs.
- [ ] **Step 3: implement** §3.2's diff.
- [ ] **Step 4: verification.**

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
.venv/bin/python -m ruff check tradehub/sports/orientation.py tradehub/sports/scan.py tradehub/journal/forecasters/sports.py tradehub/journal/registry.py tests/test_sports_orientation.py tests/test_journal_sports.py
cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/lib/journal.ts && npx vite build
```

- [ ] **Step 5: commit** `feat(ui): pair each sports kind with its own market baseline`.

### Task 4: Live check, then open the PR

- [ ] Run the journal against the deployed API and paste the output: the new forecasters' `registered` / `frozen` counts, and confirm the spread/total `orientation` in a real payload names the away team and carries the title's line. **State plainly if the live scan returns no spread or total rows** — today's live feed had 6 and 11, but a quiet board is a real outcome, not a reason to round the number up.
- [ ] PR body: the four §1 tables (quoted live rows), the sign-flip guard, the §3 key table, the `MARKET_PAIR` rule, the forecaster-count change 19 → 31 and why, and the verification output. Say plainly that the code here was written but **not executed** before this plan was written.

---

## Self-Review

- **Spec §8 Sports:** predictors plug in as consumed graded outputs through `/api/kalshi-feed`; the journal still never re-settles a game (settlement stays `settle_on_kalshi`); NFL and CFB only; plan (l)'s ranking/window/inversion work is untouched, since the same scan prices these rows.
- **Gate honesty:** one target per **contract** keeps the settled count comparable to the 200-target daily bar; model and baseline are frozen at the same moment on the same contract, so BSS is apples-to-apples per kind.
- **The two failure modes this plan exists to prevent**, each with a test: a spread line or total silently folded away (§1.4, `test_winner_rows_fold_but_every_spread_line_and_total_is_its_own_contract`), and a gap sign-flipped on a NO row or relabelled onto the other team (§1.5, `test_a_no_side_gap_is_the_mirror_and_the_words_still_name_pit`).
- **Honesty about the code:** §1 is checked against live data; §2–§4 are written but unexecuted. A reviewer should read §2.1's `orient` closely — the `named = team if (is_home or is_away) else team` line is a leftover from an earlier draft and is a no-op that should be simplified before merge.
- **Not in this plan:** the /sports page's display of spread and total rows (`lib/sportsPicks.ts` folds by `game_id|kind` and would show one row for 11 totals — that is a separate UI decision about how many lines to list), the remaining roadmap items 12–14, and the research plans.
