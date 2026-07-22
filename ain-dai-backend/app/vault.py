"""ห้องนิรภัยเอกสารยืนยันตัวตน — รูปบัตร เซลฟี่ ใบขับขี่ สแกนหน้า ลายเซ็น

ไฟล์กลุ่มนี้ **ห้ามเสิร์ฟผ่าน StaticFiles** เพราะใครถือลิงก์ก็เปิดดูได้
เก็บไว้นอกโฟลเดอร์สาธารณะ แล้วให้ดูผ่าน /api/secure-file/... ซึ่งตรวจสิทธิ์ก่อนทุกครั้ง
(แอดมิน หรือเจ้าตัวเท่านั้น)

รูปหน้างานกับไฟล์เสียงยังอยู่ /uploads ตามเดิม เพราะช่างและลูกค้าต้องเห็นกัน
"""
import logging
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE / "uploads"           # รูปงาน/เสียง — เปิดดูได้
PRIVATE_DIR = BASE / "private_uploads"  # เอกสารยืนยันตัวตน — ต้องผ่านการตรวจสิทธิ์
URL_PREFIX = "/api/secure-file/"

log = logging.getLogger("vault")

# คอลัมน์ในตาราง providers ที่เก็บลิงก์เอกสารลับ
SECRET_COLUMNS = ("id_card_url", "selfie_url", "license_url", "contract_signature_url")
SECRET_ARRAY_COLUMNS = ("face_scan_urls",)


def save(data: bytes, ext: str) -> str:
    """เก็บไฟล์ลับ → คืน url ที่ต้องผ่านการตรวจสิทธิ์"""
    PRIVATE_DIR.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (PRIVATE_DIR / name).write_bytes(data)
    return f"{URL_PREFIX}{name}"


def is_secure_url(url: str | None) -> bool:
    return bool(url) and url.startswith(URL_PREFIX)


def resolve(name: str) -> Path | None:
    """ชื่อไฟล์ → path จริง (กัน path traversal เช่น ../../.env)"""
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    path = (PRIVATE_DIR / name).resolve()
    if not path.is_file() or path.parent != PRIVATE_DIR.resolve():
        return None
    return path


async def sweep_orphans(pool, keep_hours: int = 24) -> int:
    """ลบไฟล์ที่ไม่มีเจ้าของออกจากห้องนิรภัย

    ถ้าคนอัปโหลดรูปบัตรแล้วสมัครไม่สำเร็จ (กรอกเลขบัตรผิด/ปิดหน้าไปเฉยๆ)
    รูปบัตรจะค้างอยู่โดยไม่ผูกกับใครเลย ไม่มีใครลบได้ — ต้องเก็บกวาดเอง
    เว้นไฟล์ใหม่ไว้ keep_hours ชั่วโมง เผื่อคนกำลังกรอกฟอร์มค้างอยู่
    """
    if not PRIVATE_DIR.is_dir():
        return 0
    cols = " UNION ALL ".join(f"SELECT {c} AS url FROM providers" for c in SECRET_COLUMNS)
    arrays = " UNION ALL ".join(
        f"SELECT unnest({c}) AS url FROM providers" for c in SECRET_ARRAY_COLUMNS)
    rows = await pool.fetch(f"SELECT DISTINCT url FROM ({cols} UNION ALL {arrays}) t "
                            "WHERE url IS NOT NULL")
    ใช้อยู่ = {r["url"].rsplit("/", 1)[-1] for r in rows}
    cutoff = time.time() - keep_hours * 3600
    removed = 0
    for path in PRIVATE_DIR.iterdir():
        if path.is_file() and path.name not in ใช้อยู่ and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("เก็บกวาดเอกสารที่ไม่มีเจ้าของออกจากห้องนิรภัย %d ไฟล์", removed)
    return removed


async def migrate_existing(pool) -> None:
    """ย้ายเอกสารลับที่เคยเก็บไว้ในโฟลเดอร์สาธารณะเข้าห้องนิรภัย แล้วแก้ลิงก์ในฐานข้อมูล

    ระบบเคยเก็บรูปบัตรไว้ที่ /uploads ซึ่งใครมีลิงก์ก็เปิดดูได้ — ต้องเก็บกวาดให้
    รันซ้ำได้ (ไฟล์ที่ย้ายแล้วจะไม่เข้าเงื่อนไข)
    """
    cols = ", ".join(SECRET_COLUMNS + SECRET_ARRAY_COLUMNS)
    rows = await pool.fetch(f"SELECT id, {cols} FROM providers")
    PRIVATE_DIR.mkdir(exist_ok=True)
    moved = 0

    def relocate(url: str | None) -> str | None:
        """/uploads/x.jpg → /api/secure-file/x.jpg (ย้ายไฟล์จริงตามไปด้วย)"""
        nonlocal moved
        if not url or not url.startswith("/uploads/"):
            return url
        name = url.rsplit("/", 1)[-1]
        src, dst = PUBLIC_DIR / name, PRIVATE_DIR / name
        if src.is_file() and not dst.exists():
            src.rename(dst)
            moved += 1
        return f"{URL_PREFIX}{name}"

    for row in rows:
        updates, args = [], []
        for col in SECRET_COLUMNS:
            new = relocate(row[col])
            if new != row[col]:
                args.append(new)
                updates.append(f"{col} = ${len(args) + 1}")
        for col in SECRET_ARRAY_COLUMNS:
            old = list(row[col] or [])
            new_list = [relocate(u) for u in old]
            if new_list != old:
                args.append(new_list)
                updates.append(f"{col} = ${len(args) + 1}")
        if updates:
            await pool.execute(
                f"UPDATE providers SET {', '.join(updates)} WHERE id = $1", row["id"], *args)

    if moved:
        log.warning("ย้ายเอกสารยืนยันตัวตน %d ไฟล์เข้าห้องนิรภัยแล้ว "
                    "(เดิมเปิดดูได้จากลิงก์สาธารณะ)", moved)
