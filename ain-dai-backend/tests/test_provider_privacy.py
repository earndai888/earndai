"""ลูกค้าต้องเห็นแค่ชื่อกับรีวิว — ห้ามเห็นบัญชีเงิน เบอร์ หรือข้อมูลบัตร

เงินลูกค้าเข้าบัญชีกลางของแพลตฟอร์ม ไม่ได้โอนให้ช่างตรง ถ้าเลขพร้อมเพย์หรือเบอร์
หลุดไปถึงลูกค้าเมื่อไหร่ ก็นัดกันเองนอกระบบได้ทันที = ระบบคุ้มครองใครไม่ได้เลย
"""
import inspect
import re

import pytest

from app import contact_guard
from app.routers import jobs

# ฟิลด์ที่ห้ามโผล่ใน endpoint ฝั่งลูกค้าเด็ดขาด
SECRET_FIELDS = ["promptpay_id", "national_id", "full_name",
                 "face_scan_urls", "contract_signature_url", "phone"]

# endpoint ที่ลูกค้าเรียกได้ (ไม่ใช่ /me ของช่างเอง และไม่ใช่ฝั่งแอดมิน)
CUSTOMER_ENDPOINTS = [jobs.list_bids, jobs.top_providers, jobs.job_detail, jobs.my_jobs]


@pytest.mark.parametrize("fn", CUSTOMER_ENDPOINTS, ids=lambda f: f.__name__)
def test_endpoint_ลูกค้าไม่ดึงข้อมูลลับของช่าง(fn):
    src = inspect.getsource(fn)
    # ตัด comment ทิ้งก่อน เทียบเฉพาะโค้ดจริง
    code = "\n".join(line.split("--")[0].split("#")[0] for line in src.splitlines())
    for field in SECRET_FIELDS:
        assert field not in code, f"{fn.__name__} ดึง {field} ซึ่งลูกค้าไม่ควรเห็น"


def test_รายการข้อเสนอส่งกลับเฉพาะชื่อกับรีวิว():
    src = inspect.getsource(jobs.list_bids)
    for ต้องมี in ("display_name", "rating_avg", "rating_count", "jobs_done"):
        assert ต้องมี in src
    assert "u.phone" not in src and "p.promptpay_id" not in src


def test_ชื่อช่างที่ลูกค้าเห็นมาจาก_display_name_ไม่ใช่ชื่อจริง():
    """ชื่อจริงตามบัตรใช้แค่ออกใบ 50 ทวิ ไม่ใช่ชื่อที่โชว์ลูกค้า"""
    src = inspect.getsource(jobs.list_bids) + inspect.getsource(jobs.top_providers)
    assert "full_name" not in src


# ── กันทิ้งเบอร์ไว้ในข้อความที่ลูกค้าอ่าน ──────────────────

@pytest.mark.parametrize("text,kind", [
    ("ช่างเอก โทร 0812345678", "เบอร์โทร"),
    ("ติดต่อ 081-234-5678 ได้เลย", "เบอร์โทร"),
    ("โทร 081 234 5678", "เบอร์โทร"),
    ("แอดไลน์ @changek123", "ไอดีไลน์"),
    ("line id: chang_ek99", "ไอดีไลน์"),
    ("ไลน์ chang.ek", "ไอดีไลน์"),
    ("โทร ๐๘๑๒๓๔๕๖๗๘", "เบอร์โทร"),        # เขียนด้วยเลขไทย
    ("เบอร์ +66812345678", "เบอร์โทร"),
    ("045 123456 ที่ร้าน", "เบอร์โทร"),      # เบอร์บ้าน 9 หลัก
])
def test_จับช่องทางติดต่อที่แอบใส่มา(text, kind):
    assert contact_guard.find_contact_leak(text) == kind


@pytest.mark.parametrize("text", [
    "ช่างเอก รับเหมาไฟฟ้า",
    "ประสบการณ์ 10 ปี เครื่องมือครบ เก็บงานเรียบร้อย",
    "ล้างแอร์ 9000-24000 BTU ทุกยี่ห้อ",
    "รับงานตั้งแต่ 08.00-17.00 น.",
    "คิดราคา 500 บาทต่อจุด",
    "ล้างแอร์ 12000 BTU 500 บาท ติดตั้ง 2500 บาท",
    "รับงาน 24 ชม. ทุกวัน",
    None,
    "",
])
def test_ข้อความปกติไม่ถูกบล็อก(text):
    assert contact_guard.find_contact_leak(text) is None


def test_ข้อความเตือนบอกเหตุผลไม่ใช่แค่ห้าม():
    msg = contact_guard.message("เบอร์โทร", "คำแนะนำตัว")
    assert "เบอร์โทร" in msg and "คำแนะนำตัว" in msg
    assert "คุ้มครอง" in msg   # บอกด้วยว่าห้ามเพราะอะไร


def test_ด่านกันเบอร์ถูกใช้จริงทั้งตอนสมัครและตอนเสนอราคา():
    assert "contact_guard" in inspect.getsource(jobs._check_identity)
    assert "contact_guard" in inspect.getsource(jobs.create_bid)


def test_หน้าสมัครช่างบอกชัดว่าอะไรลูกค้าเห็นไม่เห็น():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "static" / "provider.html").read_text("utf-8")
    # พร้อมเพย์ต้องอยู่ใต้หัวข้อที่ติดป้าย "ลูกค้าไม่เห็น"
    หัวข้อพร้อมเพย์ = re.search(r"<h2>[^<]*บัญชีรับเงิน[^<]*<span class=\"lock\">[^<]*</span></h2>", html)
    assert หัวข้อพร้อมเพย์, "หัวข้อบัญชีรับเงินต้องติดป้ายว่าลูกค้าไม่เห็น"
    assert html.index(str(หัวข้อพร้อมเพย์.group())) < html.index('id="rpromptpay"')
    # และต้องมีตัวอย่างให้ช่างเห็นว่าลูกค้าเห็นแค่ไหน
    assert 'id="publicpreview"' in html
