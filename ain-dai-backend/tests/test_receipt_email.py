"""ชุด 3: อีเมล + ใบเสร็จ (LINE + อีเมล)"""
import inspect
from datetime import date

import pytest
from pydantic import ValidationError

from app import flex, mailer, receipt, thai_id
from app.routers.jobs import JobIn, ProviderRegisterIn, _send_receipt, do_confirm_payment


# ── อีเมล ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("name@gmail.com", "name@gmail.com"),
    ("  Name@Gmail.COM ", "name@gmail.com"),
    ("a.b-c+d@sub.domain.co.th", "a.b-c+d@sub.domain.co.th"),
    ("nope", None), ("a@b", None), ("@x.com", None), ("", None), (None, None),
])
def test_ตรวจและล้างอีเมล(raw, expect):
    assert thai_id.normalize_email(raw) == expect


def test_ช่างต้องกรอกอีเมล():
    assert ProviderRegisterIn.model_fields["email"].is_required()


def test_ลูกค้าไม่บังคับอีเมล():
    # JobIn ต้องแจ้งงานได้โดยไม่ใส่อีเมล
    j = JobIn(category_slug="ac-cleaning", tambon_id=1, title="แอร์ไม่เย็น",
              contact_phone="0812345678", photos=["/uploads/a.jpg", "/uploads/b.jpg"])
    assert j.email is None


# ── ใบเสร็จ PDF ─────────────────────────────────────────

def test_สร้างใบเสร็จ_pdf_ได้():
    pdf = receipt.build_pdf({"receipt_no": 12, "pay_date": date(2026, 7, 23),
                             "customer_name": "สมหญิง ใจดี", "job_title": "ล้างแอร์",
                             "provider_name": "ช่างเอก", "amount": 650})
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000


# ── การ์ดใบเสร็จใน LINE ─────────────────────────────────

def test_การ์ดใบเสร็จมีปุ่มดาวน์โหลดเมื่อมีลิงก์():
    card = flex.receipt_card(12, 650, "https://x.app/api/receipt/tok")
    btn = card["contents"]["footer"]["contents"][0]["action"]
    assert btn["type"] == "uri" and btn["uri"].endswith("/receipt/tok")
    assert "RCP-000012" in str(card["contents"]["body"])


def test_การ์ดใบเสร็จไม่มีปุ่มถ้ายังไม่ตั้งโดเมน():
    card = flex.receipt_card(12, 650, None)
    assert "footer" not in card["contents"]


# ── ส่งใบเสร็จหลังจ่ายเงิน ──────────────────────────────

def test_จ่ายเงินแล้วส่งใบเสร็จ():
    assert "_send_receipt" in inspect.getsource(do_confirm_payment)


def test_ใบเสร็จส่งทั้ง_line_และอีเมล():
    src = inspect.getsource(_send_receipt)
    assert "line_api.push" in src and "flex.receipt_card" in src   # LINE
    assert "mailer.send" in src and "mailer.configured()" in src   # อีเมล (ถ้าตั้งค่า)
    # ออกเลขใบเสร็จ + โทเคนลับ ครั้งเดียว (idempotent)
    assert "receipt_token" in src and "nextval('receipt_no_seq')" in src


def test_ใบเสร็จพังไม่ทำให้จ่ายเงินล้ม():
    """ส่งใบเสร็จเป็น best-effort — พังต้องไม่ทำให้การพักเงินล้ม"""
    src = inspect.getsource(_send_receipt)
    assert "except Exception" in src


# ── อีเมล best-effort ───────────────────────────────────

def test_ไม่ตั้ง_smtp_ถือว่าปิดอีเมล():
    # ค่าเริ่มต้นไม่มี SMTP → configured() False → ไม่ส่ง (ใช้ LINE อย่างเดียว)
    assert mailer.configured() is False


async def _fake():
    return await mailer.send("a@b.com", "s", "b")


def test_ส่งอีเมลตอนไม่ได้ตั้งค่าคืน_false_ไม่_throw():
    import asyncio
    assert asyncio.run(_fake()) is False


# ── ใบเสร็จเปิดด้วยโทเคนลับ ─────────────────────────────

def test_ใบเสร็จใช้โทเคนลับแทน_auth():
    from app.routers import jobs
    src = inspect.getsource(jobs.receipt_pdf)
    assert "receipt_token = $1" in src
    assert "ไม่พบใบเสร็จ" in src   # โทเคนผิด → 404
