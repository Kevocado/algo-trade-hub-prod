"""An in-memory Supabase stand-in for the journal, including the migration's trigger rules.

It mirrors the database guarantees (tests/test_journal_migration_pg.py proves the real ones) so the
Python pipeline can be tested for how it *reacts* to refusals: late freeze, no calendar row,
settlement before cutoff, immutability. `clock` is what "now()" means inside the fake database.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db: FakeJournalDB, table: str):
        self.db, self.table, self.filters, self.lo, self.hi, self.op, self.payload = db, table, [], None, None, "select", None
        self.order_by: tuple[str, ...] = ()

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.filters.append(lambda r, c=col, v=vals: r.get(c) in v)
        return self

    def order(self, *cols, desc=False, **_k):
        self.order_by, self.desc = cols, desc
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def limit(self, n):
        self.lo, self.hi = 0, n - 1
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def upsert(self, row, on_conflict):
        self.op, self.payload, self.conflict = "upsert", row, on_conflict.split(",")
        return self

    def execute(self):
        if self.op == "insert":
            return _Result([self.db.insert(self.table, dict(self.payload))])
        if self.op == "upsert":
            return _Result([self.db.upsert(self.table, dict(self.payload), self.conflict)])
        rows = [r for r in self.db.tables[self.table] if all(f(r) for f in self.filters)]
        if self.order_by:
            rows.sort(key=lambda r: tuple(r.get(c) for c in self.order_by), reverse=getattr(self, 'desc', False))
        if self.lo is not None:
            rows = rows[self.lo:self.hi + 1]
        return _Result([dict(r) for r in rows])


class FakeJournalDB:
    def __init__(self, clock: Callable[[], datetime]):
        self.clock = clock
        self.tables: dict[str, list[dict[str, Any]]] = {
            "journal_calendars": [], "journal_forecasts": [], "journal_settlements": [], "journal_scores": [],
            "backtest_runs": [], "track_record": [],
        }
        self._id = 0

    def table(self, name):
        return _Query(self, name)

    def _cutoff(self, target):
        for row in self.tables["journal_calendars"]:
            if row["target"] == target:
                return datetime.fromisoformat(row["cutoff_at"])
        return None

    def insert(self, table, row):
        now = self.clock()
        if table == "journal_calendars":
            if datetime.fromisoformat(row["cutoff_at"]) <= now:
                raise RuntimeError("journal: calendar cutoff is not in the future")
            if any(r["target"] == row["target"] for r in self.tables[table]):
                raise RuntimeError("duplicate key")
        elif table == "journal_forecasts":
            cutoff = self._cutoff(row["target"])
            if cutoff is None:
                raise RuntimeError("journal: no calendar row for target")
            if now >= cutoff:
                raise RuntimeError("journal: freeze refused, cutoff has passed")
            key = (row["forecaster"], row["forecaster_version"], row["target"])
            if any((r["forecaster"], r["forecaster_version"], r["target"]) == key for r in self.tables[table]):
                raise RuntimeError("duplicate key")
            self._id += 1
            row.update(id=self._id, frozen_at=now.isoformat(), rebuilt=False)
        elif table == "journal_settlements":
            cutoff = self._cutoff(row["target"])
            if cutoff is None or now < cutoff:
                raise RuntimeError("journal: settlement refused before its cutoff")
            if any(r["target"] == row["target"] for r in self.tables[table]):
                raise RuntimeError("duplicate key")
            row["settled_at"] = now.isoformat()
        self.tables[table].append(row)
        return row

    def upsert(self, table, row, conflict):
        if table != "journal_scores":
            raise RuntimeError(f"{table} is immutable")
        rows = self.tables[table]
        for i, existing in enumerate(rows):
            if all(existing.get(c) == row.get(c) for c in conflict):
                rows[i] = row
                return row
        rows.append(row)
        return row
