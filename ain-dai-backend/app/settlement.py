"""คำนวณการแบ่งเงิน (แบบ ก)

ช่างได้ 90% ของค่างาน แล้วหักภาษี ณ ที่จ่าย 1% ของค่างานเต็มออกจากส่วนช่าง
→ ช่างได้จริง 89% | ค่าระบบ 8% | กองทุนชุมชน 2% | ภาษีนำส่ง 1%

กติกาปัดเศษ: ปัดที่ platform/fund/tax ก่อน (ทศนิยม 2 ตำแหน่ง)
แล้ว provider_net = gross - สามก้อนนั้น เพื่อให้ผลรวมเท่า gross เป๊ะทุกงาน
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


@dataclass(frozen=True)
class FeeConfig:
    provider_pct: Decimal = Decimal("0.90")
    platform_pct: Decimal = Decimal("0.08")
    fund_pct: Decimal = Decimal("0.02")
    tax_pct: Decimal = Decimal("0.01")  # หักจากส่วนช่าง (แบบ ก)


@dataclass(frozen=True)
class Split:
    gross: Decimal
    provider_net: Decimal
    platform_fee: Decimal
    fund_amount: Decimal
    tax_withheld: Decimal


def compute_split(gross: Decimal | int | float | str, cfg: FeeConfig = FeeConfig()) -> Split:
    gross = Decimal(str(gross)).quantize(CENT)
    if gross <= 0:
        raise ValueError("gross ต้องมากกว่า 0")
    platform_fee = (gross * cfg.platform_pct).quantize(CENT, ROUND_HALF_UP)
    fund_amount = (gross * cfg.fund_pct).quantize(CENT, ROUND_HALF_UP)
    tax_withheld = (gross * cfg.tax_pct).quantize(CENT, ROUND_HALF_UP)
    provider_net = gross - platform_fee - fund_amount - tax_withheld
    split = Split(gross, provider_net, platform_fee, fund_amount, tax_withheld)
    assert split.provider_net + split.platform_fee + split.fund_amount + split.tax_withheld == gross
    return split
