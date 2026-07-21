-- ═══════════════════════════════════════════════════════
-- ระบบหลังบ้านแอดมิน: อนุมัติช่าง (KYC), ระดับช่าง, แท็กทักษะ, ข้อพิพาท
-- รันซ้ำได้ (idempotent)
-- ═══════════════════════════════════════════════════════

-- 1) ข้อมูลสมัคร/อนุมัติช่าง
ALTER TABLE providers
  ADD COLUMN IF NOT EXISTS approval_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS tier            int  NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS skill_tags      text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS id_card_url     text,
  ADD COLUMN IF NOT EXISTS selfie_url      text,
  ADD COLUMN IF NOT EXISTS license_url     text,
  ADD COLUMN IF NOT EXISTS admin_note      text,
  ADD COLUMN IF NOT EXISTS reviewed_at     timestamptz;

DO $$ BEGIN
  ALTER TABLE providers ADD CONSTRAINT providers_approval_chk
    CHECK (approval_status IN ('pending','approved','rejected','info_requested'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE providers ADD CONSTRAINT providers_tier_chk CHECK (tier BETWEEN 1 AND 3);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ช่างเดิมที่ใช้งานอยู่แล้ว → ถือว่าอนุมัติแล้ว (ไม่ให้ระบบสะดุด)
UPDATE providers SET approval_status = 'approved', reviewed_at = now()
 WHERE active AND approval_status = 'pending';

-- 2) ข้อพิพาท / แจ้งปัญหา
CREATE TABLE IF NOT EXISTS disputes (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      uuid NOT NULL REFERENCES jobs(id),
  opened_by   uuid REFERENCES users(id),
  reason      text,
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  resolution  text CHECK (resolution IN ('release','refund','fund_compensate')),
  admin_note  text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes (status, created_at DESC);

-- 3) ลิงก์กลุ่ม OpenChat ต่อหมวด (ส่งให้ช่างตอนอนุมัติ)
ALTER TABLE category_line_groups
  ADD COLUMN IF NOT EXISTS openchat_url text;

-- ตรวจผล
SELECT (SELECT count(*) FROM providers WHERE approval_status='approved') AS approved,
       (SELECT count(*) FROM providers WHERE approval_status='pending')  AS pending,
       (SELECT count(*) FROM disputes) AS disputes;
