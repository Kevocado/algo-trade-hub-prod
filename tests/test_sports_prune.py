"""B5: stale sports edges — three gaps in the round-2 pruning.

1. **Pruning is driven by the produced edges.** The round-2 code derived the engine set from
   `sports_edges`, so a sport that legitimately produced ZERO edges (no market cleared the
   candidate filter this hour) pruned nothing — its previous rows stayed up forever. The set of
   engines to prune must come from the CONFIGURED sports, not from what happened to be produced.
   A feed error must still never prune, so the signal is "this sport's feed fetch AND its edge
   upsert both succeeded", which is only knowable per sport.

2. **Started games are never removed.** `remove_stale_edges` only deletes rows whose market_id is
   absent from the produced set. A game that kicked off keeps its row on the board until some
   later scan happens to omit it. Sports rows must also be deleted once the game has started.
   (Round 4: the predicate is the indexed `start_utc` game start. It was `expires_at`, which for
   a sports market is the Kalshi close time — about two days after kickoff — so the delete
   almost never fired when it mattered. `tests/test_sports_started_games.py` covers the gap.)

3. Feed errors never prune — the invariant that makes the rest of this safe.
"""
from datetime import datetime, timedelta, timezone

from tradehub.sports import scan as sports_scan

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(hours=48)).isoformat()
PAST = (NOW - timedelta(hours=3)).isoformat()


def _sports_cfg(engine, sport):
    from tradehub.sports.config import SportConfig
    return SportConfig(sport=sport, engine=engine, base_url="", site_url="",
                       series={}, series_titles={}, edge=None)


# ── (1) prune by configured sport, including a zero-edge run ───────────────────

def test_prune_targets_come_from_configured_sports_not_produced_edges():
    """The engine set must be the configured sports, so a sport that produced nothing is
    still pruned. Round 2 derived it from the produced rows and so never pruned that case."""
    produced = []                       # this sport produced nothing at all
    engines = sports_scan.sports_prune_targets(produced)
    assert engines == {"sports_nfl", "sports_cfb"}, (
        f"prune targets were {engines}; a zero-edge run must still prune its engine"
    )


def test_prune_targets_ignore_unknown_engines_in_the_rows():
    """A row from some other writer must not add an engine to the prune set."""
    produced = [{"engine": "sports_nfl", "market_ticker": "A"},
                {"engine": "not_a_sport", "market_ticker": "B"}]
    targets = sports_scan.sports_prune_targets(produced)
    assert "not_a_sport" not in targets
    assert targets == {"sports_nfl", "sports_cfb"}


def test_sport_prunes_when_feed_and_write_both_succeeded_even_with_zero_edges():
    from tradehub.sports import scan as sports

    calls = []
    assert sports.prune_sports_if_healthy(
        client="supa",
        per_sport={"nfl": {"feed_ok": True, "write_ok": True, "edges": []}},
        remove= lambda client, produced: calls.append(produced),
        now=NOW,
    ) is not None
    assert {"sports_nfl": set()} in calls, f"a zero-edge NFL run did not prune: {calls}"
    assert "sports_cfb" not in calls[0], "CFB had no feed result and must not be pruned"


# ── (2) started games are deleted ─────────────────────────────────────────────

def test_started_sports_rows_are_deleted_using_start_utc():
    """A game that kicked off must leave the board even though the market_id may still appear
    in the produced set on a later scan.

    Round 3 filtered on `expires_at`, which for a sports market is the Kalshi close time — about
    two days AFTER kickoff — so the delete did not fire until long after the game started. The
    predicate is now the indexed game start.
    """
    deleted = []

    class Q:
        def __init__(self, store):
            self.store = store

        def select(self, *_a):
            return self

        def eq(self, k, v):
            self.store.filters[k] = v
            return self

        def lte(self, k, v):
            self.store.filters[k] = v
            self.store.lte_used = True
            return self

        def delete(self):
            return self

        def execute(self):
            self.store.deleted.append(dict(self.store.filters))
            return type("R", (), {"data": None})()

    class Store:
        def __init__(self):
            self.filters: dict = {}
            self.deleted: list = []
            self.lte_used = False

        def table(self, name):
            self.filters = {}
            return Q(self)

    store = Store()
    sports_scan.remove_started_sports_edges(store, NOW)
    assert store.lte_used, "the started-game delete did not use a lte() bound"
    assert {d["engine"] for d in store.deleted} == {"sports_nfl", "sports_cfb"}, store.deleted
    assert all(d["start_utc"] == NOW.isoformat() for d in store.deleted), store.deleted


def test_started_sports_cleanup_failure_is_isolated_and_reported():
    class Q:
        def __init__(self, engine_holder):
            self.engine_holder = engine_holder

        def select(self, *_a):
            return self

        def eq(self, k, v):
            self.engine_holder["engine"] = v
            return self

        def lte(self, k, v):
            self.engine_holder["start_utc"] = v
            return self

        def delete(self):
            return self

        def execute(self):
            if self.engine_holder.get("engine") == "sports_nfl":
                raise RuntimeError("boom")
            self.engine_holder.setdefault("ok", []).append(self.engine_holder["engine"])
            return type("R", (), {"data": None})()

    class Supa:
        def __init__(self):
            self.engine_holder: dict = {}

        def table(self, name):
            self.engine_holder = {}
            return Q(self.engine_holder)

    holder = {"ok": []}
    supa = Supa()
    orig = supa.table

    def table(name):
        q = orig(name)
        q.engine_holder = holder
        return q

    supa.table = table
    errors = sports_scan.remove_started_sports_edges(supa, NOW)
    assert holder["ok"] == ["sports_cfb"], "the healthy sport was skipped after the other failed"
    assert any("sports_nfl" in e for e in errors), errors


def test_started_sports_delete_is_engine_scoped():
    deleted = []

    class Q:
        def __init__(self):
            self.filters = {}

        def select(self, *_a):
            return self

        def eq(self, k, v):
            self.filters[k] = v
            return self

        def lte(self, k, v):
            self.filters[k] = v
            return self

        def delete(self):
            return self

        def execute(self):
            deleted.append(dict(self.filters))
            return type("R", (), {"data": None})()

    class Supa:
        def table(self, name):
            return Q()

    sports_scan.remove_started_sports_edges(Supa(), NOW)
    assert len(deleted) == 2, "expected one delete per sport engine"
    assert {d["engine"] for d in deleted} == {"sports_nfl", "sports_cfb"}


# ── (3) a feed error never prunes ──────────────────────────────────────────────

def test_a_feed_error_never_prunes_that_sport():
    from tradehub.sports import scan as sports

    calls = []
    sports.prune_sports_if_healthy(
        client="supa",
        per_sport={"nfl": {"feed_ok": False, "write_ok": True, "edges": []},
                   "cfb": {"feed_ok": True, "write_ok": True, "edges": []}},
        remove=lambda client, produced: calls.append(produced),
        now=NOW,
    )
    assert "sports_nfl" not in calls[0], "a feed error pruned the sport"
    assert "sports_cfb" in calls[0], "the healthy sport should still prune"


def test_a_failed_write_never_prunes_that_sport():
    from tradehub.sports import scan as sports

    calls = []
    sports.prune_sports_if_healthy(
        client="supa",
        per_sport={"nfl": {"feed_ok": True, "write_ok": False, "edges": []}},
        remove=lambda client, produced: calls.append(produced),
        now=NOW,
    )
    assert calls == [], f"a failed edge write pruned anyway: {calls}"


def test_prune_errors_are_isolated_per_sport():
    """One sport's cleanup blowing up must not stop the other sport's, nor the scan."""
    from tradehub.sports import scan as sports

    seen = []

    def remove(client, produced):
        seen.append(set(produced))
        if "sports_nfl" in produced:
            raise RuntimeError("cleanup boom")

    errors = sports.prune_sports_if_healthy(
        client="supa",
        per_sport={"nfl": {"feed_ok": True, "write_ok": True, "edges": []},
                   "cfb": {"feed_ok": True, "write_ok": True, "edges": []}},
        remove=remove,
        now=NOW,
    )
    assert {"sports_nfl"} in seen and {"sports_cfb"} in seen, "the second sport was skipped"
    assert any("sports_nfl" in e for e in errors), errors
    assert not any("sports_cfb" in e for e in errors), errors
