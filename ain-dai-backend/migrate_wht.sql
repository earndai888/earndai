-- ═══════════════════════════════════════════════════════
-- ใบ 50 ทวิ (หนังสือรับรองหักภาษี ณ ที่จ่าย) + ลิงก์กลุ่ม OpenChat
-- รันซ้ำได้ (idempotent)
-- ═══════════════════════════════════════════════════════

-- ข้อมูลผู้ถูกหักภาษี (แอดมินกรอกจากบัตร ปชช. ตอนอนุมัติ) — ใช้ออกใบ 50 ทวิ
ALTER TABLE providers
  ADD COLUMN IF NOT EXISTS national_id text,
  ADD COLUMN IF NOT EXISTS address     text;

-- เลขที่ใบ 50 ทวิ ต่อรายการ settlement (เดินเลขอัตโนมัติ)
ALTER TABLE settlements
  ADD COLUMN IF NOT EXISTS wht_no int;

CREATE SEQUENCE IF NOT EXISTS wht_no_seq START 1;

-- ลิงก์กลุ่ม OpenChat ต่อหมวดงาน (เผื่อยังไม่ได้รันจาก migrate_admin.sql)
ALTER TABLE category_line_groups
  ADD COLUMN IF NOT EXISTS openchat_url text;

-- ให้ผูกลิงก์กลุ่มได้แม้ยังไม่มี group_id (แอดมินใส่ลิงก์อย่างเดียวก่อนได้)
ALTER TABLE category_line_groups ALTER COLUMN group_id DROP NOT NULL;

SELECT (SELECT count(*) FROM providers WHERE national_id IS NOT NULL) AS มีเลขบัตร,
       (SELECT count(*) FROM category_line_groups WHERE openchat_url IS NOT NULL) AS มีลิงก์กลุ่ม;
