from shared.kalshi_fees import kalshi_fee_cents


def test_kalshi_fee_rounds_the_total_order_fee_up_to_a_whole_cent():
    assert kalshi_fee_cents(44.0) == 2.0
    assert kalshi_fee_cents(44.0, contracts=10) == 18.0
    assert kalshi_fee_cents(40.0, maker=True) == 1.0
    assert kalshi_fee_cents(40.0, contracts=10, maker=True) == 5.0
