"""ระบบหลังบ้านแอดมิน — อนุมัติช่าง, ทะเบียนช่าง, กระดานงาน, การเงิน/escrow,
ข้อพิพาท, สถิติ KPI + export CSV

ป้องกันด้วย header X-Admin-Token เทียบกับ ADMIN_TOKEN ใน env
(ไม่ตั้ง ADMIN_TOKEN = ปิดหน้าแอดมินทั้งหมด)
"""
import csv
import io
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import db, line_api
from ..config import settings

router = APIRouter(prefix="/api/admin")
log = logging.getLogger("admin")


async def require_admin(x_admin_token: str = Header(default="")) -> bool:
    if not settings.admin_token:
        raise HTTPException(503, "ยังไม่ได้ตั้งค่า ADMIN_TOKEN — หน้าแอดมินถูกปิดอยู่")
    if x_admin_token != settings.admin_token:
        raise HTTPException(401, "รหัสแอดมินไม่ถูกต้อง")
    return True


Admin = Depends(require_admin)


async def notify(line_user_id: str | None, text: str) -> None:
    """แจ้งช่างทาง LINE (พังก็ไม่ให้ล้มทั้งคำสั่ง)"""
    if not line_user_id:
        return
    try:
        await line_api.push(line_user_id, [{"type": "text", "text": text}])
    except Exception:
        log.warning("แจ้งเตือน %s ไม่สำเร็จ", line_user_id)


# ══════════ 6. ภาพรวม / KPI ══════════

@router.get("/summary")
async def summary(_: bool = Admin):
    pool = db.get_pool()
    row = await pool.fetchrow("""
        SELECT
          (SELECT count(*) FROM providers WHERE approval_status='pending')            AS providers_pending,
          (SELECT count(*) FROM providers WHERE approval_status='approved' AND active) AS providers_active,
          (SELECT count(*) FROM providers WHERE NOT active)                            AS providers_suspended,
          (SELECT count(*) FROM jobs WHERE status='bidding')                           AS jobs_new,
          (SELECT count(*) FROM jobs WHERE status IN ('assigned','in_progress','done')) AS jobs_active,
          (SELECT count(*) FROM jobs WHERE status IN ('confirmed','settled'))          AS jobs_done,
          (SELECT count(*) FROM jobs WHERE status IN ('disputed','cancelled','expired')) AS jobs_problem,
          (SELECT COALESCE(sum(gross),0) FROM settlements)                             AS gmv,
          (SELECT COALESCE(sum(provider_net),0) FROM settlements)                      AS provider_income,
          (SELECT COALESCE(sum(platform_fee),0) FROM settlements)                      AS platform_fee,
          (SELECT COALESCE(sum(tax_withheld),0) FROM settlements)                      AS tax_withheld,
          (SELECT COALESCE(sum(amount),0) FROM community_fund_ledger)                  AS fund_total,
          (SELECT COALESCE(sum(p.amount),0) FROM payments p JOIN jobs j ON j.id=p.job_id
            WHERE p.status='paid' AND j.status IN ('assigned','in_progress','done','disputed')) AS escrow_held,
          (SELECT COALESCE(sum(provider_net),0) FROM settlements WHERE status='pending') AS payout_pending,
          (SELECT count(*) FROM disputes WHERE status='open')                          AS disputes_open,
          (SELECT COALESCE(round(avg(rating_avg)::numeric,2),0) FROM providers
            WHERE approval_status='approved' AND rating_count>0)                       AS avg_rating
    """)
    # เวลาตอบสนองงานฉุกเฉิน (นาที) — จากประกาศงาน → ช่างเสนอราคารายแรก
    emer = await pool.fetchval("""
        SELECT round(avg(EXTRACT(EPOCH FROM (b.first_bid - j.created_at))/60)::numeric, 1)
          FROM jobs j
          JOIN service_categories c ON c.id = j.category_id AND c.slug = 'emergency'
          JOIN (SELECT job_id, min(created_at) AS first_bid FROM bids GROUP BY job_id) b
            ON b.job_id = j.id
    """)
    # งานแยกตามตำบล (แทน heatmap)
    by_tambon = await pool.fetch("""
        SELECT t.name AS tambon, count(j.id) AS jobs,
               count(*) FILTER (WHERE j.status IN ('confirmed','settled')) AS done
          FROM tambons t LEFT JOIN jobs j ON j.tambon_id = t.id
         WHERE t.amphoe = $1 GROUP BY t.name HAVING count(j.id) > 0
         ORDER BY count(j.id) DESC""", settings.pilot_amphoe)
    by_category = await pool.fetch("""
        SELECT c.name_th AS category, c.icon, count(j.id) AS jobs
          FROM service_categories c LEFT JOIN jobs j ON j.category_id = c.id
         WHERE c.active GROUP BY c.name_th, c.icon, c.id ORDER BY c.id""")
    return dict(row) | {
        "emergency_response_min": float(emer) if emer is not None else None,
        "by_tambon": [dict(r) for r in by_tambon],
        "by_category": [dict(r) for r in by_category],
    }


# ══════════ 1-2. ช่าง: คิวอนุมัติ + ทะเบียน ══════════

@router.get("/providers")
async def list_providers(
    status: str = Query("pending"),
    category: str | None = None,
    tambon_id: int | None = None,
    q: str | None = None,
    _: bool = Admin,
):
    """status: pending | approved | rejected | info_requested | suspended | all"""
    sql = """
        SELECT p.id, p.approval_status, p.tier, p.skill_tags, p.active, p.verified,
               p.bio, p.promptpay_id, p.rating_avg, p.rating_count, p.jobs_done,
               p.id_card_url, p.selfie_url, p.license_url, p.admin_note,
               p.created_at, p.reviewed_at, p.categories, p.tambon_coverage,
               u.line_user_id, u.display_name, u.phone,
               (SELECT array_agg(c.name_th ORDER BY c.id) FROM service_categories c
                 WHERE c.id = ANY(p.categories)) AS category_names,
               (SELECT array_agg(t.name ORDER BY t.name) FROM tambons t
                 WHERE t.id = ANY(p.tambon_coverage)) AS tambon_names
          FROM providers p JOIN users u ON u.id = p.user_id
         WHERE TRUE
    """
    args: list = []
    if status == "suspended":
        sql += " AND NOT p.active"
    elif status != "all":
        args.append(status)
        sql += f" AND p.approval_status = ${len(args)}"
    if category:
        args.append(category)
        sql += (f" AND EXISTS (SELECT 1 FROM service_categories c"
                f" WHERE c.id = ANY(p.categories) AND c.slug = ${len(args)})")
    if tambon_id:
        args.append(tambon_id)
        sql += f" AND ${len(args)} = ANY(p.tambon_coverage)"
    if q:
        args.append(f"%{q}%")
        sql += f" AND (u.display_name ILIKE ${len(args)} OR u.phone ILIKE ${len(args)})"
    sql += " ORDER BY p.created_at DESC LIMIT 200"
    rows = await db.get_pool().fetch(sql, *args)
    return [dict(r) | {"id": str(r["id"]), "created_at": r["created_at"].isoformat()}
            for r in rows]


class ApproveIn(BaseModel):
    category_slugs: list[str] | None = None      # อนุมัติเฉพาะหมวดที่อนุญาต
    tier: int = Field(default=1, ge=1, le=3)
    skill_tags: list[str] = []
    verified: bool = False
    admin_note: str | None = None


@router.post("/providers/{provider_id}/approve")
async def approve_provider(provider_id: str, body: ApproveIn, _: bool = Admin):
    pool = db.get_pool()
    prov = await pool.fetchrow(
        """SELECT p.*, u.line_user_id FROM providers p JOIN users u ON u.id=p.user_id
            WHERE p.id = $1::uuid""", provider_id)
    if not prov:
        raise HTTPException(404, "ไม่พบช่างรายนี้")

    cats = prov["categories"]
    if body.category_slugs:
        rows = await pool.fetch(
            "SELECT id FROM service_categories WHERE slug = ANY($1::text[]) AND active",
            body.category_slugs)
        if not rows:
            raise HTTPException(400, "ไม่พบหมวดงานที่เลือก")
        cats = [r["id"] for r in rows]

    await pool.execute(
        """UPDATE providers SET approval_status='approved', active=true, categories=$2,
               tier=$3, skill_tags=$4, verified=$5, admin_note=$6, reviewed_at=now()
            WHERE id = $1::uuid""",
        provider_id, cats, body.tier, body.skill_tags, body.verified, body.admin_note)

    names = await pool.fetch(
        "SELECT name_th FROM service_categories WHERE id = ANY($1::int[])", cats)
    cat_txt = ", ".join(r["name_th"] for r in names)
    links = await pool.fetch(
        """SELECT c.name_th, g.openchat_url FROM category_line_groups g
             JOIN service_categories c ON c.id = g.category_id
            WHERE g.category_id = ANY($1::int[]) AND g.active
              AND g.openchat_url IS NOT NULL""", cats)
    link_txt = "".join(f"\n• {r['name_th']}: {r['openchat_url']}" for r in links)
    await notify(prov["line_user_id"],
                 f"🎉 ยินดีด้วยครับ! เอิ้นได้อนุมัติให้คุณเป็นช่างแล้ว\n"
                 f"หมวดที่รับงานได้: {cat_txt}\n"
                 f"ระดับ: Level {body.tier}\n\n"
                 f"เปิดหน้าช่างเพื่อรับงานได้เลยครับ"
                 + (f"\n\nเข้ากลุ่มช่างประจำหมวด:{link_txt}" if link_txt else ""))
    return {"ok": True}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/providers/{provider_id}/reject")
async def reject_provider(provider_id: str, body: RejectIn, _: bool = Admin):
    pool = db.get_pool()
    prov = await pool.fetchrow(
        """UPDATE providers SET approval_status='rejected', active=false,
               admin_note=$2, reviewed_at=now()
            WHERE id = $1::uuid
        RETURNING (SELECT line_user_id FROM users u WHERE u.id = providers.user_id) AS line_user_id""",
        provider_id, body.reason)
    if not prov:
        raise HTTPException(404, "ไม่พบช่างรายนี้")
    await notify(prov["line_user_id"],
                 f"ขออภัยครับ ใบสมัครช่างของคุณยังไม่ผ่านการอนุมัติ\n"
                 f"เหตุผล: {body.reason}\n\nแก้ไขแล้วสมัครใหม่ได้ตลอดนะครับ")
    return {"ok": True}


@router.post("/providers/{provider_id}/request-info")
async def request_info(provider_id: str, body: RejectIn, _: bool = Admin):
    pool = db.get_pool()
    prov = await pool.fetchrow(
        """UPDATE providers SET approval_status='info_requested', admin_note=$2,
               reviewed_at=now()
            WHERE id = $1::uuid
        RETURNING (SELECT line_user_id FROM users u WHERE u.id = providers.user_id) AS line_user_id""",
        provider_id, body.reason)
    if not prov:
        raise HTTPException(404, "ไม่พบช่างรายนี้")
    await notify(prov["line_user_id"],
                 f"📄 เอิ้นได้ขอเอกสาร/ข้อมูลเพิ่มเติมครับ\n{body.reason}\n\n"
                 f"เปิดหน้าช่าง → เมนู 'ข้อมูลช่าง' เพื่ออัปโหลดเพิ่มได้เลยครับ")
    return {"ok": True}


class SuspendIn(BaseModel):
    active: bool
    reason: str | None = None


@router.post("/providers/{provider_id}/suspend")
async def suspend_provider(provider_id: str, body: SuspendIn, _: bool = Admin):
    pool = db.get_pool()
    prov = await pool.fetchrow(
        """UPDATE providers SET active = $2, admin_note = COALESCE($3, admin_note)
            WHERE id = $1::uuid
        RETURNING (SELECT line_user_id FROM users u WHERE u.id = providers.user_id) AS line_user_id""",
        provider_id, body.active, body.reason)
    if not prov:
        raise HTTPException(404, "ไม่พบช่างรายนี้")
    await notify(prov["line_user_id"],
                 "✅ เปิดรับงานให้แล้วครับ" if body.active
                 else f"⛔ ระงับการรับงานชั่วคราวครับ\n{body.reason or ''}")
    return {"ok": True}


class TierIn(BaseModel):
    tier: int = Field(ge=1, le=3)
    skill_tags: list[str] | None = None


@router.post("/providers/{provider_id}/tier")
async def set_tier(provider_id: str, body: TierIn, _: bool = Admin):
    await db.get_pool().execute(
        """UPDATE providers SET tier=$2,
               skill_tags = COALESCE($3, skill_tags),
               verified = ($2 >= 2)
            WHERE id = $1::uuid""",
        provider_id, body.tier, body.skill_tags)
    return {"ok": True}


# ══════════ 3. กระดานงาน 4 แท็บ ══════════

TAB_STATUS = {
    "new":     ("bidding",),
    "active":  ("assigned", "in_progress", "done"),
    "done":    ("confirmed", "settled"),
    "problem": ("disputed", "cancelled", "expired"),
}


@router.get("/jobs")
async def list_jobs(tab: str = Query("new"), _: bool = Admin):
    statuses = TAB_STATUS.get(tab)
    if not statuses:
        raise HTTPException(400, "tab ต้องเป็น new | active | done | problem")
    rows = await db.get_pool().fetch("""
        SELECT j.id, j.title, j.status, j.description, j.photos, j.voice_note_url,
               j.budget_min, j.budget_max, j.preferred_time, j.created_at, j.start_otp,
               j.otp_verified_at,
               c.name_th AS category, c.icon, t.name AS tambon,
               cu.display_name AS customer_name, cu.phone AS customer_phone,
               pu.display_name AS provider_name, pu.phone AS provider_phone,
               b.price,
               EXTRACT(EPOCH FROM (now() - j.created_at))/60 AS age_min,
               (SELECT count(*) FROM bids x WHERE x.job_id = j.id AND x.status='active') AS bids_count,
               pay.status AS payment_status, pay.amount AS payment_amount,
               s.provider_net, s.platform_fee, s.fund_amount, s.tax_withheld, s.status AS settle_status,
               r.rating, r.comment,
               (SELECT d.id::text FROM disputes d WHERE d.job_id=j.id AND d.status='open' LIMIT 1) AS dispute_id
          FROM jobs j
          JOIN service_categories c ON c.id = j.category_id
          JOIN tambons t ON t.id = j.tambon_id
          JOIN users cu ON cu.id = j.customer_id
          LEFT JOIN bids b ON b.id = j.assigned_bid_id
          LEFT JOIN providers p ON p.id = b.provider_id
          LEFT JOIN users pu ON pu.id = p.user_id
          LEFT JOIN LATERAL (SELECT status, amount FROM payments
                              WHERE job_id=j.id ORDER BY created_at DESC LIMIT 1) pay ON TRUE
          LEFT JOIN settlements s ON s.job_id = j.id
          LEFT JOIN reviews r ON r.job_id = j.id
         WHERE j.status = ANY($1::text[])
         ORDER BY j.created_at DESC LIMIT 200
    """, list(statuses))
    return [dict(r) | {"id": str(r["id"]), "created_at": r["created_at"].isoformat()}
            for r in rows]


# ══════════ 4. การเงิน / escrow / payout ══════════

@router.get("/finance")
async def finance(_: bool = Admin):
    pool = db.get_pool()
    escrow = await pool.fetch("""
        SELECT j.id, j.title, p.amount, p.status, j.status AS job_status,
               t.name AS tambon, p.paid_at
          FROM payments p JOIN jobs j ON j.id = p.job_id
          JOIN tambons t ON t.id = j.tambon_id
         WHERE p.status = 'paid' AND j.status IN ('assigned','in_progress','done','disputed')
         ORDER BY p.paid_at DESC LIMIT 100""")
    payouts = await pool.fetch("""
        SELECT s.id, s.gross, s.provider_net, s.platform_fee, s.fund_amount,
               s.tax_withheld, s.status, s.created_at,
               j.title, u.display_name AS provider_name, pr.promptpay_id
          FROM settlements s
          JOIN jobs j ON j.id = s.job_id
          LEFT JOIN bids b ON b.id = j.assigned_bid_id
          LEFT JOIN providers pr ON pr.id = b.provider_id
          LEFT JOIN users u ON u.id = pr.user_id
         ORDER BY s.created_at DESC LIMIT 100""")
    fund = await pool.fetch("""
        SELECT f.amount, f.note, f.created_at, t.name AS tambon
          FROM community_fund_ledger f JOIN tambons t ON t.id = f.tambon_id
         ORDER BY f.created_at DESC LIMIT 100""")
    return {
        "escrow": [dict(r) | {"id": str(r["id"]),
                              "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None}
                   for r in escrow],
        "payouts": [dict(r) | {"id": str(r["id"]), "created_at": r["created_at"].isoformat()}
                    for r in payouts],
        "fund": [dict(r) | {"created_at": r["created_at"].isoformat()} for r in fund],
    }


@router.post("/settlements/{settlement_id}/mark-transferred")
async def mark_transferred(settlement_id: str, _: bool = Admin):
    """แอดมินโอนเงินเข้าบัญชีช่างแล้ว → ปิดรายการ (MVP: บันทึกเอง ยังไม่ต่อ bank API)"""
    row = await db.get_pool().fetchrow(
        """UPDATE settlements SET status='transferred', transferred_at=now()
            WHERE id=$1::uuid AND status <> 'transferred' RETURNING job_id""",
        settlement_id)
    if not row:
        raise HTTPException(400, "ไม่พบรายการ หรือโอนไปแล้ว")
    await db.get_pool().execute(
        "UPDATE jobs SET status='settled' WHERE id=$1 AND status='confirmed'", row["job_id"])
    return {"ok": True}


# ══════════ 5. ข้อพิพาท ══════════

class DisputeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/jobs/{job_id}/hold")
async def hold_job(job_id: str, body: DisputeIn, _: bool = Admin):
    """อายัดเงิน + เปิดเคสข้อพิพาท"""
    pool = db.get_pool()
    job = await pool.fetchrow("SELECT id, status FROM jobs WHERE id=$1::uuid", job_id)
    if not job:
        raise HTTPException(404, "ไม่พบงานนี้")
    await pool.execute("UPDATE jobs SET status='disputed' WHERE id=$1::uuid", job_id)
    row = await pool.fetchrow(
        "INSERT INTO disputes (job_id, reason) VALUES ($1::uuid, $2) RETURNING id",
        job_id, body.reason)
    return {"dispute_id": str(row["id"])}


class ResolveIn(BaseModel):
    action: str = Field(pattern="^(release|refund|fund_compensate)$")
    note: str | None = None


@router.post("/disputes/{dispute_id}/resolve")
async def resolve_dispute(dispute_id: str, body: ResolveIn, _: bool = Admin):
    from .jobs import create_settlement

    pool = db.get_pool()
    d = await pool.fetchrow("SELECT * FROM disputes WHERE id=$1::uuid", dispute_id)
    if not d or d["status"] == "resolved":
        raise HTTPException(400, "ไม่พบเคส หรือปิดเคสไปแล้ว")
    job_id = d["job_id"]

    if body.action == "release":            # งานถูกต้อง → ปล่อยเงินให้ช่าง
        await pool.execute("UPDATE jobs SET status='confirmed' WHERE id=$1", job_id)
        await create_settlement(job_id)
    elif body.action == "refund":           # ช่างผิด → คืนเงินลูกค้า
        await pool.execute(
            "UPDATE payments SET status='refunded' WHERE job_id=$1 AND status='paid'", job_id)
        await pool.execute("UPDATE jobs SET status='cancelled' WHERE id=$1", job_id)
    else:                                    # ชดเชยจากกองทุนชุมชน 2%
        job = await pool.fetchrow("SELECT tambon_id FROM jobs WHERE id=$1", job_id)
        amount = await pool.fetchval(
            "SELECT amount FROM payments WHERE job_id=$1 ORDER BY created_at DESC LIMIT 1", job_id)
        await pool.execute(
            """INSERT INTO community_fund_ledger (tambon_id, job_id, amount, note)
               VALUES ($1,$2,$3,'ชดเชยความเสียหายจากกองทุนชุมชน')""",
            job["tambon_id"], job_id, -(amount or 0))
        await pool.execute("UPDATE jobs SET status='cancelled' WHERE id=$1", job_id)

    await pool.execute(
        """UPDATE disputes SET status='resolved', resolution=$2, admin_note=$3,
               resolved_at=now() WHERE id=$1::uuid""",
        dispute_id, body.action, body.note)
    return {"ok": True}


@router.get("/disputes")
async def list_disputes(status: str = "open", _: bool = Admin):
    rows = await db.get_pool().fetch("""
        SELECT d.id, d.reason, d.status, d.resolution, d.admin_note,
               d.created_at, d.resolved_at,
               j.id AS job_id, j.title, j.photos, j.voice_note_url, j.otp_verified_at,
               t.name AS tambon, cu.display_name AS customer_name,
               pu.display_name AS provider_name,
               (SELECT amount FROM payments WHERE job_id=j.id ORDER BY created_at DESC LIMIT 1) AS amount
          FROM disputes d
          JOIN jobs j ON j.id = d.job_id
          JOIN tambons t ON t.id = j.tambon_id
          JOIN users cu ON cu.id = j.customer_id
          LEFT JOIN bids b ON b.id = j.assigned_bid_id
          LEFT JOIN providers p ON p.id = b.provider_id
          LEFT JOIN users pu ON pu.id = p.user_id
         WHERE ($1 = 'all' OR d.status = $1)
         ORDER BY d.created_at DESC LIMIT 100""", status)
    return [dict(r) | {"id": str(r["id"]), "job_id": str(r["job_id"]),
                       "created_at": r["created_at"].isoformat()} for r in rows]


# ══════════ 6. Export CSV ══════════

def _csv(rows: list[dict], filename: str) -> Response:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    # BOM ให้ Excel อ่านภาษาไทยถูก
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export")
async def export_csv(type: str = Query("jobs"), _: bool = Admin):
    pool = db.get_pool()
    if type == "jobs":
        rows = await pool.fetch("""
            SELECT j.id::text, j.created_at, c.name_th AS หมวดงาน, t.name AS ตำบล,
                   j.title AS ชื่องาน, j.status AS สถานะ,
                   b.price AS ราคาที่ตกลง, cu.display_name AS ลูกค้า,
                   pu.display_name AS ช่าง, r.rating AS คะแนนรีวิว
              FROM jobs j
              JOIN service_categories c ON c.id=j.category_id
              JOIN tambons t ON t.id=j.tambon_id
              JOIN users cu ON cu.id=j.customer_id
              LEFT JOIN bids b ON b.id=j.assigned_bid_id
              LEFT JOIN providers p ON p.id=b.provider_id
              LEFT JOIN users pu ON pu.id=p.user_id
              LEFT JOIN reviews r ON r.job_id=j.id
             ORDER BY j.created_at DESC""")
        name = "jobs.csv"
    elif type == "settlements":
        rows = await pool.fetch("""
            SELECT s.created_at, j.title AS งาน, u.display_name AS ช่าง,
                   pr.promptpay_id AS พร้อมเพย์, s.gross AS ยอดงาน,
                   s.provider_net AS ช่างได้รับ, s.platform_fee AS ค่าระบบ,
                   s.fund_amount AS กองทุนชุมชน, s.tax_withheld AS ภาษีหัก_ณ_ที่จ่าย,
                   s.status AS สถานะโอน
              FROM settlements s JOIN jobs j ON j.id=s.job_id
              LEFT JOIN bids b ON b.id=j.assigned_bid_id
              LEFT JOIN providers pr ON pr.id=b.provider_id
              LEFT JOIN users u ON u.id=pr.user_id
             ORDER BY s.created_at DESC""")
        name = "settlements-tax.csv"
    elif type == "fund":
        rows = await pool.fetch("""
            SELECT f.created_at, t.name AS ตำบล, f.amount AS จำนวนเงิน, f.note AS หมายเหตุ
              FROM community_fund_ledger f JOIN tambons t ON t.id=f.tambon_id
             ORDER BY f.created_at DESC""")
        name = "community-fund.csv"
    elif type == "providers":
        rows = await pool.fetch("""
            SELECT u.display_name AS ชื่อช่าง, u.phone AS เบอร์โทร,
                   p.approval_status AS สถานะอนุมัติ, p.tier AS ระดับ,
                   p.rating_avg AS คะแนน, p.jobs_done AS งานสำเร็จ,
                   p.created_at AS วันสมัคร
              FROM providers p JOIN users u ON u.id=p.user_id
             ORDER BY p.created_at DESC""")
        name = "providers.csv"
    else:
        raise HTTPException(400, "type ต้องเป็น jobs | settlements | fund | providers")
    return _csv([dict(r) for r in rows], name)
