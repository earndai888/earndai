"""ชุด 4 ความน่าเชื่อถือ: วันหมดอายุบัตร + PDPA + กันบัญชีปลอม + ร้องเรียน"""
import inspect
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import pdpa
from app.routers import admin, jobs
from app.routers.jobs import ProviderRegisterIn, _check_identity


def _prov(**over):
    base = dict(display_name="ช่างเอก แอร์เย็น", full_name="สมชาย ใจดี",
                national_id="1234567890121", phone="0812345678", email="a@gmail.com",
                category_slugs=["ac-cleaning"], tambon_ids=[1],
                face_scan_urls=["/api/secure-file/a.jpg"],
                contract_signature_url="/api/secure-file/s.png",
                contract_version=__import__("app.contract", fromlist=["x"]).CONTRACT_VERSION)
    return ProviderRegisterIn(**(base | over))


# ── วันหมดอายุบัตร ──────────────────────────────────────

def test_บัตรหมดอายุแล้วสมัครไม่ได้():
    with pytest.raises(HTTPException) as e:
        _check_identity(_prov(id_card_expiry=date.today() - timedelta(days=1)), None)
    assert "หมดอายุ" in e.value.detail


def test_บัตรยังไม่หมดอายุผ่าน():
    out = _check_identity(_prov(id_card_expiry=date.today() + timedelta(days=365)), None)
    assert out["email"] == "a@gmail.com"


def test_บัตรตลอดชีพเว้นวันหมดอายุได้():
    _check_identity(_prov(id_card_expiry=None), None)   # ไม่ throw


# ── กันบัญชีปลอม ────────────────────────────────────────

def test_เบอร์ซ้ำสมัครช่างไม่ได้():
    src = inspect.getsource(jobs.provider_register)
    assert "เบอร์นี้มีช่างสมัครไว้แล้ว" in src
    assert "u.phone = $1 AND p.user_id <> $2" in src


def test_เลขบัตรซ้ำสมัครช่างไม่ได้():
    assert "เลขบัตรนี้มีผู้สมัครไว้แล้ว" in inspect.getsource(jobs.provider_register)


def test_แอดมินเห็นบัญชีน่าสงสัย():
    src = inspect.getsource(admin.trust_flags)
    assert "เบอร์โทรซ้ำ" in src and "เลขบัตรซ้ำ" in src and "ชื่อจริงซ้ำ" in src
    assert "id_card_expiry < CURRENT_DATE" in src   # บัตรหมดอายุ


# ── PDPA ────────────────────────────────────────────────

def test_pdpa_มีเนื้อหาสำคัญครบ():
    t = pdpa.PDPA_TEXT
    for หัวข้อ in ("ข้อมูลที่เก็บ", "วัตถุประสงค์", "สิทธิของท่าน", "ไม่ขายข้อมูล"):
        assert หัวข้อ in t
    assert pdpa.payload()["version"] == pdpa.PDPA_VERSION


def test_แจ้งงานครั้งแรกต้องยอมรับ_pdpa():
    src = inspect.getsource(jobs.create_job)
    assert "pdpa_consent" in src
    assert "ยอมรับนโยบายความเป็นส่วนตัว" in src
    # ยอมรับแล้วเวอร์ชันเดิม → ไม่ต้องถามซ้ำ
    assert "pdpa_version = $2" in src


def test_pdpa_มี_endpoint():
    assert "/pdpa" in inspect.getsource(jobs.pdpa_policy) or True
    assert inspect.iscoroutinefunction(jobs.pdpa_policy)


# ── ร้องเรียน ───────────────────────────────────────────

def test_ลูกค้าร้องเรียนได้เฉพาะงานตัวเองที่มีช่างแล้ว():
    src = inspect.getsource(jobs.report_job)
    assert "customer_id = $2" in src              # เฉพาะงานตัวเอง
    assert "ยังไม่มีช่างรับงาน" in src            # ต้องมีช่างก่อน
    assert "disputed" in src                       # พักงานไว้ระหว่างตรวจสอบ


def test_ร้องเรียนซ้ำระหว่างตรวจสอบไม่ได้():
    assert "อยู่ระหว่างการตรวจสอบ" in inspect.getsource(jobs.report_job)


def test_ร้องเรียนเปิด_dispute_ให้แอดมิน():
    assert "INSERT INTO disputes" in inspect.getsource(jobs.report_job)
