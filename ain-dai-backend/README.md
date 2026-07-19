# เอิ้นได้ — Backend (FastAPI)

บริการท้องถิ่น ใกล้คุณ | LINE webhook + AI intent ชั้นที่ 1 + escrow settlement

## โครงสร้าง

```
app/
  main.py            FastAPI app + worker auto-release 24 ชม.
  config.py          ค่า config จาก .env
  db.py              asyncpg pool
  intent.py          AI ชั้นที่ 1: keyword matching ไทย → หมวดงาน
  settlement.py      คำนวณแบ่งเงินแบบ ก (89/8/2/1) + กติกาปัดเศษ
  line_api.py        เรียก LINE Messaging API + ตรวจลายเซ็น webhook
  flex.py            การ์ดงาน Flex Message + quick reply
  routers/
    webhook.py       POST /webhook/line — รับ event จาก LINE
    jobs.py          REST API สำหรับ LIFF (สร้างงาน→เสนอราคา→จ่าย→OTP→ยืนยัน)
schema.sql           PostgreSQL schema v1.1 + seed data
tests/               pytest: settlement + intent
```

## ติดตั้ง

```bash
# 1. ฐานข้อมูล
createdb aindai
psql -d aindai -f schema.sql

# 2. Python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. ค่า config
cp .env.example .env   # แก้ค่าจาก LINE Developers Console

# 4. รัน
uvicorn app.main:app --reload
```

ตั้งค่า webhook URL ใน LINE Developers Console เป็น
`https://โดเมนของคุณ/webhook/line` (ตอน dev ใช้ ngrok/cloudflared)

## ทดสอบ

```bash
pytest tests/ -v
```

## ลองยิง API (DEV_MODE=true ใช้ header X-Debug-User แทน token)

```bash
# สร้างงาน
curl -X POST localhost:8000/api/jobs \
  -H 'X-Debug-User: Utest-customer' -H 'Content-Type: application/json' \
  -d '{"category_slug":"gardening","tambon_id":1,"title":"ตัดหญ้าหน้าบ้าน",
       "description":"หญ้ารก มีต้นกล้วย","budget_min":300,"budget_max":500}'

# flow ต่อ: POST /api/jobs/{id}/bids → /select/{bid} → /payments/{id}/confirm
#          → /jobs/{id}/start (OTP) → /complete → /approve
```

## หมายเหตุ

- อัตราแบ่งเงิน 90/8/2 + ภาษี 1% อยู่ในตาราง `fee_config` — ปรับได้ไม่ต้องแก้โค้ด
  (อัตราภาษีหัก ณ ที่จ่ายควรยืนยันกับนักบัญชีก่อนใช้จริง)
- Intent ชั้นที่ 2 (LLM/classifier) เสียบเพิ่มได้ที่ `intent.classify()`
- MVP ยืนยันการโอนแบบ manual — เฟส 2 เปลี่ยนเป็น payment gateway callback
  ที่ `POST /payments/{id}/confirm` จุดเดียว
