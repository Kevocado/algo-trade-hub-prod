from datetime import datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Decision, LeakageError, Observation, check_no_lookahead

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def test_features_published_before_decision_pass():
    d = Decision("KXHIGHNY-26JUL24-T88", T0, 0.3, (Observation("f", 1.0, T0 - timedelta(hours=1)),))
    check_no_lookahead(d)


def test_feature_published_exactly_at_decision_passes():
    check_no_lookahead(Decision("T", T0, 0.5, (Observation("f", 1.0, T0),)))


def test_feature_published_after_decision_raises_and_names_it():
    late = Observation("late_feature", 1.0, T0 + timedelta(seconds=1))
    ok = Observation("ok_feature", 1.0, T0 - timedelta(days=1))
    with pytest.raises(LeakageError, match="late_feature"):
        check_no_lookahead(Decision("T", T0, 0.5, (ok, late)))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        check_no_lookahead(Decision("T", datetime(2026, 7, 24, 12), 0.5))
    with pytest.raises(ValueError):
        check_no_lookahead(Decision("T", T0, 0.5, (Observation("f", 1.0, datetime(2026, 7, 24)),)))
