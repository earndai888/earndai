"""ห้องนิรภัยเอกสารบัตร ปชช. + สิทธิ์แก้/ลบข้อมูลของแอดมิน"""
import inspect

import pytest

from app import vault
from app.main import app
from app.routers import admin, jobs


# ── ห้องนิรภัย ──────────────────────────────────────────

def test_เอกสารลับไม่ได้อยู่ในโฟลเดอร์สาธารณะ():
    assert vault.PRIVATE_DIR != vault.PUBLIC_DIR
    assert vault.PRIVATE_DIR.name not in ("uploads", "static")


def test_uploads_สาธารณะถูก_mount_แต่ห้องนิรภัยไม่ถูก_mount():
    """StaticFiles = ใครมีลิงก์ก็เปิดได้ ห้ามเอาเอกสารบัตรไปไว้ตรงนั้น"""
    mounted = [r.path for r in app.routes if r.__class__.__name__ == "Mount"]
    assert "/uploads" in mounted
    assert not any("private" in m for m in mounted)


@pytest.mark.parametrize("bad", [
    "../.env", "../../app/config.py", "..\\..\\.env", "/etc/passwd", ".hidden",
    "sub/dir.jpg",
])
def test_กัน_path_traversal(bad):
    assert vault.resolve(bad) is None


def test_ไฟล์ที่ไม่มีอยู่จริงคืน_None():
    assert vault.resolve("ไม่มีไฟล์นี้จริงๆ.jpg") is None


def test_แยกแยะ_url_ห้องนิรภัย():
    assert vault.is_secure_url("/api/secure-file/abc.jpg")
    assert not vault.is_secure_url("/uploads/abc.jpg")
    assert not vault.is_secure_url("https://evil.example/x.jpg")
    assert not vault.is_secure_url(None)


def test_เปิดไฟล์ลับต้องผ่านการตรวจสิทธิ์():
    """endpoint ทั้งสองทางต้องมีด่าน — ฝั่งช่างเช็คว่าเป็นเจ้าของ ฝั่งแอดมินเช็ค token"""
    ฝั่งช่าง = inspect.getsource(jobs.secure_file)
    assert "current_user" in inspect.signature(jobs.secure_file).parameters or \
           "user" in inspect.signature(jobs.secure_file).parameters
    assert "ไม่มีสิทธิ์" in ฝั่งช่าง          # เจ้าของเท่านั้น
    assert "Admin" in inspect.getsource(admin.admin_secure_file)


def test_ตอนสมัครบังคับว่าเอกสารต้องอยู่ในห้องนิรภัย():
    src = inspect.getsource(jobs._check_identity)
    assert "vault.is_secure_url" in src
    assert "id_card_url" in src and "face_scan_urls" in src


def test_เก็บกวาดไฟล์ไร้เจ้าของแต่เว้นไฟล์ที่เพิ่งอัปโหลด():
    """รูปบัตรของคนที่สมัครไม่สำเร็จจะค้างอยู่โดยไม่มีใครลบได้ — ต้องกวาดเอง
    แต่ห้ามลบไฟล์ที่เพิ่งอัปโหลด เพราะอาจมีคนกำลังกรอกฟอร์มค้างอยู่"""
    src = inspect.getsource(vault.sweep_orphans)
    assert "keep_hours" in src and "st_mtime" in src
    assert "unlink" in src
    # ต้องถูกเรียกใช้จริง ไม่ใช่เขียนทิ้งไว้เฉยๆ
    from app import main
    assert "sweep_orphans" in inspect.getsource(main.auto_release_loop)


def test_รายการคอลัมน์ลับครบตามที่เก็บจริง():
    """เพิ่มเอกสารลับใหม่แล้วลืมใส่ในรายการ = ลบช่างแล้วไฟล์ค้างในเครื่อง"""
    ทั้งหมด = set(vault.SECRET_COLUMNS) | set(vault.SECRET_ARRAY_COLUMNS)
    assert ทั้งหมด == {"id_card_url", "selfie_url", "license_url",
                       "contract_signature_url", "face_scan_urls"}


# ── สิทธิ์แก้/ลบของแอดมิน ───────────────────────────────

def test_แก้ข้อมูลช่างต้องบอกเหตุผลเสมอ():
    fields = admin.ProviderEditIn.model_fields
    assert fields["reason"].is_required()


def test_ฟิลด์ที่แก้ไม่ได้ไม่อยู่ในฟอร์มแก้ไข():
    """คะแนนรีวิว/จำนวนงาน มาจากงานจริง — แก้มือได้เมื่อไหร่ รีวิวก็เชื่อไม่ได้
    ส่วนสแกนหน้า/ลายเซ็น เป็นหลักฐานที่ช่างทำเอง แอดมินทำแทนไม่ได้"""
    for ห้ามมี in ("rating_avg", "rating_count", "jobs_done",
                   "face_scan_urls", "contract_signature_url"):
        assert ห้ามมี not in admin.ProviderEditIn.model_fields


def test_แก้ข้อมูลผ่านด่านเดียวกับตอนช่างกรอกเอง():
    src = inspect.getsource(admin.edit_provider)
    assert "contact_guard" in src            # ห้ามใส่เบอร์ในชื่อร้าน/แนะนำตัว
    assert "valid_national_id" in src        # เลขบัตรต้องถูกหลักตรวจสอบ
    assert "normalize_phone" in src
    assert "มีช่างคนอื่นใช้อยู่แล้ว" in src   # เลขบัตรซ้ำคนอื่นไม่ได้


def test_ลบช่างต้องเคลียร์งานและเงินก่อน():
    src = inspect.getsource(admin.delete_provider)
    assert "มีงานค้างอยู่" in src
    assert "ยังค้างโอนเงิน" in src


def test_ลบช่างแล้วต้องลบไฟล์ในห้องนิรภัยจริง():
    src = inspect.getsource(admin.delete_provider)
    assert "unlink" in src, "ตัดลิงก์ในฐานข้อมูลอย่างเดียว ไฟล์บัตรยังอยู่ในเครื่อง"
    assert "national_id = NULL" in src


def test_ลบช่างไม่ลบประวัติเงิน():
    """settlements/payments ลบไม่ได้ ต้องใช้ยืนยันภาษีย้อนหลัง"""
    src = inspect.getsource(admin.delete_provider)
    assert "DELETE FROM settlements" not in src
    assert "DELETE FROM payments" not in src
    assert "DELETE FROM jobs" not in src


def test_ทุกการแก้และลบถูกบันทึกลง_audit():
    for fn in (admin.edit_provider, admin.delete_provider):
        assert "audit.record" in inspect.getsource(fn), f"{fn.__name__} ไม่ได้บันทึก audit"


def test_audit_ไม่บันทึกเลขบัตรเต็มลงล็อก():
    from app import audit
    assert "national_id" in audit.MASKED_FIELDS
    out = audit._mask({"national_id": "1234567890121", "reason": "แก้ตามบัตร"})
    assert "1234567890121" not in str(out)
    assert out["reason"] == "แก้ตามบัตร"
