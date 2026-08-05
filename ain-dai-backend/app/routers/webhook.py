"""LINE webhook: รับข้อความ → intent ชั้น 1 → ตอบปุ่มเปิดฟอร์ม หรือ quick reply"""
import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, Header, HTTPException, Request

from .. import ai_chat, chat_job, db, flex, line_api, promptpay
from ..config import settings
from ..intent import classify, classify_sub, subcategories_of
from .jobs import (do_approve_job, do_cancel_pending, do_confirm_payment,
                   do_select_bid, pending_order, pending_payment)

# คำสั่งยกเลิก/เริ่มใหม่ที่ลูกค้าพิมพ์ได้ (นอกจากกดปุ่ม)
CANCEL_WORDS = {"ยกเลิก", "ยกเลิกรายการ", "ยกเลิกรายการเดิม", "เริ่มใหม่",
                "เริ่มต้นใหม่", "รายการใหม่", "ล้างแชท", "เคลียร์", "reset"}


def is_cancel_command(text: str) -> bool:
    t = text.strip().lower()
    return t in CANCEL_WORDS or t.startswith("ยกเลิก") or t.startswith("เริ่มใหม่")

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
        uid = src.get("userId")
        if slug := data.get("category"):
            sub = data.get("sub")
            # งานด่วนที่ยังไม่รู้ประเภท → ถามประเภทก่อน ไม่งั้นเริ่มเก็บข้อมูลในแชทเลย
            if not sub and subcategories_of(slug):
                await line_api.reply(reply_token, [flex.subcategory_quick_reply(slug)])
            elif uid:
                await upsert_user(uid)
                await line_api.reply(reply_token,
                                     await chat_job.start(uid, slug, sub or None, ""))
        elif data.get("a"):
            await handle_transaction_postback(reply_token, uid, data)
        return

    # บอทถูกเชิญเข้ากลุ่ม/ห้อง → แนะนำวิธีผูกหมวดงาน
    if etype == "join":
        await line_api.reply(reply_token, [{
            "type": "text",
            "text": "สวัสดีครับ 🙌 นี่คือบอทเอิ้นได้\n\nตั้งให้กลุ่มนี้เป็นกลุ่มช่างของหมวดงาน — พิมพ์:\nผูกหมวด ช่างแอร์\n(หรือ งานสวน / แม่บ้าน / งานด่วน)\n\nงานใหม่ในหมวดนี้จะแจ้งเข้ากลุ่มอัตโนมัติ\nเลิกรับแจ้งเตือน พิมพ์: เลิกผูก"}])
        return

    if etype == "message":
        mtype = event["message"].get("type")

        # ในกลุ่ม/ห้อง: รับเฉพาะข้อความ text สำหรับคำสั่งผูก/เลิกผูก
        if src.get("type") in ("group", "room"):
            if mtype == "text":
                gid = src.get("groupId") or src.get("roomId")
                await handle_group_command(reply_token, gid, event["message"]["text"].strip())
            return

        user_id = src.get("userId")
        if not user_id:
            return
        await upsert_user(user_id)
        text = event["message"].get("text", "").strip() if mtype == "text" else ""

        # พิมพ์ "ยกเลิก"/"เริ่มใหม่" → ล้างบทสนทนา + งานร่างในแชท + งานที่ค้าง
        if mtype == "text" and is_cancel_command(text):
            await handle_cancel(reply_token, user_id)
            return

        user = await db.get_pool().fetchrow(
            "SELECT id, line_user_id FROM users WHERE line_user_id = $1", user_id)

        # มีงานร่างค้างในแชท → เดินหน้าเก็บข้อมูลต่อ (ตำบล/รูป/งบ/รายละเอียด)
        draft = await chat_job.get_draft(user_id)
        if draft:
            await line_api.reply(reply_token, await chat_job.advance(dict(user), event, draft))
            return

        # ส่งรูปมาโดยไม่มีงานร่าง — ถ้ามีรายการรอชำระ ถือเป็น "สลิปการโอน"
        if mtype == "image":
            await handle_slip(reply_token, dict(user), event["message"].get("id"))
            return

        # ส่งตำแหน่ง/อื่นๆ ลอยๆ → บอกวิธีเริ่ม
        if mtype != "text":
            await line_api.reply(reply_token, [{"type": "text",
                "text": "พิมพ์บอกงานที่ต้องการก่อนนะครับ เช่น \"แอร์ไม่เย็น\" หรือ \"รถยางรั่ว\" "
                        "แล้วผมจะถามรายละเอียดทีละขั้นแล้วประกาศหาช่างให้เลยครับ 😊"}])
            return

        # AI ชั้นที่ 2 (ถ้าเปิด Gemini): คุยโต้ตอบ แล้วเริ่มเก็บข้อมูลในแชท
        if ai_chat.enabled():
            await line_api.show_loading(user_id)
            ai = await ai_chat.chat(user_id, text)
            if ai:
                messages: list[dict] = []
                if ai["text"]:
                    messages.append({"type": "text", "text": ai["text"]})
                if ai["form"]:
                    f = ai["form"]
                    if subcategories_of(f["category_slug"]) and not f.get("subcategory_slug"):
                        messages.append(flex.subcategory_quick_reply(f["category_slug"]))
                    else:
                        # เริ่มเก็บข้อมูลในแชท (แทนการส่งลิงก์เว็บ)
                        messages += await chat_job.start(
                            user_id, f["category_slug"], f.get("subcategory_slug"),
                            f.get("description") or text)
                await line_api.reply(reply_token, messages)
                return

        # ชั้นที่ 1 (Gemini ปิด): จับหมวด → เริ่มเก็บข้อมูลในแชท
        result = classify(text)
        if result.confident:
            sub = classify_sub(text, result.slug)
            if subcategories_of(result.slug) and not sub:
                # งานด่วนแต่ยังไม่รู้ว่าด่วนเรื่องอะไร → ถามประเภทก่อน
                await line_api.reply(reply_token, [flex.subcategory_quick_reply(result.slug)])
            else:
                await line_api.reply(reply_token,
                                     await chat_job.start(user_id, result.slug, sub, text))
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


async def handle_transaction_postback(reply_token: str, line_user_id: str | None, data: dict) -> None:
    """ปุ่มในการ์ดแชท: เลือกช่าง (pick) → จ่ายเงิน (paid) → ยืนยันงาน (confirm)
    ทำธุรกรรมจริงในแชท โดยเช็คว่าเป็นลูกค้าเจ้าของงานก่อนทุกครั้ง"""
    if not line_user_id:
        return
    pool = db.get_pool()
    me = await pool.fetchrow("SELECT id FROM users WHERE line_user_id = $1", line_user_id)
    if not me:
        return
    action = data.get("a")
    try:
        if action == "pick":                      # ลูกค้าเลือกช่าง → ส่งการ์ดจ่ายเงิน
            r = await do_select_bid(pool, data["job"], data["bid"], me["id"])
            prov = await pool.fetchrow(
                """SELECT u.display_name FROM bids b JOIN providers p ON p.id = b.provider_id
                     JOIN users u ON u.id = p.user_id WHERE b.id = $1::uuid""", data["bid"])
            card = flex.payment_card(r["payment_id"], r["amount"],
                                     prov["display_name"] if prov else "ช่าง",
                                     f"/api/payments/{r['payment_id']}/qr.png")
            msgs = [{"type": "text",
                     "text": f"เลือกช่าง {prov['display_name'] if prov else ''} เรียบร้อยครับ 👍 "
                             "สแกน QR ด้านล่างจ่ายเงิน แล้วส่งรูปสลิปกลับมาในแชทนี้ได้เลยครับ 📤"}, card]
            if not settings.public_base_url:   # โหมดยังไม่ตั้งโดเมน — ส่ง payload ให้ก่อน
                msgs.append({"type": "text", "text": "PromptPay: " +
                             promptpay.payload(settings.promptpay_id, float(r["amount"]))})
            await line_api.reply(reply_token, msgs)

        elif action == "paid":                    # การ์ดเก่า/พิมพ์มา → ขอสลิปแทน
            await line_api.reply(reply_token, [{"type": "text",
                "text": "รบกวนถ่ายรูปสลิปการโอนส่งมาในแชทนี้ด้วยครับ เพื่อยืนยันการชำระ 📤"}])

        elif action == "confirm":                 # ลูกค้ายืนยันจบงาน → ปล่อยเงิน
            await do_approve_job(pool, data["job"], me["id"])
            await line_api.reply(reply_token, [{"type": "text",
                "text": "ขอบคุณครับพี่ 🙏 ยืนยันงานเรียบร้อย ระบบกำลังโอนเงินให้ช่าง\n"
                        "ฝากรีวิวช่างในแอปเพื่อช่วยช่างดีๆ ในชุมชนของเราด้วยนะครับ ⭐"}])

        elif action == "jobpost":                 # กดปุ่มประกาศหาช่าง (จบในแชท)
            draft = await chat_job.get_draft(line_user_id)
            if not draft:
                await line_api.reply(reply_token, [{"type": "text",
                    "text": "ไม่พบข้อมูลงานที่ค้างไว้ครับ พิมพ์บอกงานใหม่ได้เลย"}])
            else:
                await line_api.reply(reply_token,
                    await chat_job.post_job({"id": me["id"], "line_user_id": line_user_id}, draft))

        elif action == "jobcancel":               # ยกเลิกงานร่างในแชท
            await chat_job.clear(line_user_id)
            await line_api.reply(reply_token, [{"type": "text",
                "text": "ยกเลิกแล้วครับ พิมพ์บอกงานใหม่ได้เลยเมื่อพร้อม 😊"}])

        elif action == "cancel":                  # กดปุ่มยกเลิกรายการเดิม
            await handle_cancel(reply_token, line_user_id)
    except HTTPException as e:
        await line_api.reply(reply_token, [{"type": "text", "text": f"ทำรายการไม่สำเร็จ: {e.detail}"}])


async def handle_slip(reply_token: str, user: dict, message_id: str | None) -> None:
    """ลูกค้าส่งรูปสลิปการโอน → เก็บสลิป + ยืนยันจ่าย (พักเงิน + รหัสเริ่มงาน)"""
    pool = db.get_pool()
    pay = await pending_payment(pool, user["id"])
    if not pay:
        await line_api.reply(reply_token, [{"type": "text",
            "text": "ยังไม่มีรายการที่รอชำระครับ ถ้าจะแจ้งงานใหม่พิมพ์บอกได้เลย เช่น \"แอร์ไม่เย็น\""}])
        return
    content = await line_api.get_message_content(message_id)
    if not content:
        await line_api.reply(reply_token, [{"type": "text",
            "text": "รับรูปสลิปไม่สำเร็จครับ ลองถ่ายใหม่แล้วส่งมาอีกทีนะครับ"}])
        return
    slip_url = await chat_job._save_photo(content)   # เก็บสลิปใน uploads
    try:
        r = await do_confirm_payment(pool, str(pay["id"]), user["id"], slip_url=slip_url)
    except HTTPException as e:
        await line_api.reply(reply_token, [{"type": "text", "text": f"ยืนยันไม่สำเร็จ: {e.detail}"}])
        return
    if not r:
        await line_api.reply(reply_token, [{"type": "text", "text": "รายการนี้ชำระไปแล้วครับ"}])
        return
    await line_api.reply(reply_token, [{"type": "text",
        "text": "ได้รับสลิปแล้วครับ ขอบคุณครับ 🙏\n\n"
                f"รหัสเริ่มงานของพี่คือ  {r['otp']}\n"
                "บอกรหัสนี้กับช่างตอนช่างมาถึงบ้าน เพื่อยืนยันว่าช่างมาทำงานจริง "
                "งานเสร็จผมจะส่งปุ่มให้พี่กดยืนยันครับ"}])


async def handle_cancel(reply_token: str, line_user_id: str | None) -> None:
    """ยกเลิกงานที่ค้าง (ก่อนจ่ายเงิน) + ล้างบทสนทนาเดิม แล้วให้เริ่มใหม่"""
    if not line_user_id:
        return
    pool = db.get_pool()
    me = await pool.fetchrow("SELECT id FROM users WHERE line_user_id = $1", line_user_id)
    cancelled = await do_cancel_pending(pool, me["id"]) if me else None
    await ai_chat.clear_history(line_user_id)
    await chat_job.clear(line_user_id)   # ล้างงานร่างที่กำลังเก็บข้อมูลในแชทด้วย
    if cancelled:
        text = (f"ยกเลิกรายการเดิม \"{cancelled}\" ให้แล้วครับ ✅\n"
                "เริ่มใหม่ได้เลย พี่อยากให้ช่วยเรื่องอะไรครับ?")
    else:
        text = "เริ่มบทสนทนาใหม่ให้แล้วครับ 😊 พี่อยากให้ช่วยเรื่องอะไรครับ?"
    await line_api.reply(reply_token, [{**flex.category_quick_reply(), "text": text}])


async def upsert_user(line_user_id: str | None) -> None:
    if not line_user_id:
        return
    await db.get_pool().execute(
        """INSERT INTO users (line_user_id, display_name)
           VALUES ($1, 'ผู้ใช้ใหม่') ON CONFLICT (line_user_id) DO NOTHING""",
        line_user_id,
    )
