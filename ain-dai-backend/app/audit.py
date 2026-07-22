"""บันทึกทุกการแก้ไข/ลบของแอดมิน

แอดมินแก้ข้อมูลคนอื่นได้ ก็ต้องตรวจสอบย้อนหลังได้ว่าใครแก้อะไรไปเมื่อไหร่
โดยเฉพาะข้อมูลบัตรประชาชนกับเงิน — ถ้ามีเรื่องขึ้นมาจะได้ชี้แจงได้
"""
import json
import logging

from . import db

log = logging.getLogger("audit")

# ฟิลด์ที่ห้ามบันทึกค่าเต็มลงล็อก (บันทึกแค่ว่ามีการเปลี่ยน)
MASKED_FIELDS = {"national_id"}


async def ensure_table() -> None:
    pool = db.get_pool()
    await pool.execute(
        """CREATE TABLE IF NOT EXISTS admin_audit (
             id          bigserial PRIMARY KEY,
             at          timestamptz NOT NULL DEFAULT now(),
             action      text NOT NULL,
             target_type text NOT NULL,
             target_id   text,
             target_name text,
             detail      jsonb NOT NULL DEFAULT '{}'
           )"""
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_at ON admin_audit (at DESC)")


def _mask(detail: dict) -> dict:
    out = {}
    for k, v in detail.items():
        if k in MASKED_FIELDS and v:
            out[k] = "(เปลี่ยนแล้ว — ไม่บันทึกเลขลงล็อก)"
        else:
            out[k] = v
    return out


async def record(action: str, target_type: str, target_id: str | None,
                 target_name: str | None = None, **detail) -> None:
    """บันทึกหนึ่งเหตุการณ์ — พังก็ไม่ให้กระทบงานหลัก แต่ต้องเห็นใน log"""
    try:
        await db.get_pool().execute(
            """INSERT INTO admin_audit (action, target_type, target_id, target_name, detail)
               VALUES ($1,$2,$3,$4,$5::jsonb)""",
            action, target_type, str(target_id) if target_id else None, target_name,
            json.dumps(_mask(detail), ensure_ascii=False, default=str))
    except Exception:
        log.exception("บันทึก audit ไม่สำเร็จ: %s %s %s", action, target_type, target_id)
