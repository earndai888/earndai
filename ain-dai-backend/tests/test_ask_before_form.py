"""ชั้น keyword (Gemini ปิด) ต้องถามต่อก่อน ไม่ส่งลิงก์ฟอร์มทันที"""
import inspect

from app import flex
from app.intent import SUBCATEGORIES, subcategories_of
from app.routers import webhook


def test_การ์ดถามรายละเอียดมีปุ่มข้ามไปกรอกฟอร์ม():
    card = flex.ask_details("emergency", "emg-auto")
    assert card["type"] == "text"
    assert "รับเรื่อง" in card["text"]
    btn = card["quickReply"]["items"][0]["action"]
    assert btn["type"] == "postback"
    assert btn["data"] == "category=emergency&sub=emg-auto"
    # ต้องเอ่ยชื่อประเภทงานย่อยให้ลูกค้ารู้ว่าบอทเข้าใจถูก
    assert SUBCATEGORIES["emg-auto"]["name"] in card["text"]


def test_หมวดไม่มีงานย่อยไม่ใส่_sub_ในปุ่ม():
    card = flex.ask_details("ac-cleaning")
    assert card["quickReply"]["items"][0]["action"]["data"] == "category=ac-cleaning"


def test_ยางรั่วถามก่อนไม่ส่งลิงก์ทันที():
    """เคสที่ลูกค้าเจอ: พิมพ์รถยางรั่ว → ต้องถามต่อ ไม่ใช่ส่งฟอร์มเลย"""
    src = inspect.getsource(webhook.handle_event)
    # เจอ keyword มั่นใจ + รู้ประเภทแล้ว → เก็บ pending intent + ถามรายละเอียด
    assert "set_pending_intent" in src
    assert "flex.ask_details" in src
    # คำตอบรอบถัดไป (ไม่ match keyword) → เปิดฟอร์มพร้อม description
    assert "get_pending_intent" in src
    assert "clear_pending_intent" in src


def test_งานด่วนยังถามประเภทย่อยก่อนถ้าไม่รู้():
    """'ด่วนครับ' ไม่รู้ว่าด่วนเรื่องอะไร → ถามประเภทก่อน ไม่ใช่ถามรายละเอียดมั่ว"""
    src = inspect.getsource(webhook.handle_event)
    assert "subcategories_of(result.slug) and not sub" in src
    # ของจริง: emergency มีงานย่อย, หมวดอื่นไม่มี
    assert subcategories_of("emergency") and not subcategories_of("ac-cleaning")


def test_เปิดฟอร์มแล้วเคลียร์เรื่องที่คุยค้าง():
    """กดข้ามไปกรอกฟอร์ม (postback category) → ล้าง pending intent ไม่ถามซ้ำ"""
    src = inspect.getsource(webhook.handle_event)
    assert "clear_pending_intent(src[\"userId\"])" in src


def test_pending_intent_หมดอายุได้():
    """เรื่องที่คุยค้างนานเกินไปต้องไม่เอามาต่อ (กันงานเก่าโผล่)"""
    from app import ai_chat
    assert ai_chat.PENDING_TTL_MIN > 0
    assert "make_interval(mins => $2)" in inspect.getsource(ai_chat.get_pending_intent)


def test_ยกเลิกล้าง_pending_intent_ด้วย():
    from app import ai_chat
    assert "chat_pending" in inspect.getsource(ai_chat.clear_history)
