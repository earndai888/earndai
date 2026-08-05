"""สร้างงานให้จบในแชท LINE (ไม่ต้องเปิดเว็บ)"""
import inspect

from app import chat_job


def test_parse_budget():
    assert chat_job._parse_budget("300-500") == (300, 500)
    assert chat_job._parse_budget("500") == (None, 500)
    assert chat_job._parse_budget("1,200 - 2,500") == (1200, 2500)
    assert chat_job._parse_budget("แล้วแต่ช่าง") == (None, None)
    assert chat_job._parse_budget("ไม่ระบุ") == (None, None)


def test_คำว่าพอแล้วจบการส่งรูป():
    assert "พอแล้ว" in chat_job.DONE_WORDS
    assert "ไม่มีรูป" in chat_job.DONE_WORDS


def test_สรุปงานครบทุกช่อง():
    draft = {"category_slug": "ac-cleaning", "subcategory_slug": None,
             "tambon_name": "น้ำอ้อม", "photos": ["/uploads/a.jpg"],
             "budget_min": 300, "budget_max": 500, "description": "แอร์ไม่เย็น"}
    s = chat_job._summary(draft)
    assert "ช่างแอร์" in s and "น้ำอ้อม" in s and "300-500" in s and "แอร์ไม่เย็น" in s


def test_ปุ่มยืนยันมี_postback_ถูก():
    qr = chat_job._confirm_quick_reply()
    datas = [i["action"]["data"] for i in qr["items"]]
    assert "a=jobpost" in datas and "a=jobcancel" in datas


def test_งานด่วนใช้ชื่อประเภทย่อยในบทสนทนา():
    draft = {"category_slug": "emergency", "subcategory_slug": "emg-auto",
             "photos": [], "tambon_name": "-", "description": "-"}
    from app.intent import SUBCATEGORIES
    assert SUBCATEGORIES["emg-auto"]["name"] in chat_job._summary(draft)


def test_ประกาศจากแชทเรียก_do_create_job_ผ่อนรูป():
    src = inspect.getsource(chat_job.post_job)
    assert "do_create_job" in src
    assert "min_photos=0" in src          # แชทไม่บังคับ 2 รูป
    assert '"pdpa_consent": True' in src  # กดประกาศ = ยินยอม PDPA


def test_webhook_เดินflowแชทเมื่อมีงานร่าง():
    from app.routers import webhook
    src = inspect.getsource(webhook.handle_event)
    assert "chat_job.get_draft" in src
    assert "chat_job.advance" in src
    # รับรูป/ตำแหน่งได้ ไม่ใช่เฉพาะ text
    assert 'etype == "message"' in src


def test_ปุ่มประกาศ_และยกเลิก_ในแชท():
    from app.routers import webhook
    src = inspect.getsource(webhook.handle_transaction_postback)
    assert 'action == "jobpost"' in src and 'action == "jobcancel"' in src


def test_เก็บงานร่างไม่เกิน60นาที():
    assert "60 minutes" in inspect.getsource(chat_job.get_draft)


# ── ส่งสลิปการโอน (ไม่ใช่กดยืนยันเฉยๆ) ──────────────────

def test_รับสลิปแล้วค่อยยืนยันจ่าย():
    from app.routers import webhook
    src = inspect.getsource(webhook.handle_slip)
    assert "pending_payment" in src              # ต้องมีรายการรอชำระ
    assert "get_message_content" in src          # ดาวน์โหลดรูปสลิป
    assert "slip_url=slip_url" in src            # เก็บสลิปตอนยืนยัน
    assert "do_confirm_payment" in src


def test_รูปที่ส่งมาตอนมีรายการรอชำระถือเป็นสลิป():
    from app.routers import webhook
    src = inspect.getsource(webhook.handle_event)
    assert "handle_slip" in src
    assert 'mtype == "image"' in src


def test_do_confirm_payment_เก็บ_slip_url():
    from app.routers import jobs
    src = inspect.getsource(jobs.do_confirm_payment)
    assert "slip_url" in src
    assert "slip_url=COALESCE($2, slip_url)" in src


def test_การ์ดจ่ายเงินไม่มีปุ่มกดโอนแล้ว_ต้องส่งสลิป():
    from app import flex
    card = flex.payment_card("P", 500, "ช่างเอก", "/api/payments/P/qr.png")
    assert "footer" not in card["contents"]      # ไม่มีปุ่มกดยืนยันลอยๆ
    assert "สลิป" in str(card["contents"]["body"])
