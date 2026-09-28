"""A missing table, a missing credential and a bug in this code are three different problems, and
`/api/shadow-performance` served all three as the same thing.

Found on 2026-09-28, after PR #42. The owner is about to apply
`20260428000013_signal_events_publication_and_rls.sql` to finish the half-applied
`20260415090000_signal_events_unification.sql`, after which the missing-table 503 stops firing -- and
nothing else had been checked. What fires instead is this:

    build_shadow_timeline_response
      -> build_shadow_report
        -> _latest_bar_status("BTC")
          -> _fetch_alpaca_hourly_closes
            -> _alpaca_config()      # RuntimeError("Missing Alpaca API credentials ...")

`vps-stack/compose.yml` passes `SUPABASE_*`, `SPORTS_*`, `OPENROUTER_API_KEY` and `FRED_API_KEY` to
the tradehub service and **no `ALPACA_*`**, so this is the live state, not a hypothetical. The
handler had one `except` for the whole builder, so the credential failure was reported the way a
missing table is reported and the reader got a bare "Missing Alpaca API credentials" string with
nothing about what to set, where, or that the table was by then perfectly fine.

The deeper defect is the shape of the mistake, not the string. Two changes here are load-bearing and
each has its own test:

- `_table_fault` had a single `except RuntimeError` that assumed every RuntimeError was a missing
  table. It now decides between three cases, and decides on the STATUS, because the status is the
  one field a client can branch on without parsing English. A prose difference is not a
  machine-readable difference.
- `build_shadow_timeline_response` re-raised `RuntimeError(str(report["errors"][0]))`, flattening a
  typed `MissingCredentialError` -- which carries the exact variable names as attributes -- into an
  undifferentiated string. Any classification downstream of that line was working from a substring,
  which is why the one branch it had guessed wrong. The original exception now survives the
  wrapping, and `test_the_credential_type_survives_the_builders_error_wrapping` fails if it does not.

These are deliberately tests of the HANDLER, driving it with the real exceptions the real code
raises. A test that monkeypatched `build_shadow_timeline_response` to fail would prove the same
thing for every one of them and would not notice the wrapping bug above.
"""
from __future__ import annotations

import asyncio
import re

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

from tradehub.api import main as api_main
from tradehub.scripts import shadow_performance as sp


# ── The three cases, each as the real exception the real code raises ────────────

def _missing_table() -> APIError:
    """What postgREST raises when `signal_events` is not in the schema cache.

    `APIError` derives straight from `Exception`, which is how a branch that catches RuntimeError to
    recognise a missing table shipped dead. Nothing here fakes a RuntimeError with the same words.
    """
    return APIError({
        "message": "Could not find the table 'public.signal_events' in the schema cache",
        "code": "PGRST205",
        "hint": "Perhaps you meant the table 'public.crypto_signal_events'.",
        "details": None,
    })


def _missing_credential() -> sp.MissingCredentialError:
    """What `_alpaca_config()` raises on the VPS today: the compose file supplies no ALPACA_*."""
    return sp.MissingCredentialError("Alpaca API", ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"))


def _genuine_bug() -> TypeError:
    """A real defect in the builder, which must stay a 500 and must not be dressed as an operator step."""
    return TypeError("unsupported operand type(s) for +: 'int' and 'NoneType'")


def _handler(exc: Exception) -> HTTPException:
    """Drive the real handler and return the HTTPException it raised."""
    with pytest.raises(HTTPException) as caught:
        asyncio.run(api_main.get_shadow_performance(domain="crypto", hours=24))
    return caught.value


# ── Case 1: the table is missing. A migration, and a 503 that says so. ─────────

def test_a_missing_table_is_a_503_naming_the_migration(monkeypatch):
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_missing_table()))

    fault = _handler(_missing_table())

    assert fault.status_code == 503
    assert "20260415090000_signal_events_unification.sql" in str(fault.detail)
    assert fault.headers["X-Error-Code"] == "missing_table"


# ── Case 2: the table is fine, a credential is not. A DIFFERENT status. ────────

def test_a_missing_credential_is_not_reported_as_a_missing_table(monkeypatch):
    """The whole point of the PR, as one assertion.

    Same handler, same builder, same table. Only the credential is missing. If this returns 503 with
    a migration in it, an operator applies a migration they already applied and the page stays red.
    """
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_missing_credential()))

    fault = _handler(_missing_credential())

    assert fault.status_code != 503, (
        "a missing credential must not share a status with a missing table: an operator cannot tell "
        "which of the two deployment steps is outstanding"
    )
    assert ".sql" not in str(fault.detail), (
        f"an unset credential is not a migration, and must not be dressed as one: {fault.detail}"
    )
    assert "supabase/migrations/" not in str(fault.detail), fault.detail


def test_a_missing_credential_names_the_variables_and_where_to_set_them(monkeypatch):
    """"Missing Alpaca API credentials" is the name of the problem, not an instruction. The reader
    still has to work out which variables, in which file, on which machine -- and `compose.yml` will
    not pass them through even once they are set, so the service block has to change too."""
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_missing_credential()))

    detail = str(_handler(_missing_credential()).detail)

    assert "ALPACA_API_KEY" in detail, detail
    assert "ALPACA_SECRET_KEY" in detail, detail
    # Where, not just what. compose.yml is the file that decides what the container receives.
    assert "compose.yml" in detail, detail
    assert "ALPACA_API_KEY: ${ALPACA_API_KEY:-}" in detail, detail
    # And it says the table is fine, because that is the thing the old 500 failed to say.
    assert "not a migration" in detail, detail


def test_a_missing_credential_does_not_read_as_a_migration_to_the_frontend(monkeypatch):
    """The frontend classifies a failed read by matching `/supabase/migrations/` in the detail
    (`market_sentiment_tool/src/lib/shadowPerformance.ts`, `shadowUnavailable`). If this detail ever
    contained a migration path the page would headline "Waiting on a database migration" for a
    problem no migration can fix. Pinned here because the frontend is out of scope for this change
    and cannot defend itself."""
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_missing_credential()))

    detail = str(_handler(_missing_credential()).detail)

    assert re.search(r"supabase/migrations/", detail) is None, detail


# ── Case 3: the code is broken. A 500, and it stays one. ───────────────────────

def test_a_genuine_type_error_is_still_a_500(monkeypatch):
    """The branch this PR adds must not swallow real bugs. A TypeError inside the builder is a fact
    about this code, not about the deployment, so it is a 500 carrying the exception text and
    nothing that sends an operator off to apply a file or set a variable."""
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_genuine_bug()))

    fault = _handler(_genuine_bug())

    assert fault.status_code == 500
    detail = str(fault.detail)
    assert "unsupported operand" in detail, detail
    assert ".sql" not in detail, detail
    assert "ALPACA" not in detail, detail
    assert fault.headers["X-Error-Code"] == "internal_error"


def test_an_unplanned_runtime_error_is_still_a_500_and_not_an_operator_step(monkeypatch):
    """The generalisation, and the reason this is not just a special case for Alpaca.

    The old handler's defect was an ASSUMPTION -- that every RuntimeError out of the builder is a
    missing table -- and it will be wrong again the next time some new RuntimeError is raised in
    there. A credential class catches the credentials we know about; it must not become a net that
    turns every future RuntimeError into "an operator has a step to do".
    """
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(
        RuntimeError("frame.shape is a method, not a tuple")))

    fault = _handler(RuntimeError("frame.shape is a method, not a tuple"))

    assert fault.status_code == 500, fault.detail
    assert fault.headers["X-Error-Code"] == "internal_error"


# ── The three are distinguishable by STATUS, which is what a client branches on ──

@pytest.mark.parametrize(
    "exc, expected_status, expected_code",
    [
        pytest.param(_missing_table, 503, "missing_table", id="missing_table"),
        pytest.param(_missing_credential, 424, "missing_credentials", id="missing_credential"),
        pytest.param(_genuine_bug, 500, "internal_error", id="internal_error"),
    ],
)
def test_each_failure_case_has_its_own_status_and_its_own_code(exc, expected_status, expected_code,
                                                                monkeypatch):
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(exc()))

    fault = _handler(exc())

    assert fault.status_code == expected_status
    assert fault.headers["X-Error-Code"] == expected_code


def test_the_three_cases_are_three_distinct_answers(monkeypatch):
    """Measured, not asserted in prose: three exceptions in, three distinct (status, code, detail)
    triples out. If any two collapsed, an operator would have two different problems and one answer.
    """
    answers = []
    for exc in (_missing_table, _missing_credential, _genuine_bug):
        monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(exc()))
        fault = _handler(exc())
        answers.append((fault.status_code, fault.headers.get("X-Error-Code"), str(fault.detail)))

    assert len(set(answers)) == 3, f"two of the three cases produced the same answer: {answers}"
    assert len({status for status, _, _ in answers}) == 3, answers
    assert len({code for _, code, _ in answers}) == 3, answers


# ── The regression that made this unfixable from the outside ──────────────────

def test_the_credential_type_survives_the_builders_error_wrapping(monkeypatch):
    """The bug, end to end through the real builder rather than a stubbed one.

    `build_shadow_report` collects failures as STRINGS for the Telegram report, and
    `build_shadow_timeline_response` used to re-raise `RuntimeError(str(errors[0]))`. That re-wrap
    is what made this endpoint undiagnosable: it took a `MissingCredentialError` carrying
    `("ALPACA_API_KEY", "ALPACA_SECRET_KEY")` as attributes and produced a bare RuntimeError whose
    only content was a sentence, after which the API had nothing to classify but a substring. The
    type now survives, and this fails if it stops surviving.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://stub.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stub-service-role")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(sp, "_load_supabase_client", lambda: _EmptySignalEvents())

    # The real builder, no stubbing of the thing under test.
    with pytest.raises(sp.MissingCredentialError) as caught:
        sp.build_shadow_timeline_response(hours=24, domain="crypto")

    assert caught.value.variables == ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")
    assert api_main._is_missing_credential(caught.value) is True
    assert api_main._is_missing_table(caught.value) is False


def test_the_telegram_path_still_gets_its_strings(monkeypatch):
    """`build_shadow_report` is also driven by a cron job that renders a text report
    (`tradehub.core.telegram_notifier`). Adding a typed exception must not have changed what that
    report reads: `errors` stays a list of strings, in the same order, with the same dedup."""
    monkeypatch.setenv("SUPABASE_URL", "https://stub.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "stub-service-role")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(sp, "_load_supabase_client", lambda: _EmptySignalEvents())

    report = sp.build_shadow_report(hours=24, domain="crypto")

    assert report["errors"], report
    assert all(isinstance(message, str) for message in report["errors"]), report["errors"]
    assert "ALPACA_API_KEY" in report["errors"][0], report["errors"]
    assert "ALPACA_API_KEY" in sp.render_shadow_report(report)
    # The freshness loop hits both assets, and the same message is not listed twice.
    assert len(report["errors"]) == len(set(report["errors"])), report["errors"]


# ── One helper, so the other two readers get this for free ────────────────────

def test_the_other_two_table_readers_get_the_same_three_way_decision(monkeypatch):
    """`_table_fault` is the single place a failed read becomes an HTTP answer, and the War Room
    scoreboard and the CPI nowcast both raise through it. A credential failure on either of those
    must not come back as a migration prompt -- and the reason the decision is in one helper is
    precisely that three handlers each picking their own exception class is what broke this once."""
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(_missing_credential()))

    fault = _handler(_missing_credential())

    # The helper, not this handler, is the unit that decides.
    assert fault is not None
    for table in ("backtest_runs", "predictions", "signal_events"):
        assert api_main._table_fault(table, _missing_credential()).status_code == 424, table
        assert api_main._table_fault(table, _missing_table()).status_code == 503, table
        assert api_main._table_fault(table, _genuine_bug()).status_code == 500, table


def test_a_credential_error_from_another_module_is_still_classified(monkeypatch):
    """`market_sentiment_tool`'s orchestrator raises its own RuntimeError for the same two
    variables. A classifier that only understood this module's class would go back to guessing the
    moment a second caller appeared, which is the same failure mode as the dead `except
    RuntimeError`."""
    monkeypatch.setattr(api_main, "build_shadow_timeline_response", _raising(
        RuntimeError("Missing Alpaca API credentials for crypto feature fetch.")))

    fault = _handler(RuntimeError("Missing Alpaca API credentials for crypto feature fetch."))

    assert fault.status_code == 424
    assert "ALPACA_API_KEY" in str(fault.detail), fault.detail


# ── helpers ───────────────────────────────────────────────────────────────────

def _raising(exc: Exception):
    def _raise(**_kwargs):
        raise exc
    return _raise


class _EmptySignalEvents:
    """`signal_events` present and empty -- what production looks like the moment the rename lands
    on a project that has never graded a signal. Chainable no-op, so these tests fail on real logic
    rather than on a missing builder method."""

    def table(self, name):
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return type("R", (), {"data": [], "count": 0})()
