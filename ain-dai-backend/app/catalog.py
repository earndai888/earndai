"""ซิงก์กลุ่มงานย่อยจาก intent.SUBCATEGORIES ลงฐานข้อมูล

ทำตอน startup ทุกครั้ง (รันซ้ำได้) — แก้ชื่อ/ตัวอย่างงานที่ intent.py ที่เดียว
แล้ว deploy ใหม่ ฐานข้อมูลจะตามให้เอง ไม่ต้องรัน SQL มือ
"""
import logging

from . import db
from .intent import CATEGORY_NAMES, SUBCATEGORIES

log = logging.getLogger("catalog")


async def ensure_subcategories() -> None:
    pool = db.get_pool()
    # ชื่อหมวดใน intent.py คือต้นทาง — เผื่อเปลี่ยนชื่อ (เช่น งานฉุกเฉิน → งานด่วน 24 ชม.)
    for slug, name in CATEGORY_NAMES.items():
        await pool.execute(
            "UPDATE service_categories SET name_th = $2 WHERE slug = $1 AND name_th <> $2",
            slug, name)
    await pool.execute(
        """CREATE TABLE IF NOT EXISTS service_subcategories (
             id          serial PRIMARY KEY,
             category_id int NOT NULL REFERENCES service_categories(id),
             slug        text UNIQUE NOT NULL,
             name_th     text NOT NULL,
             icon        text,
             examples    text[] NOT NULL DEFAULT '{}',
             sort        int NOT NULL DEFAULT 0,
             active      boolean NOT NULL DEFAULT true
           )"""
    )
    # งานอ้างกลุ่มย่อยได้ (ไม่บังคับ — หมวดอื่นยังไม่มีกลุ่มย่อย)
    await pool.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS subcategory_id int "
        "REFERENCES service_subcategories(id)")
    # ช่างเลือกได้ว่ารับงานด่วนแบบไหนบ้าง (ว่าง = รับทุกแบบในหมวดที่สมัคร)
    await pool.execute(
        "ALTER TABLE providers ADD COLUMN IF NOT EXISTS subcategories int[] "
        "NOT NULL DEFAULT '{}'")

    for i, (slug, sub) in enumerate(SUBCATEGORIES.items()):
        cat_id = await pool.fetchval(
            "SELECT id FROM service_categories WHERE slug = $1", sub["category"])
        if not cat_id:
            log.warning("ข้ามกลุ่มย่อย %s — ยังไม่มีหมวด %s ในฐานข้อมูล", slug, sub["category"])
            continue
        await pool.execute(
            """INSERT INTO service_subcategories (category_id, slug, name_th, icon, examples, sort, active)
               VALUES ($1,$2,$3,$4,$5,$6,true)
               ON CONFLICT (slug) DO UPDATE
                 SET category_id = $1, name_th = $3, icon = $4,
                     examples = $5, sort = $6, active = true""",
            cat_id, slug, sub["name"], sub["icon"], sub["examples"], i)

    # กลุ่มย่อยที่ถูกลบออกจากโค้ดแล้ว → ปิดไว้ (ไม่ลบ เพราะงานเก่าอ้างอยู่)
    await pool.execute(
        "UPDATE service_subcategories SET active = false WHERE slug <> ALL($1::text[])",
        list(SUBCATEGORIES))


async def ensure_provider_kyc() -> None:
    """คอลัมน์ยืนยันตัวตนช่าง: ชื่อจริง เลขบัตร สแกนหน้า ลายเซ็นสัญญา"""
    pool = db.get_pool()
    await pool.execute(
        """ALTER TABLE providers
             ADD COLUMN IF NOT EXISTS full_name              text,
             ADD COLUMN IF NOT EXISTS national_id            text,
             ADD COLUMN IF NOT EXISTS address                text,
             ADD COLUMN IF NOT EXISTS face_scan_urls         text[] NOT NULL DEFAULT '{}',
             ADD COLUMN IF NOT EXISTS contract_signature_url text,
             ADD COLUMN IF NOT EXISTS contract_version       text,
             ADD COLUMN IF NOT EXISTS contract_signed_at     timestamptz"""
    )
