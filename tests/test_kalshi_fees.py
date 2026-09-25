from shared.kalshi_fees import kalshi_fee_cents


def test_kalshi_fee_rounds_the_total_order_fee_up_to_a_whole_cent():
    assert kalshi_fee_cents(44.0) == 2.0
    assert kalshi_fee_cents(44.0, contracts=10) == 18.0
    assert kalshi_fee_cents(40.0, maker=True) == 1.0
    assert kalshi_fee_cents(40.0, contracts=10, maker=True) == 5.0


def test_kalshi_fee_uses_integer_math_for_dusty_probabilities():
    assert kalshi_fee_cents(50.0, contracts=4) == 7.0
    assert kalshi_fee_cents(50.0, contracts=16, maker=True) == 7.0


def test_kalshi_fee_matches_whole_cent_examples():
    assert kalshi_fee_cents(10.0, contracts=100) == 63.0
    assert kalshi_fee_cents(20.0, contracts=25) == 28.0
    assert kalshi_fee_cents(20.0, contracts=25, maker=True) == 7.0
