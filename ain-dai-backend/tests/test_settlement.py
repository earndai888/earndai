from decimal import Decimal

import pytest

from app.settlement import FeeConfig, compute_split


def test_1000_baht():
    s = compute_split(1000)
    assert s.provider_net == Decimal("890.00")
    assert s.platform_fee == Decimal("80.00")
    assert s.fund_amount == Decimal("20.00")
    assert s.tax_withheld == Decimal("10.00")


def test_sum_always_equals_gross():
    """เงินสี่ก้อนต้องรวมเท่า gross เป๊ะ แม้ยอดหารไม่ลงตัว"""
    for gross in ["333", "199.50", "457.77", "1", "99999.99", "512.34"]:
        s = compute_split(gross)
        assert s.provider_net + s.platform_fee + s.fund_amount + s.tax_withheld == Decimal(gross).quantize(Decimal("0.01"))


def test_odd_amount_rounding():
    s = compute_split("333")
    assert s.platform_fee == Decimal("26.64")
    assert s.fund_amount == Decimal("6.66")
    assert s.tax_withheld == Decimal("3.33")
    assert s.provider_net == Decimal("296.37")


def test_custom_config():
    cfg = FeeConfig(provider_pct=Decimal("0.90"), platform_pct=Decimal("0.08"),
                    fund_pct=Decimal("0.02"), tax_pct=Decimal("0.03"))
    s = compute_split(1000, cfg)
    assert s.tax_withheld == Decimal("30.00")
    assert s.provider_net == Decimal("870.00")


def test_zero_rejected():
    with pytest.raises(ValueError):
        compute_split(0)
