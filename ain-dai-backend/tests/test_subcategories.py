"""งานด่วน 24 ชม. แยก 4 กลุ่มย่อย — ต้องจับกลุ่มถูก ไม่งั้นงานไปไม่ถึงช่างที่ทำได้"""
import pytest

from app import flex
from app.intent import CATEGORY_NAMES, SUBCATEGORIES, classify, classify_sub, subcategories_of


def test_มีครบ4กลุ่มย่อยและอยู่ในหมวดงานด่วน():
    subs = subcategories_of("emergency")
    assert set(subs) == {"emg-agri", "emg-auto", "emg-lock", "emg-home"}
    assert len(SUBCATEGORIES) == 4          # ตอนนี้มีแค่หมวดงานด่วนที่แตกกลุ่มย่อย
    for s in subs.values():
        assert s["name"] and s["icon"] and s["examples"]


def test_หมวดอื่นไม่มีกลุ่มย่อย():
    for slug in CATEGORY_NAMES:
        if slug != "emergency":
            assert subcategories_of(slug) == {}


@pytest.mark.parametrize("text,expected", [
    # 1) เครื่องจักรการเกษตร
    ("รถไถดับกลางนา สตาร์ทไม่ติด", "emg-agri"),
    ("รถเกี่ยวข้าวสายพานขาด", "emg-agri"),
    ("เครื่องสูบน้ำเข้านาเสีย", "emg-agri"),
    ("ปั๊มน้ำบาดาลไม่ทำงาน", "emg-agri"),
    ("โดรนเกษตรหัวฉีดตัน", "emg-agri"),
    ("เลื่อยยนต์เสีย", "emg-agri"),
    # 2) กู้ภัยยานพาหนะ
    ("ยางแตกกลางทาง หาคนปะยาง", "emg-auto"),
    ("รถสตาร์ทไม่ติด แบตหมด", "emg-auto"),
    ("น้ำมันหมดกลางทาง", "emg-auto"),
    # 3) กุญแจ
    ("ลืมกุญแจไว้ในรถ", "emg-lock"),
    ("เข้าบ้านไม่ได้ กุญแจหัก", "emg-lock"),
    ("อยากเปลี่ยนลูกบิดด่วน", "emg-lock"),
    # 4) สาธารณูปโภคในบ้าน
    ("ไฟดับทั้งบ้าน เบรกเกอร์ตัด", "emg-home"),
    ("ท่อประปาแตก น้ำทะลัก", "emg-home"),
    ("ส้วมตัน ใช้ห้องน้ำไม่ได้", "emg-home"),
])
def test_จับกลุ่มย่อยถูก(text, expected):
    assert classify_sub(text) == expected


@pytest.mark.parametrize("text", [
    "รถไถดับกลางนา", "ยางแตกกลางทาง", "ลืมกุญแจไว้ในรถ", "ส้วมตัน", "ไฟดับทั้งบ้าน",
])
def test_คำของกลุ่มย่อยพาเข้าหมวดงานด่วนได้เอง(text):
    """ก่อนหน้านี้ "รถไถเสีย" จับหมวดไม่ได้เลย เพราะไม่มีคำว่า ด่วน/ฉุกเฉิน"""
    r = classify(text)
    assert r.slug == "emergency" and r.confident


def test_ไม่ปนกับหมวดอื่น():
    assert classify("จ้างตัดหญ้าหน้าบ้าน").slug == "gardening"
    assert classify("ล้างแอร์").slug == "ac-cleaning"
    assert classify_sub("จ้างตัดหญ้าหน้าบ้าน") is None


def test_classify_sub_จำกัดตามหมวดได้():
    assert classify_sub("ไฟดับทั้งบ้าน", "gardening") is None
    assert classify_sub("ไฟดับทั้งบ้าน", "emergency") == "emg-home"


def test_ถามต่อเมื่อยังไม่รู้ว่าด่วนเรื่องอะไร():
    q = flex.subcategory_quick_reply("emergency")
    assert q and len(q["quickReply"]["items"]) == 4
    for item in q["quickReply"]["items"]:
        # LINE จำกัด label ของ quick reply ไว้ 20 ตัวอักษร
        assert len(item["action"]["label"]) <= 20
        assert item["action"]["data"].startswith("category=emergency&sub=emg-")
    assert flex.subcategory_quick_reply("ac-cleaning") is None


def test_ปุ่มเปิดฟอร์มพากลุ่มย่อยไปหน้าเว็บด้วย():
    msg = flex.open_form_message("emergency", subcategory_slug="emg-lock")
    uri = msg["contents"]["footer"]["contents"][0]["action"]["uri"]
    assert "category=emergency" in uri and "sub=emg-lock" in uri
    assert SUBCATEGORIES["emg-lock"]["name"] in msg["contents"]["body"]["contents"][0]["text"]


def test_label_ปุ่มไม่เกินที่LINEรับได้():
    """ชื่อหมวดยาว (งานด่วน 24 ชม.) เคยทำให้ label เกิน 20 ตัว → LINE ตีกลับ"""
    for slug in CATEGORY_NAMES:
        msg = flex.open_form_message(slug)
        assert len(msg["contents"]["footer"]["contents"][0]["action"]["label"]) <= 20


def test_การ์ดงานบอกว่าด่วนแบบไหน():
    job = {"id": "x", "title": "รถไถดับกลางนา", "description": "", "budget_min": None,
           "budget_max": None, "preferred_time": "วันนี้"}
    card = flex.job_card(job, "งานด่วน 24 ชม.", "น้ำอ้อม",
                         sub_name=SUBCATEGORIES["emg-agri"]["name"])
    head = card["contents"]["body"]["contents"][0]["text"]
    assert "งานด่วน 24 ชม." in head and SUBCATEGORIES["emg-agri"]["name"] in head
