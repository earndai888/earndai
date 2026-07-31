"""สร้างงานให้จบในแชท LINE — เก็บข้อมูลทีละขั้น แล้วประกาศหาช่างจากแชทเลย

ขั้นตอน: หมวด → ตำบล → รูป → งบ → รายละเอียด → ยืนยันประกาศ
ทำงานแม้ Gemini ปิด (ไม่ต้องเปิดเว็บฟอร์ม)
"""
import json
import logging
import re
import uuid
from pathlib import Path

from . import db, flex, line_api
from .config import settings
from .intent import CATEGORY_NAMES, SUBCATEGORIES

log = logging.getLogger("chat_job")

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
MAX_PHOTOS = 5
DONE_WORDS = {"พอแล้ว", "พอ", "เสร็จ", "ครบแล้ว", "ไม่มีรูป", "ไม่มี", "ข้าม", "ต่อ", "next"}
SKIP_WORDS = {"ไม่มี", "ข้าม", "ไม่ระบุ", "แล้วแต่", "แล้วแต่ช่าง", "-"}


async def ensure_table() -> None:
    await db.get_pool().execute(
        """CREATE TABLE IF NOT EXISTS chat_draft (
             line_user_id text PRIMARY KEY,
             draft        jsonb NOT NULL DEFAULT '{}',
             updated_at   timestamptz NOT NULL DEFAULT now()
           )""")


async def get_draft(line_user_id: str) -> dict | None:
    row = await db.get_pool().fetchrow(
        """SELECT draft FROM chat_draft
            WHERE line_user_id = $1 AND updated_at > now() - interval '60 minutes'""",
        line_user_id)
    return json.loads(row["draft"]) if row else None


async def _save(line_user_id: str, draft: dict) -> None:
    await db.get_pool().execute(
        """INSERT INTO chat_draft (line_user_id, draft, updated_at) VALUES ($1, $2::jsonb, now())
           ON CONFLICT (line_user_id) DO UPDATE SET draft = $2::jsonb, updated_at = now()""",
        line_user_id, json.dumps(draft, ensure_ascii=False))


async def clear(line_user_id: str) -> None:
    await db.get_pool().execute("DELETE FROM chat_draft WHERE line_user_id = $1", line_user_id)


def _txt(s: str) -> dict:
    return {"type": "text", "text": s}


async def _ask_tambon(draft: dict) -> list[dict]:
    name = (SUBCATEGORIES.get(draft.get("subcategory_slug") or "") or {}).get("name") \
        or CATEGORY_NAMES.get(draft["category_slug"], "งานนี้")
    return [_txt(f"รับเรื่อง{name}แล้วครับ 😊\nพี่อยู่ตำบลไหนในอำเภอกันทรลักษ์ครับ? พิมพ์ชื่อตำบลได้เลย")]


async def start(line_user_id: str, category_slug: str, subcategory_slug: str | None,
                first_text: str) -> list[dict]:
    """เริ่มเก็บข้อมูลงานใหม่ (เรียกเมื่อจับหมวดได้)"""
    draft = {"step": "tambon", "category_slug": category_slug,
             "subcategory_slug": subcategory_slug, "photos": [], "first_text": first_text}
    await _save(line_user_id, draft)
    return await _ask_tambon(draft)


def _parse_budget(text: str) -> tuple[float | None, float | None]:
    # ไม่มีตัวเลข (เช่น "แล้วแต่ช่าง") = ไม่ระบุงบ
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return min(nums[0], nums[1]), max(nums[0], nums[1])
    return None, nums[0]


async def _match_tambon(text: str) -> dict | None:
    name = re.sub(r"^(ต\.?|ตำบล)\s*", "", text.strip())
    pool = db.get_pool()
    where = "amphoe = $2" if settings.pilot_amphoe else "TRUE"
    args = [f"%{name}%"] + ([settings.pilot_amphoe] if settings.pilot_amphoe else [])
    return await pool.fetchrow(
        f"SELECT id, name FROM tambons WHERE name ILIKE $1 AND {where} ORDER BY name LIMIT 1", *args)


async def _save_photo(content: bytes) -> str:
    UPLOAD_DIR.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    (UPLOAD_DIR / name).write_bytes(content)
    return f"/uploads/{name}"


def _summary(draft: dict) -> str:
    name = (SUBCATEGORIES.get(draft.get("subcategory_slug") or "") or {}).get("name") \
        or CATEGORY_NAMES.get(draft["category_slug"], "-")
    budget = "แล้วแต่ช่าง"
    if draft.get("budget_min") or draft.get("budget_max"):
        lo, hi = draft.get("budget_min"), draft.get("budget_max")
        budget = f"{int(lo):,}-{int(hi):,} บาท" if lo and hi else f"ไม่เกิน {int(hi):,} บาท"
    return ("สรุปงานที่จะประกาศนะครับ 📋\n"
            f"• งาน: {name}\n"
            f"• ตำบล: {draft.get('tambon_name', '-')}\n"
            f"• รูป: {len(draft.get('photos', []))} รูป\n"
            f"• งบ: {budget}\n"
            f"• รายละเอียด: {draft.get('description') or '-'}")


def _confirm_quick_reply() -> dict:
    return {"items": [
        {"type": "action", "action": {"type": "postback", "label": "✅ ประกาศหาช่างเลย",
         "data": "a=jobpost", "displayText": "ประกาศหาช่างเลย"}},
        {"type": "action", "action": {"type": "postback", "label": "❌ ยกเลิก",
         "data": "a=jobcancel", "displayText": "ยกเลิก"}},
    ]}


async def advance(user: dict, event: dict, draft: dict) -> list[dict]:
    """รับข้อความ/รูปในแต่ละขั้น → คืนข้อความตอบกลับ"""
    line_user_id = user["line_user_id"]
    msg = event.get("message", {})
    mtype = msg.get("type")
    text = msg.get("text", "").strip() if mtype == "text" else ""
    step = draft.get("step")

    if step == "tambon":
        if mtype != "text":
            return [_txt("พิมพ์ชื่อตำบลที่พี่อยู่มาได้เลยครับ")]
        tam = await _match_tambon(text)
        if not tam:
            return [_txt(f"หาตำบล \"{text}\" ในอำเภอกันทรลักษ์ไม่เจอครับ 🤔 ลองพิมพ์ชื่อตำบลอีกที")]
        draft.update(tambon_id=tam["id"], tambon_name=tam["name"], step="photos")
        await _save(line_user_id, draft)
        return [_txt(f"ต.{tam['name']} — ได้ครับ 👍\nส่งรูปหน้างานมาให้ช่างดูได้เลยครับ (ส่งได้หลายรูป)\n"
                     "ส่งครบแล้วพิมพ์ \"พอแล้ว\" (ถ้าไม่มีรูปพิมพ์ \"ไม่มีรูป\")")]

    if step == "photos":
        if mtype == "image":
            if len(draft["photos"]) >= MAX_PHOTOS:
                return [_txt(f"รับรูปครบ {MAX_PHOTOS} รูปแล้วครับ พิมพ์ \"พอแล้ว\" เพื่อไปต่อ")]
            content = await line_api.get_message_content(msg.get("id"))
            if not content:
                return [_txt("รับรูปไม่สำเร็จครับ ลองส่งใหม่อีกที หรือพิมพ์ \"ไม่มีรูป\" เพื่อข้าม")]
            draft["photos"].append(await _save_photo(content))
            await _save(line_user_id, draft)
            return [_txt(f"ได้รูปแล้วครับ ({len(draft['photos'])} รูป) 📸 ส่งเพิ่มได้ หรือพิมพ์ \"พอแล้ว\"")]
        if mtype == "text" and text in DONE_WORDS:
            draft["step"] = "budget"
            await _save(line_user_id, draft)
            return [_txt("งบประมาณที่พี่ไหวประมาณเท่าไหร่ครับ? (เช่น 300-500)\n"
                         "ถ้าอยากให้ช่างเสนอมาเอง พิมพ์ \"แล้วแต่ช่าง\" ได้ครับ")]
        return [_txt("ส่งรูปมาได้เลยครับ 📸 หรือพิมพ์ \"พอแล้ว\" เพื่อไปต่อ")]

    if step == "budget":
        if mtype != "text":
            return [_txt("พิมพ์งบประมาณที่ไหว หรือ \"แล้วแต่ช่าง\" ครับ")]
        lo, hi = _parse_budget(text)
        draft.update(budget_min=lo, budget_max=hi, step="details")
        await _save(line_user_id, draft)
        return [_txt("เล่ารายละเอียดงานเพิ่มอีกนิดครับ — อาการเป็นยังไง อยากให้ช่วยอะไรบ้าง")]

    if step == "details":
        if mtype != "text":
            return [_txt("พิมพ์รายละเอียดงานมาได้เลยครับ")]
        draft["description"] = text[:400]
        draft["step"] = "confirm"
        await _save(line_user_id, draft)
        return [{**_txt(_summary(draft) + "\n\nประกาศหาช่างเลยไหมครับ?\n"
                        "(กดประกาศถือว่ายอมรับนโยบายข้อมูลส่วนบุคคล PDPA)"),
                 "quickReply": _confirm_quick_reply()}]

    if step == "confirm":
        # รอผู้ใช้กดปุ่ม (postback) — ถ้าพิมพ์มาก็เตือน
        return [{**_txt("กดปุ่ม \"ประกาศหาช่างเลย\" หรือ \"ยกเลิก\" ด้านล่างครับ"),
                 "quickReply": _confirm_quick_reply()}]

    return [_txt("พิมพ์บอกงานที่ต้องการได้เลยครับ")]


async def post_job(user: dict, draft: dict) -> list[dict]:
    """ยืนยันประกาศ → สร้างงานจริง + แจ้งช่างในพื้นที่"""
    from .routers.jobs import do_create_job
    if draft.get("step") != "confirm" or not draft.get("tambon_id"):
        return [_txt("ยังกรอกข้อมูลไม่ครบครับ พิมพ์บอกงานใหม่ได้เลย")]
    name = (SUBCATEGORIES.get(draft.get("subcategory_slug") or "") or {}).get("name") \
        or CATEGORY_NAMES.get(draft["category_slug"], "งาน")
    desc = draft.get("description") or draft.get("first_text") or ""
    data = {
        "category_slug": draft["category_slug"],
        "subcategory_slug": draft.get("subcategory_slug"),
        "tambon_id": draft["tambon_id"],
        "title": name + (f" — {desc[:40]}" if desc else ""),
        "description": desc, "photos": draft.get("photos", []),
        "budget_min": draft.get("budget_min"), "budget_max": draft.get("budget_max"),
        "pdpa_consent": True,   # กดปุ่มประกาศ = ยินยอม
    }
    try:
        await do_create_job(db.get_pool(), user, data, min_photos=0)
    except Exception as e:
        detail = getattr(e, "detail", None) or "เกิดข้อผิดพลาด"
        log.warning("ประกาศงานจากแชทไม่สำเร็จ: %s", detail)
        return [_txt(f"ประกาศไม่สำเร็จครับ: {detail}\nพิมพ์ \"เริ่มใหม่\" เพื่อลองอีกครั้ง")]
    await clear(user["line_user_id"])
    return [_txt("ประกาศหาช่างให้แล้วครับ! 📣\n"
                 "ช่างในพื้นที่ของพี่จะทยอยเสนอราคาเข้ามา ผมจะส่งการ์ดให้พี่เลือกในแชทนี้เลยครับ 😊")]
