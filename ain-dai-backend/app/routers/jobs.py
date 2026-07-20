"""REST API สำหรับ LIFF Mini App — flow เต็ม: สร้างงาน → เสนอราคา → เลือก →
จ่าย escrow → OTP เริ่มงาน → เสร็จ → ยืนยัน → สร้าง settlement → รีวิว"""
import secrets
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import db, flex, line_api, promptpay
from ..config import settings
from ..intent import CATEGORY_NAMES
from ..settlement import FeeConfig, compute_split

router = APIRouter(prefix="/api")

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif",
               ".webm", ".ogg", ".mp3", ".m4a", ".wav"}
MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB


# ── auth ────────────────────────────────────────────────

async def current_user(
    authorization: str = Header(default=""),
    x_debug_user: str = Header(default=""),
) -> dict:
    """DEV: header X-Debug-User = line_user_id | PROD: Bearer <LIFF id_token>"""
    line_user_id = None
    liff_name = ""
    if settings.dev_mode and x_debug_user:
        line_user_id = x_debug_user
    elif authorization.startswith("Bearer "):
        profile = await line_api.verify_liff_token(authorization[7:])
        if profile:
            line_user_id = profile.get("sub")
            liff_name = profile.get("name") or ""
    if not line_user_id:
        raise HTTPException(401, "ยืนยันตัวตนไม่สำเร็จ")
    row = await db.get_pool().fetchrow(
        """INSERT INTO users (line_user_id, display_name)
           VALUES ($1, COALESCE(NULLIF($2, ''), 'ผู้ใช้ใหม่'))
           ON CONFLICT (line_user_id) DO UPDATE
             SET display_name = CASE
                   WHEN users.display_name = 'ผู้ใช้ใหม่' AND NULLIF($2, '') IS NOT NULL
                   THEN $2 ELSE users.display_name END
           RETURNING *""",
        line_user_id, liff_name,
    )
    return dict(row)


# ── ข้อมูลอ้างอิง (หมวดงาน/ตำบล/ช่างแนะนำ) ──────────────

@router.get("/meta")
async def meta():
    pool = db.get_pool()
    cats = await pool.fetch(
        "SELECT slug, name_th, icon FROM service_categories WHERE active ORDER BY id")
    tambons = await pool.fetch("SELECT id, name, amphoe FROM tambons ORDER BY id")
    return {"categories": [dict(r) for r in cats],
            "tambons": [dict(r) for r in tambons],
            "liff_id": settings.liff_id,
            "dev_mode": settings.dev_mode}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    """ข้อมูลผู้ใช้ที่ล็อกอินอยู่ + สถานะการเป็นช่าง"""
    prov = await db.get_pool().fetchrow(
        """SELECT p.*,
                  (SELECT array_agg(c.slug) FROM service_categories c
                    WHERE c.id = ANY(p.categories)) AS category_slugs
             FROM providers p WHERE p.user_id = $1""",
        user["id"])
    return {
        "line_user_id": user["line_user_id"],
        "display_name": user["display_name"],
        "phone": user["phone"],
        "is_provider": bool(prov and prov["active"]),
        "provider": {
            "bio": prov["bio"], "promptpay_id": prov["promptpay_id"],
            "category_slugs": prov["category_slugs"] or [],
            "tambon_coverage": prov["tambon_coverage"],
            "rating_avg": prov["rating_avg"], "rating_count": prov["rating_count"],
            "jobs_done": prov["jobs_done"], "verified": prov["verified"],
        } if prov else None,
    }


# ── สมัคร/แก้ไขข้อมูลช่าง ───────────────────────────────

class ProviderRegisterIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=60)
    phone: str | None = Field(default=None, max_length=20)
    bio: str | None = Field(default=None, max_length=300)
    promptpay_id: str | None = Field(default=None, max_length=20)
    category_slugs: list[str] = Field(min_length=1)
    tambon_ids: list[int] = Field(min_length=1)


@router.post("/provider/register", status_code=201)
async def provider_register(body: ProviderRegisterIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    cat_rows = await pool.fetch(
        "SELECT id FROM service_categories WHERE slug = ANY($1::text[]) AND active",
        list(set(body.category_slugs)))
    if len(cat_rows) != len(set(body.category_slugs)):
        raise HTTPException(400, "มีหมวดงานที่ไม่รู้จัก")
    tambon_ids = list(set(body.tambon_ids))
    tam_count = await pool.fetchval(
        "SELECT count(*) FROM tambons WHERE id = ANY($1::int[])", tambon_ids)
    if tam_count != len(tambon_ids):
        raise HTTPException(400, "มีตำบลที่ไม่รู้จัก")
    await pool.execute(
        """INSERT INTO providers (user_id, categories, tambon_coverage, bio, promptpay_id)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (user_id) DO UPDATE
             SET categories = $2, tambon_coverage = $3, bio = $4,
                 promptpay_id = $5, active = true""",
        user["id"], [r["id"] for r in cat_rows], tambon_ids,
        body.bio, body.promptpay_id)
    await pool.execute(
        "UPDATE users SET display_name = $2, phone = $3, role = 'provider' WHERE id = $1",
        user["id"], body.display_name, body.phone)
    return {"ok": True}


@router.get("/providers/top")
async def top_providers():
    rows = await db.get_pool().fetch(
        """SELECT u.display_name, p.bio, p.rating_avg, p.rating_count, p.jobs_done,
                  p.verified, t.name AS tambon_name
             FROM providers p
             JOIN users u ON u.id = p.user_id
             LEFT JOIN tambons t ON t.id = u.tambon_id
            WHERE p.active
            ORDER BY p.rating_avg DESC, p.jobs_done DESC LIMIT 5""")
    return [dict(r) for r in rows]


# ── อัปโหลดไฟล์ (รูป/เสียง) ─────────────────────────────

@router.post("/uploads", status_code=201)
async def upload_file(file: UploadFile = File(...), user: dict = Depends(current_user)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"ไม่รองรับไฟล์ชนิด {ext or '(ไม่มีนามสกุล)'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "ไฟล์ใหญ่เกิน 10 MB")
    name = f"{uuid.uuid4().hex}{ext}"
    UPLOAD_DIR.mkdir(exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)
    return {"url": f"/uploads/{name}"}


# ── สร้างงาน ────────────────────────────────────────────

class JobIn(BaseModel):
    category_slug: str
    tambon_id: int
    title: str = Field(min_length=2, max_length=120)
    description: str | None = None
    photos: list[str] = []
    voice_note_url: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    preferred_date: date | None = None
    preferred_time: str | None = None
    address_full: str | None = None


@router.post("/jobs", status_code=201)
async def create_job(body: JobIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    cat = await pool.fetchrow("SELECT * FROM service_categories WHERE slug = $1", body.category_slug)
    if not cat:
        raise HTTPException(400, "ไม่รู้จักหมวดงานนี้")
    job = await pool.fetchrow(
        """INSERT INTO jobs (customer_id, category_id, tambon_id, title, description,
             photos, voice_note_url, budget_min, budget_max, preferred_date,
             preferred_time, address_full, status, expires_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'bidding', now() + interval '72 hours')
           RETURNING *""",
        user["id"], cat["id"], body.tambon_id, body.title, body.description,
        body.photos, body.voice_note_url, body.budget_min, body.budget_max,
        body.preferred_date, body.preferred_time, body.address_full,
    )
    await broadcast_job(dict(job), cat["name_th"])
    return {"job_id": str(job["id"]), "status": job["status"]}


async def broadcast_job(job: dict, category_name: str) -> None:
    """ส่งการ์ดงาน (ปิดข้อมูลลูกค้า) เข้ากลุ่มไลน์ช่างตำบล ถ้ามี"""
    pool = db.get_pool()
    tambon = await pool.fetchrow("SELECT name FROM tambons WHERE id = $1", job["tambon_id"])
    group = await pool.fetchrow(
        "SELECT group_id FROM tambon_line_groups WHERE tambon_id = $1 AND active", job["tambon_id"])
    if group:
        card = flex.job_card(
            {**job, "id": str(job["id"])}, category_name, tambon["name"] if tambon else "-")
        try:
            await line_api.push(group["group_id"], [card])
        except Exception:
            pass  # กลุ่มส่งไม่ได้ อย่าให้การสร้างงานล้ม — log ใน production


# ── เสนอราคา ────────────────────────────────────────────

class BidIn(BaseModel):
    price: Decimal = Field(gt=0)
    message: str | None = None
    available_at: str | None = None


@router.post("/jobs/{job_id}/bids", status_code=201)
async def create_bid(job_id: str, body: BidIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    provider = await pool.fetchrow("SELECT * FROM providers WHERE user_id = $1 AND active", user["id"])
    if not provider:
        raise HTTPException(403, "ต้องลงทะเบียนเป็นช่างก่อนจึงเสนอราคาได้")
    job = await pool.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
    if not job or job["status"] not in ("open", "bidding"):
        raise HTTPException(400, "งานนี้ปิดรับข้อเสนอแล้ว")
    bid = await pool.fetchrow(
        """INSERT INTO bids (job_id, provider_id, price, message, available_at)
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (job_id, provider_id) DO UPDATE
             SET price = $3, message = $4, available_at = $5, status = 'active'
           RETURNING id""",
        job["id"], provider["id"], body.price, body.message, body.available_at,
    )
    return {"bid_id": str(bid["id"])}


@router.get("/jobs/{job_id}/bids")
async def list_bids(job_id: str, user: dict = Depends(current_user)):
    """ลูกค้าเห็นข้อเสนอ: ชื่อ รูป เรตติ้ง ราคา — ไม่มีเบอร์ช่าง (กัน bypass)"""
    rows = await db.get_pool().fetch(
        """SELECT b.id, b.price, b.message, b.available_at, b.status,
                  u.display_name, p.photo_url, p.rating_avg, p.rating_count, p.jobs_done, p.verified
             FROM bids b
             JOIN providers p ON p.id = b.provider_id
             JOIN users u ON u.id = p.user_id
            WHERE b.job_id = $1::uuid AND b.status = 'active'
            ORDER BY b.price ASC""",
        job_id,
    )
    return [dict(r) | {"id": str(r["id"])} for r in rows]


# ── รายละเอียด/รายการงาน ────────────────────────────────

@router.get("/my/jobs")
async def my_jobs(user: dict = Depends(current_user)):
    """งานทั้งหมดของลูกค้าคนนี้ (ใหม่→เก่า)"""
    rows = await db.get_pool().fetch(
        """SELECT j.id, j.title, j.status, j.created_at, c.icon, c.name_th AS category_name,
                  t.name AS tambon_name,
                  (SELECT count(*) FROM bids b WHERE b.job_id = j.id AND b.status = 'active') AS bids_count
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             JOIN tambons t ON t.id = j.tambon_id
            WHERE j.customer_id = $1
            ORDER BY j.created_at DESC LIMIT 20""",
        user["id"],
    )
    return [dict(r) | {"id": str(r["id"]), "created_at": r["created_at"].isoformat()} for r in rows]


@router.get("/provider/jobs")
async def provider_jobs(user: dict = Depends(current_user)):
    """ฝั่งช่าง: งานเปิดรับข้อเสนอในพื้นที่+หมวดของตน และงานที่ตนถูกเลือก"""
    pool = db.get_pool()
    prov = await pool.fetchrow(
        "SELECT * FROM providers WHERE user_id = $1 AND active", user["id"])
    if not prov:
        raise HTTPException(403, "ต้องลงทะเบียนเป็นช่างก่อน")
    open_jobs = await pool.fetch(
        """SELECT j.id, j.title, j.description, j.photos, j.voice_note_url,
                  j.budget_min, j.budget_max, j.preferred_time, j.created_at,
                  c.icon, c.name_th AS category_name, t.name AS tambon_name,
                  (SELECT b.price FROM bids b
                    WHERE b.job_id = j.id AND b.provider_id = $1 AND b.status = 'active') AS my_price
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             JOIN tambons t ON t.id = j.tambon_id
            WHERE j.status = 'bidding'
              AND j.tambon_id = ANY($2) AND j.category_id = ANY($3)
            ORDER BY j.created_at DESC LIMIT 20""",
        prov["id"], prov["tambon_coverage"], prov["categories"],
    )
    mine = await pool.fetch(
        """SELECT j.id, j.title, j.status, b.price, c.icon, t.name AS tambon_name,
                  j.photos, j.voice_note_url, j.description
             FROM jobs j
             JOIN bids b ON b.id = j.assigned_bid_id AND b.provider_id = $1
             JOIN service_categories c ON c.id = j.category_id
             JOIN tambons t ON t.id = j.tambon_id
            WHERE j.status IN ('assigned','in_progress','done','confirmed','settled')
            ORDER BY j.created_at DESC LIMIT 10""",
        prov["id"],
    )
    fix = lambda r: dict(r) | {"id": str(r["id"])}
    return {"open": [fix(r) | {"created_at": r["created_at"].isoformat()} for r in open_jobs],
            "mine": [fix(r) for r in mine]}


@router.get("/jobs/{job_id}")
async def job_detail(job_id: str, user: dict = Depends(current_user)):
    """สถานะงานฉบับเต็ม — ลูกค้าเห็น OTP, ช่างที่ถูกเลือกเห็นงานตน"""
    pool = db.get_pool()
    job = await pool.fetchrow(
        """SELECT j.*, c.name_th AS category_name, c.icon, t.name AS tambon_name
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             JOIN tambons t ON t.id = j.tambon_id
            WHERE j.id = $1::uuid""",
        job_id,
    )
    if not job:
        raise HTTPException(404, "ไม่พบงานนี้")
    selected = None
    if job["assigned_bid_id"]:
        selected = await pool.fetchrow(
            """SELECT b.price, u.display_name, p.user_id, p.rating_avg
                 FROM bids b JOIN providers p ON p.id = b.provider_id
                 JOIN users u ON u.id = p.user_id WHERE b.id = $1""",
            job["assigned_bid_id"])
    is_customer = job["customer_id"] == user["id"]
    is_provider = selected is not None and selected["user_id"] == user["id"]
    if not (is_customer or is_provider) and job["status"] not in ("open", "bidding"):
        raise HTTPException(403, "ไม่มีสิทธิ์ดูงานนี้")
    payment = await pool.fetchrow(
        "SELECT id, status, amount FROM payments WHERE job_id = $1 ORDER BY created_at DESC LIMIT 1",
        job["id"])
    settlement = await pool.fetchrow("SELECT * FROM settlements WHERE job_id = $1", job["id"])
    review = await pool.fetchrow("SELECT rating, comment FROM reviews WHERE job_id = $1", job["id"])
    bids_count = await pool.fetchval(
        "SELECT count(*) FROM bids WHERE job_id = $1 AND status IN ('active','selected')", job["id"])
    return {
        "id": str(job["id"]), "title": job["title"], "status": job["status"],
        "description": job["description"], "photos": job["photos"] or [],
        "voice_note_url": job["voice_note_url"],
        "budget_min": job["budget_min"], "budget_max": job["budget_max"],
        "preferred_time": job["preferred_time"],
        "category_name": job["category_name"], "icon": job["icon"],
        "tambon_name": job["tambon_name"], "bids_count": bids_count,
        "is_customer": is_customer, "is_provider": is_provider,
        "otp": job["start_otp"] if is_customer and job["status"] == "assigned" else None,
        "selected": {"display_name": selected["display_name"], "price": selected["price"],
                     "rating_avg": selected["rating_avg"]} if selected else None,
        "payment": {"id": str(payment["id"]), "status": payment["status"],
                    "amount": payment["amount"]} if payment else None,
        "settlement": {k: str(settlement[k]) for k in
                       ("gross", "provider_net", "platform_fee", "fund_amount", "tax_withheld")}
                      if settlement else None,
        "review": dict(review) if review else None,
    }


# ── QR PromptPay จริง (EMVCo) ───────────────────────────

@router.get("/payments/{payment_id}/qr.png")
async def payment_qr(payment_id: str):
    """QR สแกนจ่ายได้จริง เข้าบัญชี PROMPTPAY_ID (ไม่ต้อง auth — ใช้ใน <img>)"""
    p = await db.get_pool().fetchrow(
        "SELECT amount FROM payments WHERE id = $1::uuid", payment_id)
    if not p:
        raise HTTPException(404, "ไม่พบรายการชำระเงิน")
    png = promptpay.qr_png(settings.promptpay_id, float(p["amount"]))
    return Response(png, media_type="image/png")


# ── เลือกช่าง + จ่ายเงิน escrow ─────────────────────────

@router.post("/jobs/{job_id}/select/{bid_id}")
async def select_bid(job_id: str, bid_id: str, user: dict = Depends(current_user)):
    pool = db.get_pool()
    job = await pool.fetchrow(
        "SELECT * FROM jobs WHERE id = $1::uuid AND customer_id = $2", job_id, user["id"])
    if not job or job["status"] != "bidding":
        raise HTTPException(400, "เลือกช่างไม่ได้ในสถานะนี้")
    bid = await pool.fetchrow(
        "SELECT * FROM bids WHERE id = $1::uuid AND job_id = $2", bid_id, job["id"])
    if not bid:
        raise HTTPException(404, "ไม่พบข้อเสนอนี้")
    payment = await pool.fetchrow(
        """INSERT INTO payments (job_id, amount, method) VALUES ($1, $2, 'promptpay_qr')
           RETURNING id""",
        job["id"], bid["price"],
    )
    await pool.execute("UPDATE jobs SET assigned_bid_id = $1 WHERE id = $2", bid["id"], job["id"])
    return {"payment_id": str(payment["id"]), "amount": str(bid["price"]),
            "message": "สแกนจ่าย PromptPay แล้วยืนยันการโอน"}


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(payment_id: str, user: dict = Depends(current_user)):
    """MVP: ลูกค้ากดยืนยันโอน + แอดมินตรวจสลิป | เฟส 2: gateway ยิง callback แทน
    จ่ายแล้ว → สุ่ม OTP, สถานะ assigned, แจ้งช่าง"""
    pool = db.get_pool()
    payment = await pool.fetchrow(
        """UPDATE payments SET status = 'paid', paid_at = now()
            WHERE id = $1::uuid AND status = 'pending' RETURNING *""",
        payment_id,
    )
    if not payment:
        raise HTTPException(400, "ไม่พบรายการหรือจ่ายไปแล้ว")
    otp = f"{secrets.randbelow(10000):04d}"
    job = await pool.fetchrow(
        """UPDATE jobs SET status = 'assigned', start_otp = $2
            WHERE id = $1 RETURNING *""",
        payment["job_id"], otp,
    )
    await pool.execute("UPDATE bids SET status = 'selected' WHERE id = $1", job["assigned_bid_id"])
    await pool.execute(
        "UPDATE bids SET status = 'rejected' WHERE job_id = $1 AND id <> $2 AND status = 'active'",
        job["id"], job["assigned_bid_id"])
    # แจ้งช่างที่ถูกเลือก
    prov = await pool.fetchrow(
        """SELECT u.line_user_id FROM bids b
             JOIN providers p ON p.id = b.provider_id JOIN users u ON u.id = p.user_id
            WHERE b.id = $1""", job["assigned_bid_id"])
    if prov:
        try:
            await line_api.push(prov["line_user_id"], [{
                "type": "text",
                "text": f"🎉 คุณได้งาน \"{job['title']}\" แล้ว!\nลูกค้าจ่ายเงินเข้าระบบเรียบร้อย เงินพักปลอดภัยใน escrow\n\nเมื่อถึงหน้างาน ขอรหัส 4 หลักจากลูกค้าแล้วกรอกในระบบเพื่อเริ่มงานครับ"}])
        except Exception:
            pass
    return {"job_id": str(job["id"]), "status": "assigned", "customer_otp": otp}


# ── OTP เริ่มงาน / เสร็จงาน / ยืนยัน ────────────────────

class OtpIn(BaseModel):
    otp: str = Field(min_length=4, max_length=4)


@router.post("/jobs/{job_id}/start")
async def verify_otp(job_id: str, body: OtpIn, user: dict = Depends(current_user)):
    job = await db.get_pool().fetchrow(
        """UPDATE jobs SET status = 'in_progress', otp_verified_at = now()
            WHERE id = $1::uuid AND status = 'assigned' AND start_otp = $2
           RETURNING id""",
        job_id, body.otp,
    )
    if not job:
        raise HTTPException(400, "รหัสไม่ถูกต้องหรือสถานะงานไม่พร้อมเริ่ม")
    return {"status": "in_progress"}


class CompleteIn(BaseModel):
    photos: list[str] = []


@router.post("/jobs/{job_id}/complete")
async def complete_job(job_id: str, body: CompleteIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    job = await pool.fetchrow(
        """UPDATE jobs SET status = 'done',
                 photos = COALESCE(photos, '{}') || $2::text[]
            WHERE id = $1::uuid AND status = 'in_progress' RETURNING *""",
        job_id, body.photos,
    )
    if not job:
        raise HTTPException(400, "งานยังไม่อยู่ในสถานะกำลังทำ")
    customer = await pool.fetchrow("SELECT line_user_id FROM users WHERE id = $1", job["customer_id"])
    if customer:
        try:
            await line_api.push(customer["line_user_id"], [{
                "type": "text",
                "text": f"✅ ช่างแจ้งว่างาน \"{job['title']}\" เสร็จแล้ว\nตรวจงานแล้วกดยืนยันในแอปเพื่อปล่อยเงินให้ช่างครับ (ถ้าไม่กดภายใน 24 ชม. ระบบยืนยันให้อัตโนมัติ)"}])
        except Exception:
            pass
    return {"status": "done"}


@router.post("/jobs/{job_id}/approve")
async def approve_job(job_id: str, user: dict = Depends(current_user)):
    pool = db.get_pool()
    job = await pool.fetchrow(
        """UPDATE jobs SET status = 'confirmed'
            WHERE id = $1::uuid AND customer_id = $2 AND status = 'done' RETURNING *""",
        job_id, user["id"],
    )
    if not job:
        raise HTTPException(400, "ยืนยันไม่ได้ในสถานะนี้")
    settle = await create_settlement(job["id"])
    # แต้มสะสมผู้จ้าง + นับผลงานช่าง
    await pool.execute(
        "INSERT INTO points_ledger (user_id, job_id, points, reason) VALUES ($1,$2,20,'job_completed')",
        user["id"], job["id"])
    await pool.execute(
        """UPDATE providers SET jobs_done = jobs_done + 1
            WHERE id = (SELECT provider_id FROM bids WHERE id = $1)""",
        job["assigned_bid_id"])
    return {"status": "confirmed", "settlement": settle}


# ── รีวิวช่างหลังจบงาน ──────────────────────────────────

class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


@router.post("/jobs/{job_id}/reviews", status_code=201)
async def create_review(job_id: str, body: ReviewIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    job = await pool.fetchrow(
        "SELECT * FROM jobs WHERE id = $1::uuid AND customer_id = $2", job_id, user["id"])
    if not job or job["status"] not in ("confirmed", "settled"):
        raise HTTPException(400, "รีวิวได้หลังยืนยันจบงานแล้วเท่านั้น")
    provider_id = await pool.fetchval(
        "SELECT provider_id FROM bids WHERE id = $1", job["assigned_bid_id"])
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """INSERT INTO reviews (job_id, provider_id, rating, comment)
               VALUES ($1,$2,$3,$4) ON CONFLICT (job_id) DO NOTHING RETURNING id""",
            job["id"], provider_id, body.rating, body.comment)
        if not row:
            raise HTTPException(400, "งานนี้รีวิวไปแล้ว")
        prov = await conn.fetchrow(
            """UPDATE providers
                  SET rating_avg = round((rating_avg * rating_count + $2)::numeric
                                         / (rating_count + 1), 2),
                      rating_count = rating_count + 1
                WHERE id = $1
              RETURNING rating_avg, rating_count""",
            provider_id, body.rating)
    return {"review_id": str(row["id"]), "rating_avg": str(prov["rating_avg"]),
            "rating_count": prov["rating_count"]}


async def create_settlement(job_id) -> dict:
    """คำนวณแบ่งเงินจาก fee_config ล่าสุด บันทึก settlement + เข้ากองทุนตำบล"""
    pool = db.get_pool()
    async with pool.acquire() as conn, conn.transaction():
        existing = await conn.fetchrow("SELECT id FROM settlements WHERE job_id = $1", job_id)
        if existing:
            return {"settlement_id": str(existing["id"]), "note": "มีอยู่แล้ว"}
        job = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        bid = await conn.fetchrow("SELECT price FROM bids WHERE id = $1", job["assigned_bid_id"])
        cfg = await conn.fetchrow("SELECT * FROM fee_config ORDER BY effective_from DESC, id DESC LIMIT 1")
        split = compute_split(bid["price"], FeeConfig(
            provider_pct=cfg["provider_pct"], platform_pct=cfg["platform_pct"],
            fund_pct=cfg["fund_pct"], tax_pct=cfg["tax_pct"]))
        row = await conn.fetchrow(
            """INSERT INTO settlements (job_id, fee_config_id, gross, provider_net,
                 platform_fee, fund_amount, tax_withheld)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            job_id, cfg["id"], split.gross, split.provider_net,
            split.platform_fee, split.fund_amount, split.tax_withheld)
        await conn.execute(
            """INSERT INTO community_fund_ledger (tambon_id, job_id, amount, note)
               VALUES ($1,$2,$3,'ส่วนแบ่ง 2% จากงาน')""",
            job["tambon_id"], job_id, split.fund_amount)
    return {"settlement_id": str(row["id"]), "gross": str(split.gross),
            "provider_net": str(split.provider_net), "platform_fee": str(split.platform_fee),
            "fund_amount": str(split.fund_amount), "tax_withheld": str(split.tax_withheld)}
