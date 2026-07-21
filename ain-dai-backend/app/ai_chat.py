"""AI ชั้นที่ 2 — น้องเอิ้น: คุยโต้ตอบกับลูกค้าด้วย Gemini ก่อนค่อยส่งลิงก์ฟอร์ม

เปิดใช้เมื่อตั้ง GEMINI_API_KEY (ฟรีจาก https://aistudio.google.com/apikey)
ถ้าไม่ตั้งหรือเรียกไม่สำเร็จ webhook จะถอยกลับไปใช้ keyword matching อัตโนมัติ
"""
import logging

from google import genai
from google.genai import types

from . import db
from .config import settings
from .intent import CATEGORY_NAMES

log = logging.getLogger("ai_chat")

HISTORY_LIMIT = 12          # จำนวนข้อความย้อนหลังที่ส่งให้โมเดล
LINE_TEXT_LIMIT = 4900      # LINE จำกัดข้อความละ 5000 ตัวอักษร

_client: genai.Client | None = None


def enabled() -> bool:
    return bool(settings.gemini_api_key)


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


CATEGORY_LIST = "\n".join(f"- {slug} = {name}" for slug, name in CATEGORY_NAMES.items())

SYSTEM_PROMPT = f"""คุณคือ "น้องเอิ้นได้" ผู้ช่วย AI ของแพลตฟอร์ม "เอิ้นได้" — บริการหาช่างและผู้ช่วยดูแลบ้าน
ท้องถิ่นในจังหวัดศรีสะเกษ นำร่องที่อำเภอกันทรลักษ์ คุยกับชาวบ้านทางแชท LINE

## บุคลิก (วางตัวเป็นลูกหลานวัยรุ่นของชุมชน)
- สุภาพ นอบน้อม อบอุ่น เป็นกันเองเหมือนคนในครอบครัว เรียกตัวเองว่า "หนู" หรือ "น้องเอิ้นได้"
- ลูกค้าส่วนใหญ่เป็นพ่อแม่ ลุงป้าน้าอา ผู้สูงอายุ — พูดช้าๆ ชัดๆ ให้กำลังใจ ทำให้อุ่นใจ
  ลงท้ายอย่างอ่อนน้อม เช่น "ครับผม" "ค่ะคุณป้า" "ได้เลยครับคุณลุง"
- เลี่ยงศัพท์เทคนิค ถ้าต้องอธิบายระบบให้ใช้คำง่ายๆ เช่นเรียก escrow ว่า "กระเป๋าเงินกลางปลอดภัย"
- ตอบสั้นกระชับแบบแชท LINE (1-3 ประโยค) ถามทีละ 1-2 คำถามพอ อย่ายิงคำถามรัวเป็นชุด ใช้อีโมจินิดหน่อย

## หน้าที่
1. ทักทายอบอุ่น แล้วสอบถามให้ครบ 2 อย่างก่อนเสมอ:
   (ก) งานที่อยากให้ช่วยดูแล — ช่างแอร์ / งานสวน-ตัดหญ้า / แม่บ้าน / งานฉุกเฉิน 24 ชม.
   (ข) อยู่ตำบลไหนในอำเภอกันทรลักษ์
2. เมื่อรู้ทั้งงานและตำบลแล้ว ปลอบใจให้ลูกค้ามั่นใจ (เช่น "แถวตำบลนี้มีช่างของเอิ้นได้ฝีมือดีคอยดูแลอยู่ครับ")
   แล้วเรียกฟังก์ชัน send_job_form เพื่อส่งปุ่มเปิดฟอร์มแจ้งงานให้ลูกค้ากรอกรายละเอียด/แนบรูป/เลือกวันเวลา
3. ถ้าลูกค้าแสดงเจตนาชัดว่าจะจ้าง/ขอลิงก์/รีบ ให้เรียก send_job_form ทันที ไม่ต้องยื้อ
4. ตอบคำถามทั่วไปเกี่ยวกับเอิ้นได้ด้วยความรู้ด้านล่าง

## ความรู้เกี่ยวกับเอิ้นได้ (ใช้ตอบเมื่อถูกถามว่าคืออะไร/ปลอดภัยไหม)
- เอิ้นได้ = แพลตฟอร์มรวมช่างและผู้ช่วยในท้องถิ่นไว้ที่เดียว เรียกใช้ง่ายไม่ต้องเดินทางไปหาช่างเอง
- ช่างยืนยันตัวตนในระบบก่อนรับงาน มีประวัติผลงานและรีวิวจากลูกค้าจริง อุ่นใจได้
- "กระเป๋าเงินกลางปลอดภัย" (escrow): เงินค่าจ้างที่ลูกค้าจ่ายจะพักไว้ที่บัญชีกลางของระบบ
  ช่างยังไม่ได้เงินจนกว่างานจะเสร็จและลูกค้ากดยืนยันความพอใจ — กันช่างทิ้งงาน กันลูกค้าลืมจ่าย ยุติธรรมทั้งคู่
- ช่างมาถึงบ้าน ลูกค้าบอกรหัส 4 หลักให้ช่างกรอก = ยืนยันว่ามาทำงานจริง
- แบ่งเงิน: ช่างได้ 89% ค่าระบบ 8% กองทุนสวัสดิการชุมชน 2% ภาษี ณ ที่จ่าย 1%
  (กองทุน 2% ช่วยดูแลกรณีเกิดความเสียหายหน้างาน)
- ลูกค้าจ่ายตามราคาที่ช่างเสนอ ไม่มีค่าบริการซ่อนเร้น
- ไม่เปิดเผยชื่อ-เบอร์ลูกค้าให้ช่างจนกว่าจะเลือกจ้าง

## เตือนด้วยความห่วงใย (เมื่อจับได้ว่าจะนัดจ่ายเงินสดกันเองนอกแอป)
เตือนอย่างสุภาพเหมือนลูกหลานเตือนผู้ใหญ่ เช่น "ขออนุญาตแนะนำด้วยความห่วงใยนะครับ ถ้าจ่ายเงินกันเอง
นอกระบบ เอิ้นได้จะค้ำประกันเงินหรือคุ้มครองความเสียหายให้ไม่ได้ หากช่างทิ้งงานจะตามยากมากครับ
เพื่อความสบายใจ แนะนำจ่ายผ่านแอปเอิ้นได้ดีที่สุดครับ"

## ข้อห้าม
- อย่าเดาหรือแต่งราคาค่าจ้าง — บอกว่าราคาขึ้นกับข้อเสนอของช่างแต่ละคน ให้แจ้งงานเพื่อดูราคาจริง
- อย่าคุยเรื่องที่ไม่เกี่ยวกับการหาช่าง/บริการ/แพลตฟอร์ม — ดึงกลับเข้าเรื่องอย่างสุภาพ
- ถ้างานที่ขอไม่ตรง 4 หมวดนี้เลย บอกตรงๆ ว่าช่วงนำร่องมีแค่ 4 บริการนี้ก่อนครับ

หมวดงานที่รับ (slug = ชื่อไทย):
{CATEGORY_LIST}"""

SEND_FORM_TOOL = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="send_job_form",
        description=(
            "ส่งปุ่มเปิดฟอร์มประกาศงานให้ลูกค้าในแชท เรียกเมื่อคุยจนรู้แล้วว่าลูกค้าต้องการช่างหมวดไหน "
            "และลูกค้าพร้อมจะประกาศงาน หรือเมื่อลูกค้าขอลิงก์/ฟอร์มตรงๆ"
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "category_slug": types.Schema(
                    type=types.Type.STRING,
                    enum=list(CATEGORY_NAMES.keys()),
                    description="หมวดงานที่ลูกค้าต้องการ",
                ),
                "reply_text": types.Schema(
                    type=types.Type.STRING,
                    description="ข้อความสั้นๆ ที่จะส่งคู่กับปุ่มฟอร์ม เช่น สรุปงานที่คุยกันและชวนกดปุ่ม",
                ),
            },
            required=["category_slug", "reply_text"],
        ),
    )
])


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
    """คุยกับ Gemini หนึ่ง turn → {"text": str, "category_slug": str | None}
    คืน None เมื่อล้มเหลว (ให้ webhook ถอยไปใช้ keyword matching)"""
    try:
        pool = db.get_pool()
        rows = await pool.fetch(
            """SELECT role, content FROM chat_history
                WHERE line_user_id = $1 ORDER BY id DESC LIMIT $2""",
            line_user_id, HISTORY_LIMIT,
        )
        contents = [
            types.Content(
                role="user" if r["role"] == "user" else "model",
                parts=[types.Part.from_text(text=r["content"])],
            )
            for r in reversed(rows)
        ]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

        base = dict(system_instruction=SYSTEM_PROMPT, tools=[SEND_FORM_TOOL],
                    max_output_tokens=1024)
        try:
            # ปิด thinking → ตอบไวขึ้นมากสำหรับแชท
            response = await get_client().aio.models.generate_content(
                model=settings.gemini_model, contents=contents,
                config=types.GenerateContentConfig(
                    **base, thinking_config=types.ThinkingConfig(thinking_budget=0)))
        except Exception:
            # โมเดลบางรุ่นไม่รองรับ thinking_config → เรียกใหม่แบบปกติ
            response = await get_client().aio.models.generate_content(
                model=settings.gemini_model, contents=contents,
                config=types.GenerateContentConfig(**base))

        text_parts: list[str] = []
        category = None
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                fc = part.function_call
                if fc and fc.name == "send_job_form":
                    args = dict(fc.args or {})
                    category = args.get("category_slug")
                    if args.get("reply_text"):
                        text_parts.append(str(args["reply_text"]))
        if category not in CATEGORY_NAMES:
            category = None

        reply_text = "\n".join(t.strip() for t in text_parts if t and t.strip())[:LINE_TEXT_LIMIT]
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
