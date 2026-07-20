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
             "text": "สวัสดีครับ ยินดีต้อนรับสู่เอิ้นได้ 🙌\nบริการท้องถิ่น ใกล้คุณ\n\nต้องการช่างอะไร พิมพ์บอกได้เลย เช่น\n• \"หาช่างตัดหญ้า\"\n• \"แอร์ไม่เย็น\"\n• \"ท่อน้ำแตก\""},
        ])
        return

    if etype == "postback":
        data = dict(parse_qsl(event.get("postback", {}).get("data", "")))
        if slug := data.get("category"):
            await line_api.reply(reply_token, [flex.open_form_message(slug)])
        return

    # บอทถูกเชิญเข้ากลุ่ม/ห้อง → แนะนำวิธีผูกตำบล
    if etype == "join":
        await line_api.reply(reply_token, [{
            "type": "text",
            "text": "สวัสดีครับ 🙌 นี่คือบอทเอิ้นได้\n\nถ้าอยากให้กลุ่มนี้รับแจ้งเตือนงานใหม่ในตำบล ให้พิมพ์:\nผูกตำบล <ชื่อตำบล>\nเช่น \"ผูกตำบลโพธิ์\"\n\nเลิกรับแจ้งเตือน พิมพ์: เลิกผูกตำบล"}])
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
                if ai["category_slug"]:
                    messages.append(flex.open_form_message(ai["category_slug"]))
                await line_api.reply(reply_token, messages)
                return

        # ชั้นที่ 1 (fallback): keyword matching
        result = classify(text)
        if result.confident:
            await line_api.reply(reply_token, [flex.open_form_message(result.slug)])
        else:
            await line_api.reply(reply_token, [flex.category_quick_reply()])


async def handle_group_command(reply_token: str, group_id: str | None, text: str) -> None:
    """ผูก/เลิกผูกกลุ่มไลน์กับตำบล เพื่อรับแจ้งเตือนงานใหม่"""
    if not group_id:
        return
    pool = db.get_pool()

    if text.startswith("เลิกผูกตำบล"):
        await pool.execute(
            "UPDATE tambon_line_groups SET active = false WHERE group_id = $1", group_id)
        await line_api.reply(reply_token, [{"type": "text",
            "text": "เลิกรับแจ้งเตือนงานในกลุ่มนี้แล้วครับ"}])
        return

    if text.startswith("ผูกตำบล"):
        name = text.replace("ผูกตำบล", "", 1).strip().lstrip("ต.").strip()
        if not name:
            await line_api.reply(reply_token, [{"type": "text",
                "text": "พิมพ์ชื่อตำบลต่อท้ายด้วยครับ เช่น \"ผูกตำบลโพธิ์\""}])
            return
        tambon = await pool.fetchrow(
            "SELECT id, name FROM tambons WHERE name = $1 OR name ILIKE $2 LIMIT 1",
            name, f"%{name}%")
        if not tambon:
            names = await pool.fetch("SELECT name FROM tambons ORDER BY id")
            await line_api.reply(reply_token, [{"type": "text",
                "text": "ไม่พบตำบลนี้ครับ ตำบลที่มี: " + ", ".join(r["name"] for r in names)}])
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
