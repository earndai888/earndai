"""REST API สำหรับ LIFF Mini App — flow เต็ม: สร้างงาน → เสนอราคา → เลือก →
จ่าย escrow → OTP เริ่มงาน → เสร็จ → ยืนยัน → สร้าง settlement → รีวิว"""
import logging
import secrets
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import contact_guard, contract, db, flex, line_api, promptpay, thai_id, vault
from ..config import settings
from ..intent import CATEGORY_NAMES, subcategories_of
from ..settlement import FeeConfig, compute_split

router = APIRouter(prefix="/api")
log = logging.getLogger("jobs")

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
    try:
        subs = await pool.fetch(
            """SELECT s.slug, s.name_th, s.icon, s.examples, c.slug AS category_slug
                 FROM service_subcategories s JOIN service_categories c ON c.id = s.category_id
                WHERE s.active AND c.active ORDER BY s.sort, s.id""")
    except Exception:  # ตารางยังไม่ถูกสร้าง (ซิงก์ตอน startup พลาด) — ไม่ควรทำให้ทั้งหน้าล่ม
        log.warning("อ่านกลุ่มงานย่อยไม่ได้ — แสดงหน้าเว็บแบบไม่มีกลุ่มย่อย")
        subs = []
    if settings.pilot_amphoe:
        tambons = await pool.fetch(
            "SELECT id, name, amphoe FROM tambons WHERE amphoe = $1 ORDER BY name",
            settings.pilot_amphoe)
    else:
        tambons = await pool.fetch("SELECT id, name, amphoe FROM tambons ORDER BY id")
    return {"categories": [dict(r) for r in cats],
            "subcategories": [dict(r) for r in subs],
            "tambons": [dict(r) for r in tambons],
            "liff_id": settings.liff_id,
            "dev_mode": settings.dev_mode}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    """ข้อมูลผู้ใช้ที่ล็อกอินอยู่ + สถานะการเป็นช่าง"""
    prov = await db.get_pool().fetchrow(
        """SELECT p.*,
                  (SELECT array_agg(c.slug) FROM service_categories c
                    WHERE c.id = ANY(p.categories)) AS category_slugs,
                  (SELECT array_agg(s.slug) FROM service_subcategories s
                    WHERE s.id = ANY(p.subcategories)) AS subcategory_slugs
             FROM providers p WHERE p.user_id = $1""",
        user["id"])
    return {
        "line_user_id": user["line_user_id"],
        "display_name": user["display_name"],
        "phone": user["phone"],
        # ทำงานได้ต่อเมื่อแอดมินอนุมัติแล้วและไม่ถูกระงับ
        "is_provider": bool(prov and prov["active"] and prov["approval_status"] == "approved"),
        "has_applied": bool(prov),
        "approval_status": prov["approval_status"] if prov else None,
        "admin_note": prov["admin_note"] if prov else None,
        "provider": {
            "bio": prov["bio"], "promptpay_id": prov["promptpay_id"],
            "category_slugs": prov["category_slugs"] or [],
            "subcategory_slugs": prov["subcategory_slugs"] or [],
            "full_name": prov["full_name"],
            # ไม่ส่งเลขบัตรเต็มกลับ — โชว์แค่ให้รู้ว่ากรอกไว้แล้ว
            "national_id_masked": thai_id.mask_id(prov["national_id"] or ""),
            "face_scan_count": len(prov["face_scan_urls"] or []),
            "contract_signed": bool(prov["contract_signature_url"]),
            # สัญญามีเวอร์ชันใหม่ → ต้องเซ็นใหม่ก่อนรับงานต่อ
            "contract_outdated": bool(prov["contract_signature_url"])
                                 and prov["contract_version"] != contract.CONTRACT_VERSION,
            "tambon_coverage": prov["tambon_coverage"],
            "rating_avg": prov["rating_avg"], "rating_count": prov["rating_count"],
            "jobs_done": prov["jobs_done"], "verified": prov["verified"],
            "tier": prov["tier"], "skill_tags": prov["skill_tags"],
            "id_card_url": prov["id_card_url"], "selfie_url": prov["selfie_url"],
            "license_url": prov["license_url"], "active": prov["active"],
        } if prov else None,
    }


# ── สมัคร/แก้ไขข้อมูลช่าง ───────────────────────────────

class ProviderRegisterIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=60)
    # ── ยืนยันตัวตน (บังคับ) ──
    full_name: str = Field(min_length=4, max_length=120)     # ชื่อ-นามสกุลจริงตามบัตร
    national_id: str = Field(min_length=13, max_length=20)   # เลขบัตรประชาชน 13 หลัก
    phone: str = Field(min_length=9, max_length=20)
    # สแกนใบหน้า + ลายเซ็นสัญญา — เว้นว่างได้เฉพาะตอนแก้โปรไฟล์ (ใช้ของเดิมที่เก็บไว้)
    face_scan_urls: list[str] = []
    contract_signature_url: str | None = None
    contract_version: str | None = None
    bio: str | None = Field(default=None, max_length=300)
    promptpay_id: str | None = Field(default=None, max_length=20)
    category_slugs: list[str] = Field(min_length=1)
    # รับงานด่วนแบบไหนบ้าง (ว่าง = รับทุกแบบในหมวดที่สมัคร)
    subcategory_slugs: list[str] = []
    tambon_ids: list[int] = Field(min_length=1)
    # เอกสารยืนยันตัวตน (อัปโหลดผ่าน /api/uploads แล้วส่ง url มา)
    id_card_url: str | None = None
    selfie_url: str | None = None
    license_url: str | None = None


@router.get("/provider/contract")
async def provider_contract():
    """หนังสือสัญญาที่ช่างต้องอ่านและเซ็นก่อนรับงาน"""
    return contract.payload()


def _check_identity(body: ProviderRegisterIn, existing: dict | None) -> dict:
    """ตรวจข้อมูลยืนยันตัวตน → คืนค่าที่ล้างแล้วพร้อมบันทึก
    แก้โปรไฟล์โดยไม่สแกนหน้า/เซ็นใหม่ได้ ถ้าเคยทำไว้แล้วและสัญญายังเวอร์ชันเดิม"""
    # ชื่อร้านกับคำแนะนำตัวคือสองอย่างเดียวที่ลูกค้าเห็น — ห้ามมีช่องทางติดต่อตรง
    for text, where in ((body.display_name, "ชื่อที่แสดงให้ลูกค้าเห็น"), (body.bio, "คำแนะนำตัว")):
        if kind := contact_guard.find_contact_leak(text):
            raise HTTPException(400, contact_guard.message(kind, where))
    if not thai_id.valid_full_name(body.full_name):
        raise HTTPException(400, "กรอกทั้งชื่อและนามสกุลจริงตามบัตรประชาชนครับ")
    if not thai_id.valid_national_id(body.national_id):
        raise HTTPException(400, "เลขบัตรประชาชนไม่ถูกต้อง ลองตรวจดูอีกทีครับ")
    phone = thai_id.normalize_phone(body.phone)
    if not phone:
        raise HTTPException(400, "เบอร์โทรศัพท์ไม่ถูกต้องครับ")

    # เอกสารยืนยันตัวตนต้องอยู่ในห้องนิรภัยเท่านั้น (กันยิง url ภายนอก และกันเก็บผิดที่)
    urls = [*body.face_scan_urls,
            *(u for u in (body.contract_signature_url, body.id_card_url,
                          body.selfie_url, body.license_url) if u)]
    if any(not vault.is_secure_url(u) for u in urls):
        raise HTTPException(400, "ไฟล์แนบไม่ถูกต้อง กรุณาถ่าย/เซ็นใหม่ครับ")

    faces = body.face_scan_urls or (existing["face_scan_urls"] if existing else [])
    if not faces:
        raise HTTPException(400, "กรุณาสแกนใบหน้าก่อนส่งใบสมัครครับ")

    signature = body.contract_signature_url
    version = body.contract_version
    if signature:
        if version != contract.CONTRACT_VERSION:
            raise HTTPException(400, "หนังสือสัญญามีการปรับปรุง กรุณาโหลดหน้าใหม่แล้วเซ็นอีกครั้งครับ")
    else:
        signature = existing["contract_signature_url"] if existing else None
        version = existing["contract_version"] if existing else None
        if not signature:
            raise HTTPException(400, "กรุณาเซ็นรับหนังสือสัญญาก่อนส่งใบสมัครครับ")
        if version != contract.CONTRACT_VERSION:
            raise HTTPException(400, "หนังสือสัญญามีการปรับปรุง กรุณาอ่านและเซ็นใหม่ครับ")

    return {"national_id": thai_id.normalize_id(body.national_id), "phone": phone,
            "faces": faces, "signature": signature, "version": version}


@router.post("/provider/register", status_code=201)
async def provider_register(body: ProviderRegisterIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    existing = await pool.fetchrow(
        """SELECT face_scan_urls, contract_signature_url, contract_version
             FROM providers WHERE user_id = $1""", user["id"])
    ident = _check_identity(body, dict(existing) if existing else None)
    national_id = ident["national_id"]
    # เลขบัตรใบเดียวสมัครได้คนเดียว — กันสวมรอย/สมัครซ้ำหลายบัญชี LINE
    dup = await pool.fetchval(
        "SELECT count(*) FROM providers WHERE national_id = $1 AND user_id <> $2",
        national_id, user["id"])
    if dup:
        raise HTTPException(400, "เลขบัตรนี้มีผู้สมัครไว้แล้ว หากเป็นของพี่จริงกรุณาติดต่อแอดมินครับ")
    cat_rows = await pool.fetch(
        "SELECT id FROM service_categories WHERE slug = ANY($1::text[]) AND active",
        list(set(body.category_slugs)))
    if len(cat_rows) != len(set(body.category_slugs)):
        raise HTTPException(400, "มีหมวดงานที่ไม่รู้จัก")
    sub_slugs = list(set(body.subcategory_slugs))
    sub_rows = await pool.fetch(
        """SELECT id FROM service_subcategories
            WHERE slug = ANY($1::text[]) AND active AND category_id = ANY($2::int[])""",
        sub_slugs, [r["id"] for r in cat_rows]) if sub_slugs else []
    if len(sub_rows) != len(sub_slugs):
        raise HTTPException(400, "มีประเภทงานย่อยที่ไม่รู้จัก หรือไม่อยู่ในหมวดที่เลือก")
    tambon_ids = list(set(body.tambon_ids))
    tam_count = await pool.fetchval(
        "SELECT count(*) FROM tambons WHERE id = ANY($1::int[])", tambon_ids)
    if tam_count != len(tambon_ids):
        raise HTTPException(400, "มีตำบลที่ไม่รู้จัก")
    # สมัครใหม่/แก้ไข → กลับเข้าคิวรออนุมัติ ยกเว้นช่างที่อนุมัติแล้ว (แก้โปรไฟล์ได้เลย)
    row = await pool.fetchrow(
        """INSERT INTO providers (user_id, categories, tambon_coverage, bio, promptpay_id,
                                  id_card_url, selfie_url, license_url, subcategories,
                                  full_name, national_id, face_scan_urls,
                                  contract_signature_url, contract_version, contract_signed_at,
                                  approval_status, active)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,now(),'pending',false)
           ON CONFLICT (user_id) DO UPDATE
             SET categories = $2, tambon_coverage = $3, bio = $4, promptpay_id = $5,
                 id_card_url = COALESCE($6, providers.id_card_url),
                 selfie_url  = COALESCE($7, providers.selfie_url),
                 license_url = COALESCE($8, providers.license_url),
                 subcategories = $9,
                 full_name = $10, national_id = $11, face_scan_urls = $12,
                 contract_signature_url = $13, contract_version = $14, contract_signed_at = now(),
                 approval_status = CASE WHEN providers.approval_status = 'approved'
                                        THEN 'approved' ELSE 'pending' END
           RETURNING approval_status""",
        user["id"], [r["id"] for r in cat_rows], tambon_ids,
        body.bio, body.promptpay_id, body.id_card_url, body.selfie_url, body.license_url,
        [r["id"] for r in sub_rows],
        body.full_name.strip(), national_id, ident["faces"],
        ident["signature"], ident["version"])
    await pool.execute(
        "UPDATE users SET display_name = $2, phone = $3, role = 'provider' WHERE id = $1",
        user["id"], body.display_name, ident["phone"])
    return {"ok": True, "approval_status": row["approval_status"]}


@router.get("/providers/top")
async def top_providers():
    rows = await db.get_pool().fetch(
        """SELECT u.display_name, p.bio, p.rating_avg, p.rating_count, p.jobs_done,
                  p.verified, t.name AS tambon_name
             FROM providers p
             JOIN users u ON u.id = p.user_id
             LEFT JOIN tambons t ON t.id = u.tambon_id
            WHERE p.active AND p.approval_status = 'approved'
            ORDER BY p.rating_avg DESC, p.jobs_done DESC LIMIT 5""")
    return [dict(r) for r in rows]


# ── อัปโหลดไฟล์ (รูป/เสียง) ─────────────────────────────

@router.post("/uploads", status_code=201)
async def upload_file(file: UploadFile = File(...), secure: bool = False,
                      user: dict = Depends(current_user)):
    """secure=true → เอกสารยืนยันตัวตน เก็บในห้องนิรภัย เปิดดูได้เฉพาะแอดมินกับเจ้าตัว
    ปกติ → รูปหน้างาน/เสียง ที่ลูกค้าและช่างต้องเห็นกัน"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"ไม่รองรับไฟล์ชนิด {ext or '(ไม่มีนามสกุล)'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "ไฟล์ใหญ่เกิน 10 MB")
    if secure:
        return {"url": vault.save(data, ext)}
    name = f"{uuid.uuid4().hex}{ext}"
    UPLOAD_DIR.mkdir(exist_ok=True)
    (UPLOAD_DIR / name).write_bytes(data)
    return {"url": f"/uploads/{name}"}


@router.get("/secure-file/{name}")
async def secure_file(name: str, user: dict = Depends(current_user)):
    """เอกสารยืนยันตัวตน — เจ้าตัวดูของตัวเองได้ (แอดมินดูผ่าน /api/admin/secure-file)"""
    path = vault.resolve(name)
    if not path:
        raise HTTPException(404, "ไม่พบไฟล์นี้")
    owner = await db.get_pool().fetchval(
        f"""SELECT count(*) FROM providers
             WHERE user_id = $1 AND ({' OR '.join(f'{c} = $2' for c in vault.SECRET_COLUMNS)}
                   OR $2 = ANY(face_scan_urls))""",
        user["id"], f"{vault.URL_PREFIX}{name}")
    if not owner:
        raise HTTPException(403, "ไม่มีสิทธิ์ดูไฟล์นี้")
    return FileResponse(path)


# ── สร้างงาน ────────────────────────────────────────────

class JobIn(BaseModel):
    category_slug: str
    subcategory_slug: str | None = None   # งานด่วน 24 ชม. = ต้องบอกว่าด่วนแบบไหน
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
    sub = None
    if body.subcategory_slug:
        sub = await pool.fetchrow(
            "SELECT * FROM service_subcategories WHERE slug = $1 AND category_id = $2",
            body.subcategory_slug, cat["id"])
        if not sub:
            raise HTTPException(400, "ไม่รู้จักประเภทงานย่อยนี้")
    elif subcategories_of(body.category_slug):
        raise HTTPException(400, "หมวดนี้ต้องเลือกประเภทงานด้วยครับ")
    job = await pool.fetchrow(
        """INSERT INTO jobs (customer_id, category_id, subcategory_id, tambon_id, title, description,
             photos, voice_note_url, budget_min, budget_max, preferred_date,
             preferred_time, address_full, status, expires_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'bidding', now() + interval '72 hours')
           RETURNING *""",
        user["id"], cat["id"], sub["id"] if sub else None, body.tambon_id, body.title,
        body.description, body.photos, body.voice_note_url, body.budget_min, body.budget_max,
        body.preferred_date, body.preferred_time, body.address_full,
    )
    await broadcast_job(dict(job), cat["name_th"], sub["name_th"] if sub else None)
    return {"job_id": str(job["id"]), "status": job["status"]}


async def broadcast_job(job: dict, category_name: str, sub_name: str | None = None) -> None:
    """แจ้งเตือนงานใหม่ (ปิดข้อมูลลูกค้า):
    1) push ตรงถึงช่างทุกคนที่รับหมวด+ตำบลนี้ — ทำงานทันที ไม่ต้องตั้งกลุ่ม
    2) ส่งเข้ากลุ่มไลน์ช่างประจำตำบล ถ้ามีลงทะเบียนไว้"""
    pool = db.get_pool()
    tambon = await pool.fetchrow("SELECT name FROM tambons WHERE id = $1", job["tambon_id"])
    card = flex.job_card(
        {**job, "id": str(job["id"])}, category_name, tambon["name"] if tambon else "-",
        sub_name=sub_name)

    # 1) ช่างที่รับหมวดนี้และครอบคลุมตำบลนี้ (ไม่ส่งหาเจ้าของงานเอง เผื่อช่างประกาศงาน)
    #    งานที่มีประเภทย่อย (งานด่วน) — ส่งเฉพาะช่างที่รับประเภทนั้น
    #    ช่างที่ยังไม่ได้เลือกประเภทย่อยเลย ถือว่ารับทุกประเภทในหมวด (ข้อมูลเก่า)
    providers = await pool.fetch(
        """SELECT DISTINCT u.line_user_id
             FROM providers p JOIN users u ON u.id = p.user_id
            WHERE p.active AND p.approval_status = 'approved'
              AND $1 = ANY(p.categories)
              AND $2 = ANY(p.tambon_coverage)
              AND u.id <> $3
              AND ($4::int IS NULL OR p.subcategories = '{}' OR $4 = ANY(p.subcategories))
              AND u.line_user_id NOT LIKE 'Udemo-%' AND u.line_user_id NOT LIKE 'Utest-%'""",
        job["category_id"], job["tambon_id"], job["customer_id"], job.get("subcategory_id"))
    for r in providers:
        try:
            await line_api.push(r["line_user_id"], [card])
        except Exception:
            log.warning("แจ้งเตือนช่าง %s ไม่สำเร็จ", r["line_user_id"])

    # 2) กลุ่มไลน์ช่างแยกตามหมวดงาน (นำร่อง 4 หมวด = 4 กลุ่ม)
    cgroup = await pool.fetchrow(
        "SELECT group_id FROM category_line_groups WHERE category_id = $1 AND active",
        job["category_id"])
    if cgroup:
        try:
            await line_api.push(cgroup["group_id"], [card])
        except Exception:
            log.warning("ส่งเข้ากลุ่มหมวด %s ไม่สำเร็จ", job["category_id"])

    # 3) กลุ่มไลน์ช่างประจำตำบล (ถ้ามี)
    group = await pool.fetchrow(
        "SELECT group_id FROM tambon_line_groups WHERE tambon_id = $1 AND active", job["tambon_id"])
    if group:
        try:
            await line_api.push(group["group_id"], [card])
        except Exception:
            log.warning("ส่งเข้ากลุ่มตำบล %s ไม่สำเร็จ", job["tambon_id"])


# ── เสนอราคา ────────────────────────────────────────────

class BidIn(BaseModel):
    price: Decimal = Field(gt=0)
    message: str | None = None
    available_at: str | None = None


@router.post("/jobs/{job_id}/bids", status_code=201)
async def create_bid(job_id: str, body: BidIn, user: dict = Depends(current_user)):
    pool = db.get_pool()
    provider = await pool.fetchrow("SELECT * FROM providers WHERE user_id = $1 AND active AND approval_status = 'approved'",
        user["id"])
    if not provider:
        raise HTTPException(403, "ต้องลงทะเบียนเป็นช่างก่อนจึงเสนอราคาได้")
    job = await pool.fetchrow("SELECT * FROM jobs WHERE id = $1::uuid", job_id)
    if not job or job["status"] not in ("open", "bidding"):
        raise HTTPException(400, "งานนี้ปิดรับข้อเสนอแล้ว")
    # ข้อความเสนอราคาลูกค้าอ่านก่อนเลือกจ้าง — เป็นช่องหลักที่จะแอบทิ้งเบอร์ไว้
    if kind := contact_guard.find_contact_leak(body.message):
        raise HTTPException(400, contact_guard.message(kind, "ข้อความเสนอราคา"))
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
        """SELECT j.id, j.title, j.status, j.created_at,
                  COALESCE(s.icon, c.icon) AS icon,
                  COALESCE(s.name_th, c.name_th) AS category_name,
                  t.name AS tambon_name,
                  (SELECT count(*) FROM bids b WHERE b.job_id = j.id AND b.status = 'active') AS bids_count
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             LEFT JOIN service_subcategories s ON s.id = j.subcategory_id
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
        "SELECT * FROM providers WHERE user_id = $1 AND active AND approval_status = 'approved'",
        user["id"])
    if not prov:
        raise HTTPException(403, "ต้องลงทะเบียนเป็นช่างก่อน")
    open_jobs = await pool.fetch(
        """SELECT j.id, j.title, j.description, j.photos, j.voice_note_url,
                  j.budget_min, j.budget_max, j.preferred_time, j.created_at,
                  COALESCE(s.icon, c.icon) AS icon,
                  COALESCE(s.name_th, c.name_th) AS category_name,
                  t.name AS tambon_name,
                  (SELECT b.price FROM bids b
                    WHERE b.job_id = j.id AND b.provider_id = $1 AND b.status = 'active') AS my_price
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             LEFT JOIN service_subcategories s ON s.id = j.subcategory_id
             JOIN tambons t ON t.id = j.tambon_id
            WHERE j.status = 'bidding'
              AND j.tambon_id = ANY($2) AND j.category_id = ANY($3)
              -- งานที่มีประเภทย่อย: เห็นเฉพาะประเภทที่ช่างรับ (ยังไม่เลือก = เห็นทุกประเภท)
              AND (j.subcategory_id IS NULL OR $4::int[] = '{}'
                   OR j.subcategory_id = ANY($4))
            ORDER BY j.created_at DESC LIMIT 20""",
        prov["id"], prov["tambon_coverage"], prov["categories"], prov["subcategories"] or [],
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
        """SELECT j.*, c.name_th AS category_name,
                  COALESCE(s.icon, c.icon) AS icon, s.name_th AS sub_name,
                  t.name AS tambon_name
             FROM jobs j
             JOIN service_categories c ON c.id = j.category_id
             LEFT JOIN service_subcategories s ON s.id = j.subcategory_id
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
        "category_name": job["sub_name"] or job["category_name"], "icon": job["icon"],
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
