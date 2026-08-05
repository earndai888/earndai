"""จบงานในแชท LINE: การ์ดข้อเสนอ → จ่ายเงิน → ยืนยัน + ความปลอดภัย"""
import inspect
from decimal import Decimal

import pytest

from app import flex
from app.config import settings
from app.routers import jobs, webhook


# ── การ์ดข้อเสนอ ────────────────────────────────────────

def test_การ์ดข้อเสนอมีปุ่มเลือกช่างพร้อม_postback_ถูกงานถูกช่าง():
    bid = {"id": "BID", "job_id": "JOB", "price": Decimal("600"),
           "message": "พร้อมไปเสาร์นี้", "available_at": "เสาร์ 8:00"}
    prov = {"display_name": "ช่างเอก", "rating_avg": 4.8, "rating_count": 12}
    card = flex.bid_card(bid, prov, "แอร์ไม่เย็น")
    btn = card["contents"]["footer"]["contents"][0]["action"]
    assert btn["type"] == "postback"
    assert btn["data"] == "a=pick&job=JOB&bid=BID"
    assert "600" in card["altText"]


def test_ช่างใหม่ไม่มีรีวิวไม่โชว์ดาวมั่ว():
    card = flex.bid_card({"id": "b", "job_id": "j", "price": Decimal("500")},
                         {"display_name": "ช่างใหม่", "rating_avg": 0, "rating_count": 0},
                         "งาน")
    body_text = str(card["contents"]["body"])
    assert "ยังไม่มีรีวิว" in body_text


# ── การ์ดจ่ายเงิน ───────────────────────────────────────

def test_การ์ดจ่ายเงินบอกให้ส่งสลิปไม่มีปุ่มกดยืนยันลอยๆ():
    card = flex.payment_card("PAY1", Decimal("600"), "ช่างเอก", "/api/payments/PAY1/qr.png")
    # ไม่มีปุ่มกด "ฉันโอนแล้ว" แล้ว — ต้องส่งสลิปจริง
    assert "footer" not in card["contents"]
    assert "สลิป" in str(card["contents"]["body"])


def test_รูป_QR_โผล่เฉพาะเมื่อตั้งโดเมน(monkeypatch):
    # ไม่ตั้งโดเมน → ไม่มี hero (LINE โหลดรูป http localhost ไม่ได้)
    monkeypatch.setattr(settings, "public_base_url", "")
    assert "hero" not in flex.payment_card("P", 100, "ช่าง", "/x.png")["contents"]
    assert flex.public_url("/x.png") is None
    # ตั้งโดเมน → มี hero เป็น url เต็ม https
    monkeypatch.setattr(settings, "public_base_url", "https://earndai.up.railway.app/")
    card = flex.payment_card("P", 100, "ช่าง", "/api/payments/P/qr.png")
    assert card["contents"]["hero"]["url"] == "https://earndai.up.railway.app/api/payments/P/qr.png"


# ── การ์ดยืนยันงาน ──────────────────────────────────────

def test_การ์ดยืนยันงานมีปุ่ม_confirm():
    card = flex.job_done_card("JOB9", "ตัดหญ้า")
    assert card["contents"]["footer"]["contents"][0]["action"]["data"] == "a=confirm&job=JOB9"


# ── เชื่อม service ร่วมกัน (ไม่เขียน logic ซ้ำ) ──────────

def test_endpoint_กับแชทใช้_service_ตัวเดียวกัน():
    # REST endpoints เรียก do_* ตัวเดียวกับที่ webhook เรียก
    assert "do_select_bid" in inspect.getsource(jobs.select_bid)
    assert "do_confirm_payment" in inspect.getsource(jobs.confirm_payment)
    assert "do_approve_job" in inspect.getsource(jobs.approve_job)
    wh = inspect.getsource(webhook)   # ทั้งไฟล์ webhook
    for fn in ("do_select_bid", "do_confirm_payment", "do_approve_job"):
        assert fn in wh
    # ยืนยันจ่ายเงินย้ายไปตอนรับสลิป (handle_slip) แล้ว
    assert "do_confirm_payment" in inspect.getsource(webhook.handle_slip)


# ── ความปลอดภัย ─────────────────────────────────────────

def test_จ่ายเงินในแชทเช็คว่าเป็นเจ้าของงาน():
    """คนอื่นกดปุ่มจ่าย/ยืนยันของงานที่ไม่ใช่ของตัวเองไม่ได้"""
    src = inspect.getsource(webhook.handle_transaction_postback)
    # ดึง user จาก line_user_id ที่กดปุ่มจริง แล้วส่ง me.id เข้า service
    assert "WHERE line_user_id = $1" in src
    assert "me[\"id\"]" in src
    # service ตรวจ customer_id ซ้ำอีกชั้น
    assert "customer_id" in inspect.getsource(jobs.do_confirm_payment)
    assert "ไม่ใช่งานของคุณ" in inspect.getsource(jobs.do_confirm_payment)


def test_do_select_bid_ผูกกับลูกค้าเจ้าของงาน():
    src = inspect.getsource(jobs.do_select_bid)
    assert "customer_id = $2" in src


def test_เลือกช่างใหม่ยกเลิกรายการจ่ายค้างเดิม():
    """กันลูกค้าจ่ายผิดใบ ถ้าเปลี่ยนใจเลือกช่างคนใหม่"""
    assert "status='cancelled'" in inspect.getsource(jobs.do_select_bid)


def test_แจ้งช่างเมื่อลูกค้าจ่ายและเมื่อยืนยันจบงาน():
    assert "คุณได้งาน" in inspect.getsource(jobs.do_confirm_payment)
    assert "ลูกค้ายืนยันงาน" in inspect.getsource(jobs.do_approve_job)


def test_postback_ผิดพลาดตอบกลับสุภาพไม่ทำ_500():
    """service โยน HTTPException → ตอบข้อความบอกเหตุผล ไม่ให้ event พังทั้งก้อน"""
    src = inspect.getsource(webhook.handle_transaction_postback)
    assert "except HTTPException" in src
    assert "ทำรายการไม่สำเร็จ" in src
