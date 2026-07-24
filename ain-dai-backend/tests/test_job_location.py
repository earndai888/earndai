"""หน้างาน: บังคับรูป ≥2, เบอร์ติดต่อ, ตำแหน่ง — และเบอร์เห็นเฉพาะแอดมิน"""
import inspect

import pytest
from pydantic import ValidationError

from app.routers import jobs
from app.routers.jobs import JobIn, map_url


def _job(**over):
    base = dict(category_slug="ac-cleaning", tambon_id=1, title="แอร์ไม่เย็น",
                contact_phone="0812345678",
                photos=["/uploads/a.jpg", "/uploads/b.jpg"])
    return base | over


def test_เบอร์ติดต่อเป็นฟิลด์บังคับ():
    assert JobIn.model_fields["contact_phone"].is_required()
    with pytest.raises(ValidationError):
        JobIn(**_job(contact_phone=None))


def test_รับพิกัดในช่วงที่ถูกต้อง():
    j = JobIn(**_job(lat=14.62, lng=104.6))
    assert j.lat == 14.62 and j.lng == 104.6


@pytest.mark.parametrize("lat,lng", [(200, 0), (0, 200), (-91, 0)])
def test_พิกัดนอกโลกถูกปฏิเสธ(lat, lng):
    with pytest.raises(ValidationError):
        JobIn(**_job(lat=lat, lng=lng))


def test_ลิงก์แผนที่ไม่ใช้_api_key():
    url = map_url(14.62, 104.6)
    assert url == "https://www.google.com/maps/search/?api=1&query=14.62,104.6"
    assert "key=" not in url
    assert map_url(None, None) is None


def test_ต้องมีรูปหน้างานอย่างน้อย2():
    assert jobs.MIN_JOB_PHOTOS == 2
    src = inspect.getsource(jobs.create_job)
    assert "MIN_JOB_PHOTOS" in src
    # กรองเฉพาะไฟล์ที่อัปโหลดในระบบ (กันยิง url ภายนอกมานับเป็นรูป)
    assert 'startswith("/uploads/")' in src


def test_เบอร์หน้างานถูก_normalize_ก่อนเก็บ():
    src = inspect.getsource(jobs.create_job)
    assert "thai_id.normalize_phone(body.contact_phone)" in src


def test_เบอร์ลูกค้าเห็นเฉพาะแอดมินไม่ใช่ช่าง():
    """job_detail: ช่างที่รับงาน (is_provider) ต้องได้ contact_phone = None"""
    src = inspect.getsource(jobs.job_detail)
    assert 'job["contact_phone"] if is_customer else None' in src


def test_ที่อยู่พิกัดเปิดเฉพาะลูกค้าและช่างที่รับงาน():
    src = inspect.getsource(jobs.job_detail)
    assert "if is_customer or is_provider:" in src
    # งานที่ยังประมูลอยู่ ช่างทั่วไปไม่เห็นบล็อก contact
    assert '"map_url": map_url(job["lat"], job["lng"])' in src


def test_ช่างที่ยังไม่ถูกเลือกไม่ได้พิกัดในรายการงานเปิด():
    """provider_jobs.open ต้องไม่ดึง lat/lng/landmark/contact_phone"""
    src = inspect.getsource(jobs.provider_jobs)
    open_block = src.split("mine = await")[0]   # เฉพาะส่วน query งานเปิด
    for leak in ("contact_phone", "j.landmark", "j.lat", "j.lng", "address_full"):
        assert leak not in open_block, f"งานเปิดรับประมูลไม่ควรมี {leak}"
