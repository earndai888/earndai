-- ═══════════════════════════════════════════════════════
-- เอิ้นได้ (Ain Dai) — Database Schema v1.1
-- PostgreSQL 15+ | รัน: psql -d aindai -f schema.sql
-- อัตราแบ่งเงิน: ช่าง 89% (90% − ภาษี 1%), ค่าระบบ 8%, กองทุนชุมชน 2%
-- ═══════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── พื้นที่และหมวดงาน ──────────────────────────────────

CREATE TABLE tambons (
  id        serial PRIMARY KEY,
  name      text NOT NULL,
  amphoe    text NOT NULL,
  province  text NOT NULL DEFAULT 'ศรีสะเกษ',
  UNIQUE (name, amphoe, province)
);

CREATE TABLE service_categories (
  id       serial PRIMARY KEY,
  slug     text UNIQUE NOT NULL,
  name_th  text NOT NULL,
  icon     text,
  active   boolean NOT NULL DEFAULT true
);

-- ── ผู้ใช้และช่าง ──────────────────────────────────────

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  line_user_id  text UNIQUE NOT NULL,
  role          text NOT NULL DEFAULT 'customer'
                CHECK (role IN ('customer','provider','admin')),
  display_name  text NOT NULL,
  phone         text,
  tambon_id     int REFERENCES tambons(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE providers (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid UNIQUE NOT NULL REFERENCES users(id),
  categories       int[] NOT NULL,
  tambon_coverage  int[] NOT NULL,
  bio              text,
  photo_url        text,
  promptpay_id     text,
  national_id_hash text,
  verified         boolean NOT NULL DEFAULT false,
  rating_avg       numeric(3,2) NOT NULL DEFAULT 0,
  rating_count     int NOT NULL DEFAULT 0,
  jobs_done        int NOT NULL DEFAULT 0,
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- ── งานและการเสนอราคา ─────────────────────────────────

CREATE TABLE jobs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id      uuid NOT NULL REFERENCES users(id),
  category_id      int NOT NULL REFERENCES service_categories(id),
  tambon_id        int NOT NULL REFERENCES tambons(id),
  title            text NOT NULL,
  description      text,
  photos           text[],
  voice_note_url   text,
  voice_transcript text,
  budget_min       numeric(10,2),
  budget_max       numeric(10,2),
  preferred_date   date,
  preferred_time   text,
  address_full     text,
  lat              numeric(9,6),
  lng              numeric(9,6),
  start_otp        char(4),
  otp_verified_at  timestamptz,
  status           text NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','bidding','assigned','in_progress',
                          'done','confirmed','settled','cancelled','expired','disputed')),
  assigned_bid_id  uuid,
  expires_at       timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bids (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id        uuid NOT NULL REFERENCES jobs(id),
  provider_id   uuid NOT NULL REFERENCES providers(id),
  price         numeric(10,2) NOT NULL CHECK (price > 0),
  message       text,
  available_at  text,
  status        text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','withdrawn','selected','rejected','expired')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, provider_id)
);

ALTER TABLE jobs
  ADD CONSTRAINT fk_jobs_assigned_bid
  FOREIGN KEY (assigned_bid_id) REFERENCES bids(id);

-- ── เงิน: escrow, settlement, กองทุน ───────────────────

CREATE TABLE fee_config (
  id             serial PRIMARY KEY,
  effective_from date NOT NULL,
  provider_pct   numeric(5,4) NOT NULL DEFAULT 0.90,
  platform_pct   numeric(5,4) NOT NULL DEFAULT 0.08,
  fund_pct       numeric(5,4) NOT NULL DEFAULT 0.02,
  tax_pct        numeric(5,4) NOT NULL DEFAULT 0.01,  -- หักจากส่วนช่าง (แบบ ก)
  auto_release_hours int NOT NULL DEFAULT 24,
  CHECK (provider_pct + platform_pct + fund_pct = 1.0)
);

CREATE TABLE payments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      uuid NOT NULL REFERENCES jobs(id),
  amount      numeric(10,2) NOT NULL CHECK (amount > 0),
  method      text NOT NULL CHECK (method IN ('promptpay_qr','gateway')),
  status      text NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','paid','refunded','released')),
  slip_url    text,
  paid_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE settlements (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id          uuid UNIQUE NOT NULL REFERENCES jobs(id),
  fee_config_id   int NOT NULL REFERENCES fee_config(id),
  gross           numeric(10,2) NOT NULL,
  provider_net    numeric(10,2) NOT NULL,   -- = gross − platform − fund − tax
  platform_fee    numeric(10,2) NOT NULL,
  fund_amount     numeric(10,2) NOT NULL,
  tax_withheld    numeric(10,2) NOT NULL,
  status          text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','transferred')),
  transferred_at  timestamptz,
  transfer_ref    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (provider_net + platform_fee + fund_amount + tax_withheld = gross)
);

CREATE TABLE community_fund_ledger (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tambon_id   int NOT NULL REFERENCES tambons(id),
  job_id      uuid REFERENCES jobs(id),
  amount      numeric(10,2) NOT NULL,   -- บวก = เข้ากองทุน, ลบ = เบิกใช้
  note        text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ── แชท รีวิว แต้ม กลุ่มไลน์ ───────────────────────────

CREATE TABLE job_messages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      uuid NOT NULL REFERENCES jobs(id),
  sender_id   uuid NOT NULL REFERENCES users(id),
  body        text,
  photo_url   text,
  flagged     boolean NOT NULL DEFAULT false,  -- regex จับเบอร์/ไลน์ไอดี กัน bypass
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reviews (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id       uuid UNIQUE NOT NULL REFERENCES jobs(id),
  provider_id  uuid NOT NULL REFERENCES providers(id),
  rating       int NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment      text,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE points_ledger (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  job_id      uuid REFERENCES jobs(id),
  points      int NOT NULL,
  reason      text NOT NULL CHECK (reason IN ('job_completed','review_given','redeemed','admin_adjust')),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tambon_line_groups (
  id         serial PRIMARY KEY,
  tambon_id  int UNIQUE REFERENCES tambons(id),
  group_id   text NOT NULL,
  active     boolean NOT NULL DEFAULT true
);

-- กลุ่มไลน์ช่างแยกตามหมวดงาน (นำร่อง: 1 หมวด = 1 กลุ่ม)
CREATE TABLE category_line_groups (
  id           serial PRIMARY KEY,
  category_id  int UNIQUE REFERENCES service_categories(id),
  group_id     text NOT NULL,
  active       boolean NOT NULL DEFAULT true
);

-- ── Indexes ────────────────────────────────────────────

CREATE INDEX idx_jobs_match      ON jobs (status, tambon_id, category_id);
CREATE INDEX idx_bids_job        ON bids (job_id);
CREATE INDEX idx_prov_cats       ON providers USING gin (categories);
CREATE INDEX idx_prov_tambons    ON providers USING gin (tambon_coverage);
CREATE INDEX idx_fund_tambon     ON community_fund_ledger (tambon_id);
CREATE INDEX idx_msg_job         ON job_messages (job_id, created_at);
CREATE INDEX idx_points_user     ON points_ledger (user_id);

-- ── Seed data เริ่มต้น ─────────────────────────────────

INSERT INTO fee_config (effective_from) VALUES (CURRENT_DATE);

-- นำร่องอำเภอกันทรลักษ์ 4 หมวดงาน
INSERT INTO service_categories (slug, name_th, icon) VALUES
  ('ac-cleaning',  'ช่างแอร์',           '❄️'),
  ('gardening',    'งานสวน/ตัดหญ้า',     '🌿'),
  ('housekeeping', 'แม่บ้าน',            '🧹'),
  ('emergency',    'งานฉุกเฉิน 24 ชม.',  '🚨');

-- ตำบลในอำเภอกันทรลักษ์ จ.ศรีสะเกษ (20 ตำบล)
INSERT INTO tambons (name, amphoe) VALUES
  ('บึงมะลู',      'กันทรลักษ์'),
  ('กุดเสลา',      'กันทรลักษ์'),
  ('เมือง',        'กันทรลักษ์'),
  ('สังเม็ก',      'กันทรลักษ์'),
  ('น้ำอ้อม',      'กันทรลักษ์'),
  ('ละลาย',        'กันทรลักษ์'),
  ('รุง',          'กันทรลักษ์'),
  ('ตระกาจ',       'กันทรลักษ์'),
  ('จานใหญ่',      'กันทรลักษ์'),
  ('ภูเงิน',       'กันทรลักษ์'),
  ('ชำ',           'กันทรลักษ์'),
  ('กระแชง',       'กันทรลักษ์'),
  ('โนนสำราญ',     'กันทรลักษ์'),
  ('หนองหญ้าลาด',  'กันทรลักษ์'),
  ('เสาธงชัย',     'กันทรลักษ์'),
  ('ขนุน',         'กันทรลักษ์'),
  ('สวนกล้วย',     'กันทรลักษ์'),
  ('เวียงเหนือ',   'กันทรลักษ์'),
  ('ทุ่งใหญ่',     'กันทรลักษ์'),
  ('ภูผาหมอก',     'กันทรลักษ์');

-- ตัวอย่างการคำนวณ settlement แบบ ก (ทำใน backend):
--   gross = 1000.00
--   platform_fee = round(gross * 0.08, 2)  = 80.00
--   fund_amount  = round(gross * 0.02, 2)  = 20.00
--   tax_withheld = round(gross * 0.01, 2)  = 10.00
--   provider_net = gross - 80 - 20 - 10    = 890.00  (ปัดเศษลงที่ provider_net เสมอ)
