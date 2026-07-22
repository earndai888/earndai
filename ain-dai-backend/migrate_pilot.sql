-- ═══════════════════════════════════════════════════════
-- ปรับฐานข้อมูลที่รันไปแล้ว → นำร่องอำเภอกันทรลักษ์ 4 หมวดงาน
-- รันซ้ำได้ (idempotent)
-- ═══════════════════════════════════════════════════════

-- 1) ตารางกลุ่มไลน์แยกตามหมวดงาน
CREATE TABLE IF NOT EXISTS category_line_groups (
  id           serial PRIMARY KEY,
  category_id  int UNIQUE REFERENCES service_categories(id),
  group_id     text NOT NULL,
  active       boolean NOT NULL DEFAULT true
);

-- 2) เหลือ 4 หมวดงานนำร่อง — ปิดหมวดอื่นทั้งหมดก่อน แล้วเปิด+เปลี่ยนชื่อ 4 หมวด
UPDATE service_categories SET active = false;

INSERT INTO service_categories (slug, name_th, icon, active) VALUES
  ('ac-cleaning',  'ช่างแอร์',           '❄️', true),
  ('gardening',    'งานสวน/ตัดหญ้า',     '🌿', true),
  ('housekeeping', 'แม่บ้าน',            '🧹', true),
  ('emergency',    'งานด่วน 24 ชม.',  '🚨', true)
ON CONFLICT (slug) DO UPDATE
  SET name_th = EXCLUDED.name_th, icon = EXCLUDED.icon, active = true;

-- 3) ตำบลในอำเภอกันทรลักษ์ (เพิ่มถ้ายังไม่มี)
INSERT INTO tambons (name, amphoe) VALUES
  ('บึงมะลู','กันทรลักษ์'), ('กุดเสลา','กันทรลักษ์'), ('เมือง','กันทรลักษ์'),
  ('สังเม็ก','กันทรลักษ์'), ('น้ำอ้อม','กันทรลักษ์'), ('ละลาย','กันทรลักษ์'),
  ('รุง','กันทรลักษ์'), ('ตระกาจ','กันทรลักษ์'), ('จานใหญ่','กันทรลักษ์'),
  ('ภูเงิน','กันทรลักษ์'), ('ชำ','กันทรลักษ์'), ('กระแชง','กันทรลักษ์'),
  ('โนนสำราญ','กันทรลักษ์'), ('หนองหญ้าลาด','กันทรลักษ์'), ('เสาธงชัย','กันทรลักษ์'),
  ('ขนุน','กันทรลักษ์'), ('สวนกล้วย','กันทรลักษ์'), ('เวียงเหนือ','กันทรลักษ์'),
  ('ทุ่งใหญ่','กันทรลักษ์'), ('ภูผาหมอก','กันทรลักษ์')
ON CONFLICT (name, amphoe, province) DO NOTHING;

-- ตรวจผล — ควรได้ categories=4, tambons_kanthara=20
SELECT (SELECT count(*) FROM service_categories WHERE active) AS active_categories,
       (SELECT count(*) FROM tambons WHERE amphoe = 'กันทรลักษ์') AS tambons_kanthara;
