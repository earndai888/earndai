"""LINE webhook: รับข้อความ → intent ชั้น 1 → ตอบปุ่มเปิดฟอร์ม หรือ quick reply"""
import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, Header, HTTPException, Request

from .. import ai_chat, db, flex, line_api
from ..intent import classify

router = APIRouter()
log = logging.getLogger("webhook")


@router.post("/webhook/line")
async def line_webhook(request: Request, x_line_signature: str = Header(default="")):
    body = await request.body()
    if not line_api.verify_signature(body, x_line_signature):
        raise HTTPException(403, "ลายเซ็นไม่ถูกต้อง")
    payload = await request.json()

    for event in payload.get("events", []):
        try:
            await handle_event(event)
        except Exception:  # ห้ามให้ event เดียวพัง ทำให้ LINE retry ทั้งก้อน
            log.exception("จัดการ event ล้มเหลว: %s", event.get("type"))
    return {"ok": True}


async def handle_event(event: dict) -> None:
    etype = event.get("type")
    reply_token = event.get("replyToken")
    src = event.get("source", {})

    if etype == "follow":
        await upsert_user(src.get("userId"))
        await line_api.reply(reply_token, [
            {"type": "text",
             "text": "สวัสดีครับพี่ 😊 ผมน้องเอิ้นได้ครับ\nยินดีต้อนรับสู่ \"เอิ้นได้\" — คนศรีสะเกษช่วยคนศรีสะเกษ\n\nพี่อยากให้ช่วยเรื่องอะไร พิมพ์บอกผมได้เลยครับ เช่น\n• \"แอร์ไม่เย็น\"\n• \"หาช่างตัดหญ้า\"\n• \"หาแม่บ้านทำความสะอาด\"\n\nเดี๋ยวผมช่วยหาช่างในพื้นที่ของพี่ที่ผ่านการตรวจสอบให้ครับ"},
        ])
        return

    if etype == "postback":
        data = dict(parse_qsl(event.get("postback", {}).get("data", "")))
        if slug := data.get("category"):
            await line_api.reply(reply_token, [flex.open_form_message(slug)])
        return

    # บอทถูกเชิญเข้ากลุ่ม/ห้อง → แนะนำวิธีผูกหมวดงาน
    if etype == "join":
        await line_api.reply(reply_token, [{
            "type": "text",
            "text": "สวัสดีครับ 🙌 นี่คือบอทเอิ้นได้\n\nตั้งให้กลุ่มนี้เป็นกลุ่มช่างของหมวดงาน — พิมพ์:\nผูกหมวด ช่างแอร์\n(หรือ งานสวน / แม่บ้าน / ฉุกเฉิน)\n\nงานใหม่ในหมวดนี้จะแจ้งเข้ากลุ่มอัตโนมัติ\nเลิกรับแจ้งเตือน พิมพ์: เลิกผูก"}])
        return

    if etype == "message" and event["message"].get("type") == "text":
        text = event["message"]["text"].strip()

        # ในกลุ่ม/ห้อง: รับเฉพาะคำสั่งผูก/เลิกผูกตำบล
        if src.get("type") in ("group", "room"):
            gid = src.get("groupId") or src.get("roomId")
            await handle_group_command(reply_token, gid, text)
            return

        user_id = src.get("userId")
        await upsert_user(user_id)
        text = event["message"]["text"]

        # AI ชั้นที่ 2: คุยโต้ตอบก่อน ค่อยส่งลิงก์เมื่อคุยรู้เรื่องแล้ว
        if ai_chat.enabled() and user_id:
            await line_api.show_loading(user_id)
            ai = await ai_chat.chat(user_id, text)
            if ai:
                messages: list[dict] = []
                if ai["text"]:
                    messages.append({"type": "text", "text": ai["text"]})
                if ai["form"]:
                    # ส่งปุ่มพร้อมข้อมูลที่คุยไว้ → หน้าเว็บกรอกให้อัตโนมัติ
                    messages.append(flex.open_form_message(**ai["form"]))
                await line_api.reply(reply_token, messages)
                return

        # ชั้นที่ 1 (fallback): keyword matching
        result = classify(text)
        if result.confident:
            await line_api.reply(reply_token, [flex.open_form_message(result.slug)])
        else:
            await line_api.reply(reply_token, [flex.category_quick_reply()])


async def handle_group_command(reply_token: str, group_id: str | None, text: str) -> None:
    """ผูก/เลิกผูกกลุ่มไลน์กับหมวดงาน (หรือตำบล) เพื่อรับแจ้งเตือนงานใหม่"""
    if not group_id:
        return
    pool = db.get_pool()

    if text.startswith("เลิกผูก"):
        await pool.execute(
            "UPDATE category_line_groups SET active = false WHERE group_id = $1", group_id)
        await pool.execute(
            "UPDATE tambon_line_groups SET active = false WHERE group_id = $1", group_id)
        await line_api.reply(reply_token, [{"type": "text",
            "text": "เลิกรับแจ้งเตือนงานในกลุ่มนี้แล้วครับ"}])
        return

    if text.startswith("ผูกหมวด"):
        name = text.replace("ผูกหมวด", "", 1).strip()
        if not name:
            cats = await pool.fetch("SELECT name_th FROM service_categories WHERE active ORDER BY id")
            await line_api.reply(reply_token, [{"type": "text",
                "text": "พิมพ์ชื่อหมวดต่อท้ายครับ เช่น \"ผูกหมวด ช่างแอร์\"\nหมวดที่มี: " +
                        ", ".join(r["name_th"] for r in cats)}])
            return
        cat = await pool.fetchrow(
            "SELECT id, name_th FROM service_categories WHERE active AND name_th ILIKE $1 LIMIT 1",
            f"%{name}%")
        if not cat:
            cats = await pool.fetch("SELECT name_th FROM service_categories WHERE active ORDER BY id")
            await line_api.reply(reply_token, [{"type": "text",
                "text": "ไม่พบหมวดนี้ครับ หมวดที่มี: " + ", ".join(r["name_th"] for r in cats)}])
            return
        await pool.execute(
            """INSERT INTO category_line_groups (category_id, group_id, active)
               VALUES ($1, $2, true)
               ON CONFLICT (category_id) DO UPDATE SET group_id = $2, active = true""",
            cat["id"], group_id)
        await line_api.reply(reply_token, [{"type": "text",
            "text": f"✅ ตั้งกลุ่มนี้เป็นกลุ่มช่าง \"{cat['name_th']}\" แล้ว\nงานใหม่หมวดนี้จะแจ้งเข้ากลุ่มอัตโนมัติครับ"}])
        return

    if text.startswith("ผูกตำบล"):
        name = text.replace("ผูกตำบล", "", 1).strip().lstrip("ต.").strip()
        if not name:
            await line_api.reply(reply_token, [{"type": "text",
                "text": "พิมพ์ชื่อตำบลต่อท้ายด้วยครับ เช่น \"ผูกตำบลเมือง\""}])
            return
        tambon = await pool.fetchrow(
            "SELECT id, name FROM tambons WHERE name = $1 OR name ILIKE $2 LIMIT 1",
            name, f"%{name}%")
        if not tambon:
            await line_api.reply(reply_token, [{"type": "text",
                "text": "ไม่พบตำบลนี้ครับ ลองพิมพ์ \"ผูกหมวด <ชื่อหมวด>\" แทน"}])
            return
        await pool.execute(
            """INSERT INTO tambon_line_groups (tambon_id, group_id, active)
               VALUES ($1, $2, true)
               ON CONFLICT (tambon_id) DO UPDATE SET group_id = $2, active = true""",
            tambon["id"], group_id)
        await line_api.reply(reply_token, [{"type": "text",
            "text": f"✅ ผูกกลุ่มนี้กับ ต.{tambon['name']} แล้ว\nงานใหม่ในตำบลนี้จะแจ้งเข้ากลุ่มอัตโนมัติครับ"}])


async def upsert_user(line_user_id: str | None) -> None:
    if not line_user_id:
        return
    await db.get_pool().execute(
        """INSERT INTO users (line_user_id, display_name)
           VALUES ($1, 'ผู้ใช้ใหม่') ON CONFLICT (line_user_id) DO NOTHING""",
        line_user_id,
    )
