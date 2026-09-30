"""Wave 2 tests (spec §8): VIX, Gold, EUR/USD daily direction forecasters."""

from datetime import UTC, datetime


def test_wave2_forecasters_registered():
    """All three Wave 2 forecasters appear in the registry."""
    from tradehub.journal.registry import FORECASTERS
    names = {f.name for f in FORECASTERS}
    assert "vix_direction" in names
    assert "gold_direction" in names
    assert "eurusd_direction" in names


def test_wave2_baseline_formula_exists():
    """The baseline probability formula is documented and importable."""
    from tradehub.journal.forecasters.wave2_daily import PERSISTENCE_BLEND
    assert 0 < PERSISTENCE_BLEND < 1
