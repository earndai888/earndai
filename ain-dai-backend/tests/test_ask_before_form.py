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


def test_ยางรั่วเริ่มเก็บข้อมูลในแชทไม่ส่งลิงก์():
    """เคสที่ลูกค้าเจอ: พิมพ์รถยางรั่ว → เริ่มบทสนทนาในแชท ไม่ส่งลิงก์เว็บ"""
    src = inspect.getsource(webhook.handle_event)
    assert "chat_job.start" in src          # เริ่มเก็บข้อมูลในแชท
    assert "open_form_message" not in src   # ไม่ส่งลิงก์ฟอร์มเว็บอีกแล้ว


def test_งานด่วนยังถามประเภทย่อยก่อนถ้าไม่รู้():
    """'ด่วนครับ' ไม่รู้ว่าด่วนเรื่องอะไร → ถามประเภทก่อน ไม่ใช่ถามรายละเอียดมั่ว"""
    src = inspect.getsource(webhook.handle_event)
    assert "subcategories_of(result.slug) and not sub" in src
    # ของจริง: emergency มีงานย่อย, หมวดอื่นไม่มี
    assert subcategories_of("emergency") and not subcategories_of("ac-cleaning")


def test_เลือกหมวดจากปุ่มก็เริ่มเก็บข้อมูลในแชท():
    """กดปุ่มเลือกหมวด (postback category) → เริ่มบทสนทนาในแชท ไม่ส่งลิงก์"""
    src = inspect.getsource(webhook.handle_event)
    assert "chat_job.start(uid" in src
