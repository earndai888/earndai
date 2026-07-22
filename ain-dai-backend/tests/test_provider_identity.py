"""ยืนยันตัวตนช่าง: เลขบัตร เบอร์โทร ชื่อจริง และหนังสือสัญญา"""
import pytest
from fastapi import HTTPException

from app import contract, thai_id
from app.routers.jobs import ProviderRegisterIn, _check_identity

# เลขบัตรสมมติที่หลักตรวจสอบถูกต้อง (คำนวณจากสูตร mod 11)
GOOD_ID = "1234567890121"


def _body(**over):
    base = dict(
        display_name="ช่างเอก แอร์เย็นฉ่ำ", full_name="สมชาย ใจดี", national_id=GOOD_ID,
        phone="0812345678", category_slugs=["ac-cleaning"], tambon_ids=[1],
        face_scan_urls=["/api/secure-file/a.jpg"], contract_signature_url="/api/secure-file/sig.png",
        contract_version=contract.CONTRACT_VERSION,
    )
    return ProviderRegisterIn(**(base | over))


# ── เลขบัตรประชาชน ──────────────────────────────────────

def test_เลขบัตรที่หลักตรวจสอบถูก_ผ่าน():
    assert thai_id.valid_national_id(GOOD_ID)
    assert thai_id.valid_national_id(thai_id.format_id(GOOD_ID))  # มีขีดก็ต้องผ่าน


@pytest.mark.parametrize("bad", [
    "1234567890123",   # หลักตรวจสอบผิด
    "123456789012",    # สั้นไป
    "12345678901234",  # ยาวไป
    "0234567890121",   # ขึ้นต้นด้วย 0
    "abcdefghijklm",   # ไม่ใช่ตัวเลข
    "",
])
def test_เลขบัตรผิดถูกปฏิเสธ(bad):
    assert not thai_id.valid_national_id(bad)


def test_จัดรูปแบบและปิดบังเลขบัตร():
    assert thai_id.format_id(GOOD_ID) == "1-2345-67890-12-1"
    masked = thai_id.mask_id(GOOD_ID)
    assert masked.endswith("-1") and GOOD_ID[:9] not in masked


# ── เบอร์โทร ────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("0812345678", "0812345678"),
    ("081-234-5678", "0812345678"),
    ("+66812345678", "0812345678"),
    ("045123456", "045123456"),       # เบอร์บ้านศรีสะเกษ
    ("12345", None),
    ("", None),
])
def test_ล้างเบอร์โทร(raw, expect):
    assert thai_id.normalize_phone(raw) == expect


# ── ชื่อจริง ────────────────────────────────────────────

def test_ต้องมีทั้งชื่อและนามสกุล():
    assert thai_id.valid_full_name("สมชาย ใจดี")
    assert not thai_id.valid_full_name("สมชาย")
    assert not thai_id.valid_full_name("")


# ── ด่านตรวจตอนสมัคร ────────────────────────────────────

def test_ข้อมูลครบถ้วนผ่านได้():
    out = _check_identity(_body(), None)
    assert out["national_id"] == GOOD_ID
    assert out["phone"] == "0812345678"
    assert out["faces"] == ["/api/secure-file/a.jpg"]


@pytest.mark.parametrize("over,expect_word", [
    ({"full_name": "สมชาย"}, "นามสกุล"),
    ({"national_id": "1234567890123"}, "เลขบัตร"),
    ({"phone": "1234567890"}, "เบอร์โทร"),   # ยาวพอแต่ไม่ขึ้นต้นด้วย 0
    ({"face_scan_urls": []}, "สแกนใบหน้า"),
    ({"contract_signature_url": None, "contract_version": None}, "หนังสือสัญญา"),
    ({"contract_version": "ของเก่า"}, "หนังสือสัญญา"),
])
def test_ข้อมูลไม่ครบถูกปฏิเสธ(over, expect_word):
    with pytest.raises(HTTPException) as e:
        _check_identity(_body(**over), None)
    assert e.value.status_code == 400
    assert expect_word in e.value.detail


@pytest.mark.parametrize("bad_url", [
    "https://evil.example/face.jpg",   # url ภายนอก
    "/uploads/face.jpg",               # โฟลเดอร์สาธารณะ — ใครมีลิงก์ก็เปิดดูได้
])
def test_ไฟล์แนบต้องอยู่ในห้องนิรภัยเท่านั้น(bad_url):
    with pytest.raises(HTTPException) as e:
        _check_identity(_body(face_scan_urls=[bad_url]), None)
    assert e.value.status_code == 400


def test_แก้โปรไฟล์ไม่ต้องสแกนหน้าเซ็นใหม่():
    เดิม = {"face_scan_urls": ["/api/secure-file/old.jpg"],
            "contract_signature_url": "/api/secure-file/oldsig.png",
            "contract_version": contract.CONTRACT_VERSION}
    out = _check_identity(_body(face_scan_urls=[], contract_signature_url=None,
                                contract_version=None), เดิม)
    assert out["faces"] == ["/api/secure-file/old.jpg"]
    assert out["signature"] == "/api/secure-file/oldsig.png"


def test_สัญญาเวอร์ชันเก่าต้องเซ็นใหม่():
    เดิม = {"face_scan_urls": ["/api/secure-file/old.jpg"],
            "contract_signature_url": "/api/secure-file/oldsig.png",
            "contract_version": "2020-v0"}
    with pytest.raises(HTTPException) as e:
        _check_identity(_body(face_scan_urls=[], contract_signature_url=None,
                              contract_version=None), เดิม)
    assert "เซ็นใหม่" in e.value.detail


# ── ตัวหนังสือสัญญา ─────────────────────────────────────

def test_สัญญามีข้อสำคัญครบ():
    text = contract.CONTRACT_TEXT
    for หัวข้อ in ("อาชีพอิสระ", "89%", "escrow", "รหัส 4 หลัก",
                   "ข้อมูลส่วนบุคคล", "ระงับบัญชี"):
        assert หัวข้อ in text
    assert contract.payload()["version"] == contract.CONTRACT_VERSION
