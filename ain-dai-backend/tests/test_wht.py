from decimal import Decimal

from app.wht import baht_text


def test_baht_text_basic():
    assert baht_text(0) == "ศูนย์บาทถ้วน"
    assert baht_text(1) == "หนึ่งบาทถ้วน"
    assert baht_text(21) == "ยี่สิบเอ็ดบาทถ้วน"
    assert baht_text(100) == "หนึ่งร้อยบาทถ้วน"
    assert baht_text(111) == "หนึ่งร้อยสิบเอ็ดบาทถ้วน"


def test_baht_text_satang():
    assert baht_text(Decimal("3.50")) == "สามบาทห้าสิบสตางค์"
    assert baht_text(Decimal("123.45")) == "หนึ่งร้อยยี่สิบสามบาทสี่สิบห้าสตางค์"


def test_baht_text_large():
    assert baht_text(1_000_000) == "หนึ่งล้านบาทถ้วน"
    assert baht_text(2_500_000) == "สองล้านห้าแสนบาทถ้วน"
