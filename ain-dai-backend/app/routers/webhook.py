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

    if etype == "message" and event["message"].get("type") == "text":
        # ตอบเฉพาะแชท 1:1 — ในกลุ่มช่าง bot มีหน้าที่ส่งการ์ดงานอย่างเดียว
        if src.get("type") != "user":
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


async def upsert_user(line_user_id: str | None) -> None:
    if not line_user_id:
        return
    await db.get_pool().execute(
        """INSERT INTO users (line_user_id, display_name)
           VALUES ($1, 'ผู้ใช้ใหม่') ON CONFLICT (line_user_id) DO NOTHING""",
        line_user_id,
    )
