"""ปุ่ม/คำสั่งยกเลิกรายการเดิม + ล้างบทสนทนาที่ค้าง"""
import inspect

from app import flex
from app.routers import jobs, webhook


# ── ตรวจจับคำสั่งยกเลิก ─────────────────────────────────

def test_จับคำสั่งยกเลิกและเริ่มใหม่():
    for ok in ("ยกเลิก", "ยกเลิกรายการ", "ยกเลิกรายการเดิม", "เริ่มใหม่",
               "เริ่มต้นใหม่", "ล้างแชท", "reset", "  ยกเลิก  "):
        assert webhook.is_cancel_command(ok), ok


def test_ข้อความปกติไม่โดนจับเป็นยกเลิก():
    for no in ("แอร์ไม่เย็น", "หาช่างตัดหญ้า", "ราคาเท่าไหร่", "สวัสดี", "ขอบคุณ"):
        assert not webhook.is_cancel_command(no), no


# ── ปุ่ม quick reply ────────────────────────────────────

def test_ปุ่มยกเลิกมี_postback_a_cancel():
    qr = flex.restart_quick_reply(has_pending=True)
    action = qr["items"][0]["action"]
    assert action["type"] == "postback" and action["data"] == "a=cancel"
    assert "ยกเลิก" in action["label"]


def test_ไม่มีงานค้างปุ่มเป็นเริ่มใหม่():
    assert "เริ่มใหม่" in flex.restart_quick_reply(has_pending=False)["items"][0]["action"]["label"]


def test_แนบปุ่มไม่ทับปุ่มเลือกหมวดเดิม():
    """แนบปุ่มยกเลิกทับ quick reply เลือกหมวด → ต้องยังมีปุ่มเลือกหมวดครบ"""
    base = flex.category_quick_reply()          # มีปุ่มเลือกหมวด 4 หมวด
    n = len(base["quickReply"]["items"])
    out = flex.with_quick_reply([base], flex.restart_quick_reply(True))
    items = out[-1]["quickReply"]["items"]
    assert len(items) == n + 1                  # ปุ่มเดิม + ปุ่มยกเลิก
    assert items[-1]["action"]["data"] == "a=cancel"


def test_quick_reply_ไม่เกิน13ปุ่มตามที่_LINE_รับ():
    many = {"items": [{"type": "action", "action": {"type": "postback",
            "label": str(i), "data": f"x={i}"}} for i in range(13)]}
    out = flex.with_quick_reply([{"type": "text", "text": "x", "quickReply": many}],
                                flex.restart_quick_reply(True))
    assert len(out[-1]["quickReply"]["items"]) == 13


# ── service ยกเลิกงานค้าง ───────────────────────────────

def test_ยกเลิกได้เฉพาะงานที่ยังไม่จ่าย():
    src = inspect.getsource(jobs.do_cancel_pending)
    assert "status IN ('open','bidding')" in inspect.getsource(jobs.pending_order)
    # ต้องยกเลิก payment ค้าง + reject bids + ตั้งงานเป็น cancelled
    assert "status='cancelled'" in src
    assert "status='rejected'" in src
    assert "assigned_bid_id=NULL" in src


def test_งานที่จ่ายแล้วยกเลิกเองไม่ได้():
    """assigned = จ่ายเข้าบัญชีกลางแล้ว — ไม่อยู่ในเงื่อนไข pending_order"""
    src = inspect.getsource(jobs.pending_order)
    assert "assigned" not in src.split("status IN")[1].split(")")[0]


# ── ล้างบทสนทนา ─────────────────────────────────────────

def test_ยกเลิกล้างบทสนทนาเดิมด้วย():
    from app import ai_chat
    assert "DELETE FROM chat_history" in inspect.getsource(ai_chat.clear_history)
    assert "clear_history" in inspect.getsource(webhook.handle_cancel)


def test_ยกเลิกผ่านทั้งพิมพ์และกดปุ่ม():
    # พิมพ์ "ยกเลิก" → handle_cancel
    he = inspect.getsource(webhook.handle_event)
    assert "is_cancel_command" in he and "handle_cancel" in he
    # กดปุ่ม a=cancel → handle_cancel
    tp = inspect.getsource(webhook.handle_transaction_postback)
    assert 'action == "cancel"' in tp


def test_ยกเลิกแล้วชวนเริ่มใหม่ด้วยปุ่มเลือกหมวด():
    src = inspect.getsource(webhook.handle_cancel)
    assert "category_quick_reply" in src
    assert "ยกเลิกรายการเดิม" in src
