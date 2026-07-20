"""AI ชั้นที่ 2 — น้องเอิ้น: คุยโต้ตอบกับลูกค้าด้วย Claude ก่อนค่อยส่งลิงก์ฟอร์ม

เปิดใช้เมื่อตั้ง ANTHROPIC_API_KEY — ถ้าไม่ตั้งหรือเรียกไม่สำเร็จ
webhook จะถอยกลับไปใช้ keyword matching (intent ชั้นที่ 1) อัตโนมัติ
"""
import logging

import anthropic

from . import db
from .config import settings
from .intent import CATEGORY_NAMES

log = logging.getLogger("ai_chat")

HISTORY_LIMIT = 12          # จำนวน turn ย้อนหลังที่ส่งให้โมเดล
LINE_TEXT_LIMIT = 4900      # LINE จำกัดข้อความละ 5000 ตัวอักษร

_client: anthropic.AsyncAnthropic | None = None


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


CATEGORY_LIST = "\n".join(f"- {slug} = {name}" for slug, name in CATEGORY_NAMES.items())

SYSTEM_PROMPT = f"""คุณคือ "น้องเอิ้น" ผู้ช่วย AI ของ "เอิ้นได้" แพลตฟอร์มหาช่างและบริการท้องถิ่นในจังหวัดศรีสะเกษ
คุยกับลูกค้าทางแชท LINE

## หน้าที่ของคุณ
1. คุยกับลูกค้าเพื่อทำความเข้าใจว่าต้องการช่างประเภทไหน มีปัญหาอะไร
2. ถามเจาะรายละเอียดที่จำเป็น เช่น อาการ/ลักษณะงาน พื้นที่ (ตำบลไหน) ช่วงเวลาที่สะดวก งบประมาณคร่าวๆ
3. เมื่อเข้าใจงานชัดแล้ว (รู้หมวดงาน + รายละเอียดพอประมาณ) ให้เรียกเครื่องมือ send_job_form
   เพื่อส่งปุ่มเปิดฟอร์มประกาศงานให้ลูกค้า
4. ตอบคำถามทั่วไปเกี่ยวกับเอิ้นได้

## ความรู้เกี่ยวกับเอิ้นได้
- flow การใช้งาน: ลูกค้าประกาศงาน → ช่างในตำบลเสนอราคาแข่งกัน → ลูกค้าเลือกช่างและจ่ายเงินผ่านระบบ
  (เงินพักไว้ตรงกลางแบบ escrow ยังไม่ถึงช่าง) → ช่างมาถึงบ้านลูกค้าบอกรหัส OTP 4 หลักให้ช่างกรอกเพื่อเริ่มงาน
  → งานเสร็จลูกค้าตรวจแล้วกดยืนยัน เงินจึงโอนให้ช่าง → ให้คะแนนรีวิวช่างได้
- ถ้าลูกค้าไม่กดยืนยันภายใน 24 ชั่วโมง ระบบยืนยันให้อัตโนมัติ
- การแบ่งเงิน: ช่างได้ 89% ค่าระบบ 8% กองทุนชุมชนประจำตำบล 2% ภาษีหัก ณ ที่จ่าย 1%
- ลูกค้าไม่เสียค่าบริการเพิ่ม จ่ายตามราคาที่ช่างเสนอ
- ปลอดภัย: ไม่เปิดเผยชื่อ-เบอร์ลูกค้าให้ช่างจนกว่าจะเลือกจ้าง, เงิน escrow กันช่างเบี้ยว
- หมวดงานที่มี (slug = ชื่อไทย):
{CATEGORY_LIST}

## สไตล์การคุย
- ภาษาไทยเป็นกันเอง สุภาพ ลงท้าย "ครับ" ใช้อีโมจิได้นิดหน่อย
- ตอบสั้นกระชับแบบแชท LINE (1-3 ประโยค) ถามทีละ 1-2 คำถามพอ อย่ายิงคำถามรัวเป็นชุด
- อย่าเดาหรือแต่งราคาค่าจ้าง — บอกว่าราคาขึ้นกับข้อเสนอของช่างแต่ละคน ให้ประกาศงานเพื่อดูราคาจริง
- ถ้าลูกค้าบอกชัดตั้งแต่แรกว่าต้องการอะไร (เช่น "หาช่างตัดหญ้า") ถามรายละเอียดเพิ่มสัก 1 คำถาม
  แล้วส่งฟอร์มได้เลย ไม่ต้องยื้อ
- ถ้าลูกค้าขอฟอร์ม/ลิงก์ตรงๆ หรือรีบ ให้เรียก send_job_form ทันที
- ถ้าเรื่องที่ขอไม่ตรงหมวดไหนเลย ใช้หมวดใกล้เคียงที่สุด หรือแนะนำว่ายังไม่มีบริการนั้น
- ห้ามคุยเรื่องที่ไม่เกี่ยวกับการหาช่าง/บริการ/แพลตฟอร์ม — ดึงกลับเข้าเรื่องอย่างสุภาพ"""

SEND_FORM_TOOL = {
    "name": "send_job_form",
    "description": (
        "ส่งปุ่มเปิดฟอร์มประกาศงานให้ลูกค้าในแชท เรียกเมื่อคุยจนรู้แล้วว่าลูกค้าต้องการช่างหมวดไหน "
        "และลูกค้าพร้อมจะประกาศงาน หรือเมื่อลูกค้าขอลิงก์/ฟอร์มตรงๆ"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category_slug": {
                "type": "string",
                "enum": list(CATEGORY_NAMES.keys()),
                "description": "หมวดงานที่ลูกค้าต้องการ",
            },
            "reply_text": {
                "type": "string",
                "description": "ข้อความสั้นๆ ที่จะส่งคู่กับปุ่มฟอร์ม เช่น สรุปงานที่คุยกันและชวนกดปุ่ม",
            },
        },
        "required": ["category_slug", "reply_text"],
        "additionalProperties": False,
    },
}


async def ensure_table() -> None:
    """สร้างตารางเก็บประวัติแชท (เรียกตอน startup — รันซ้ำได้)"""
    pool = db.get_pool()
    await pool.execute(
        """CREATE TABLE IF NOT EXISTS chat_history (
             id           bigserial PRIMARY KEY,
             line_user_id text NOT NULL,
             role         text NOT NULL CHECK (role IN ('user','assistant')),
             content      text NOT NULL,
             created_at   timestamptz NOT NULL DEFAULT now()
           )"""
    )
    await pool.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_history (line_user_id, id DESC)"
    )


async def chat(line_user_id: str, user_text: str) -> dict | None:
    """คุยกับ Claude หนึ่ง turn → {"text": str, "category_slug": str | None}
    คืน None เมื่อล้มเหลว (ให้ webhook ถอยไปใช้ keyword matching)"""
    try:
        pool = db.get_pool()
        rows = await pool.fetch(
            """SELECT role, content FROM chat_history
                WHERE line_user_id = $1 ORDER BY id DESC LIMIT $2""",
            line_user_id, HISTORY_LIMIT,
        )
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

        response = await get_client().messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},  # แชทสั้น เน้นตอบไว
            tools=[SEND_FORM_TOOL],
            messages=history + [{"role": "user", "content": user_text}],
        )

        if response.stop_reason == "refusal":
            log.warning("Claude ปฏิเสธคำขอ (refusal) — ถอยไปใช้ keyword")
            return None

        text_parts = [b.text for b in response.content if b.type == "text"]
        category = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "send_job_form":
                category = block.input.get("category_slug")
                if block.input.get("reply_text"):
                    text_parts.append(block.input["reply_text"])

        reply_text = "\n".join(t.strip() for t in text_parts if t.strip())[:LINE_TEXT_LIMIT]
        if not reply_text and not category:
            return None

        # บันทึกประวัติ — ฝั่ง assistant แนบ marker ไว้ให้โมเดลรู้ว่าส่งฟอร์มไปแล้ว
        saved_reply = reply_text
        if category:
            saved_reply += f"\n[ส่งปุ่มเปิดฟอร์มหมวด {category} ให้ลูกค้าแล้ว]"
        await pool.execute(
            """INSERT INTO chat_history (line_user_id, role, content)
               VALUES ($1, 'user', $2), ($1, 'assistant', $3)""",
            line_user_id, user_text, saved_reply,
        )
        return {"text": reply_text, "category_slug": category}
    except Exception:
        log.exception("AI chat ล้มเหลว — ถอยไปใช้ keyword matching")
        return None
