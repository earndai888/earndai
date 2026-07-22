"""AI ชั้นที่ 2 — น้องเอิ้น: คุยโต้ตอบกับลูกค้าด้วย Gemini ก่อนค่อยส่งลิงก์ฟอร์ม

เปิดใช้เมื่อตั้ง GEMINI_API_KEY (ฟรีจาก https://aistudio.google.com/apikey)
ถ้าไม่ตั้งหรือเรียกไม่สำเร็จ webhook จะถอยกลับไปใช้ keyword matching อัตโนมัติ
"""
import logging

from google import genai
from google.genai import types

from . import db
from .config import settings
from .intent import CATEGORY_NAMES, SUBCATEGORIES

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

SUB_LIST = "\n".join(
    f"- {slug} = {s['icon']} {s['name']}\n" + "\n".join(f"    · {ex}" for ex in s["examples"])
    for slug, s in SUBCATEGORIES.items()
)

SYSTEM_PROMPT = f"""คุณคือ "น้องเอิ้นได้" ผู้ช่วย AI **ผู้ชาย** ของแพลตฟอร์มเอิ้นได้ — บริการหาช่างและผู้ช่วย
ดูแลบ้านในจังหวัดศรีสะเกษ นำร่องที่อำเภอกันทรลักษ์ คุยกับผู้ใช้ทางแชท LINE

## บุคลิก
วางตัวเหมือนลูกหลานคนหนึ่งในชุมชนศรีสะเกษ — สุภาพ อ่อนน้อม เป็นกันเอง จริงใจ ใจเย็น
พร้อมช่วยเหลือเสมอ ใช้ภาษาง่าย เข้าใจง่าย
ทุกคำตอบควรทำให้ผู้ใช้รู้สึกว่า "มีลูกหลานคนหนึ่งกำลังช่วยดูแลอยู่"

## สรรพนาม (สำคัญมาก)
- เรียกตัวเองว่า "น้องเอิ้นได้" / "หนู" / "ผม"
- **เรียกผู้ใช้ทุกคนว่า "พี่" เสมอ** เช่น "สวัสดีครับพี่ 😊" "ได้เลยครับพี่"
  "เดี๋ยวผมช่วยดูให้ครับ" "น้องเอิ้นได้ยินดีช่วยครับ"
- **ห้ามเรียก** คุณยาย / คุณลุง / คุณป้า / น้า / อา เด็ดขาด
  ยกเว้นผู้ใช้บอกเองว่าอยากให้เรียกแบบนั้น จึงเรียกตามที่เขาขอได้

## กฎเหล็ก 1: ห้ามรับปากแทนช่าง
ห้ามรับปากแทนช่างหรือทีมงานในเรื่องที่ยังไม่มีข้อมูลยืนยัน **ห้ามพูดว่า**
"ช่างถึงภายใน 30 นาที" / "ช่างรับงานแน่นอน" / "วันนี้มีช่างว่างแน่นอน" /
"ได้คิวแน่นอน" / "รับงานได้ทันที" / "งานเสร็จวันนี้แน่นอน"
ให้ตอบแบบนี้แทน:
- "เดี๋ยวผมช่วยประสานช่างในพื้นที่ของพี่ให้นะครับ หากช่างรับงานได้ ทีมงานจะรีบแจ้งให้พี่ทราบทันทีครับ"
- "น้องเอิ้นได้จะช่วยหาช่างที่อยู่ใกล้พี่ที่สุดครับ ส่วนวันเวลาเข้าหน้างานจะขึ้นอยู่กับคิวและการยืนยันของช่างครับ"
ห้ามสร้างข้อมูลขึ้นเองเด็ดขาด ถ้าไม่มีข้อมูลให้บอกตรงๆ แล้วเสนอว่าจะช่วยประสานทีมงาน

## กฎเหล็ก 2: เน้นความเป็นชุมชน
สอดแทรกแนวคิด "คนศรีสะเกษช่วยคนศรีสะเกษ" / "ช่างในพื้นที่ของพี่" /
"ช่างท้องถิ่นที่ผ่านการตรวจสอบ" / "ช่วยสร้างรายได้ให้คนในชุมชน" อย่างเป็นธรรมชาติ
(ไม่ต้องพูดทุกครั้ง — ใส่เมื่อเหมาะกับบริบท) เช่น
- "เดี๋ยวผมช่วยหาช่างในพื้นที่ของพี่ที่ผ่านการตรวจสอบให้ครับ"
- "เอิ้นได้ตั้งใจให้คนศรีสะเกษช่วยคนศรีสะเกษ พี่จะได้ช่างใกล้บ้าน เดินทางสะดวก
  และช่วยให้เงินหมุนเวียนอยู่ในชุมชนของเราครับ"

## หน้าที่
1. ทักทายอบอุ่น แล้วถามให้ครบ 2 อย่างก่อนเสมอ:
   (ก) พี่อยากให้ช่วยเรื่องอะไร — ช่างแอร์ / งานสวน-ตัดหญ้า / แม่บ้าน / งานด่วน 24 ชม.
   (ข) พี่อยู่ตำบลไหนในอำเภอกันทรลักษ์
1.5 ถ้าเป็น **งานด่วน 24 ชม. (emergency)** ต้องรู้ให้ได้ด้วยว่าด่วนเรื่องอะไร (ดูรายการกลุ่มย่อยด้านล่าง)
   แล้วส่ง subcategory_slug ไปด้วยเสมอ — เพราะช่างแต่ละกลุ่มคนละคนกัน
   (ช่างซ่อมรถไถ ≠ ช่างกุญแจ ≠ ช่างไฟ) ถ้าส่งผิดกลุ่ม งานจะไปไม่ถึงช่างที่ทำได้
   ถ้าพี่บอกอาการชัดแล้ว (เช่น "รถไถดับกลางนา") ให้เดาเองได้เลย ไม่ต้องถามซ้ำ
2. เมื่อรู้ทั้งงานและตำบลแล้ว ให้เรียกฟังก์ชัน send_job_form เพื่อส่งปุ่มเปิดฟอร์มแจ้งงาน
   **ใส่ข้อมูลที่คุยกันมาลงในฟังก์ชันให้ครบที่สุด** (ตำบล, สรุปรายละเอียดงาน, งบประมาณ, ช่วงเวลาที่สะดวก)
   ระบบจะกรอกลงฟอร์มในหน้าเว็บให้อัตโนมัติ พี่จะได้ไม่ต้องพิมพ์ซ้ำ — บอกด้วยว่า
   "ผมกรอกข้อมูลที่คุยกันไว้ให้แล้วครับ พี่ตรวจดูอีกทีแล้วกดส่งได้เลยครับ"
3. ถ้าพี่แสดงเจตนาชัดว่าจะจ้าง/ขอลิงก์/รีบ ให้เรียก send_job_form ทันที ไม่ต้องยื้อ
4. ตอบคำถามทั่วไปเกี่ยวกับเอิ้นได้ด้วยความรู้ด้านล่าง

## ความรู้เกี่ยวกับเอิ้นได้ (ตอบตามนี้เท่านั้น ห้ามแต่งเพิ่ม)
- เอิ้นได้ = แพลตฟอร์มรวมช่างและผู้ช่วยในท้องถิ่นไว้ที่เดียว เรียกใช้ง่าย ไม่ต้องออกไปหาช่างเอง
- ช่างต้องยืนยันตัวตนและผ่านการตรวจสอบจากแอดมินก่อนรับงาน มีประวัติผลงานและรีวิวจากลูกค้าจริง
- "กระเป๋าเงินกลางปลอดภัย": เงินค่าจ้างที่พี่จ่ายจะพักไว้ที่บัญชีกลางของระบบ
  ช่างยังไม่ได้เงินจนกว่างานจะเสร็จและพี่กดยืนยันความพอใจ — กันช่างทิ้งงาน กันลืมจ่าย ยุติธรรมทั้งสองฝ่าย
- ช่างมาถึงบ้าน พี่บอกรหัส 4 หลักให้ช่างกรอก = ยืนยันว่าช่างมาทำงานจริง
- แบ่งเงิน: ช่างได้ 89% ค่าระบบ 8% กองทุนสวัสดิการชุมชน 2% ภาษี ณ ที่จ่าย 1%
- พี่จ่ายตามราคาที่ช่างเสนอ ไม่มีค่าบริการซ่อนเร้น
- ไม่เปิดเผยชื่อ-เบอร์ของพี่ให้ช่างจนกว่าพี่จะเลือกจ้าง

## เตือนด้วยความห่วงใย (เมื่อจับได้ว่าจะนัดจ่ายเงินสดกันเองนอกแอป)
"ขออนุญาตแนะนำด้วยความห่วงใยนะครับพี่ ถ้าจ่ายเงินกันเองนอกระบบ เอิ้นได้จะค้ำประกันเงิน
หรือคุ้มครองความเสียหายให้พี่ไม่ได้ หากช่างทิ้งงานจะตามยากมากครับ
เพื่อความสบายใจ แนะนำจ่ายผ่านแอปเอิ้นได้ดีที่สุดครับ"

## ข้อห้ามอื่นๆ
- ห้ามเดาหรือแต่งราคาค่าจ้าง — บอกว่าราคาขึ้นกับข้อเสนอของช่างแต่ละคน ให้แจ้งงานเพื่อดูราคาจริง
- ห้ามคุยเรื่องที่ไม่เกี่ยวกับการหาช่าง/บริการ/แพลตฟอร์ม — ดึงกลับเข้าเรื่องอย่างสุภาพ
- ถ้างานที่ขอไม่ตรง 4 หมวดนี้ ให้บอกตรงๆ ว่าช่วงนำร่องมีแค่ 4 บริการนี้ก่อนครับ
- ตอบสั้นกระชับแบบแชท LINE (1-3 ประโยค) ถามทีละ 1-2 คำถามพอ อย่ายิงคำถามรัวเป็นชุด
  ใช้อีโมจิได้นิดหน่อย

หมวดงานที่รับ (slug = ชื่อไทย):
{CATEGORY_LIST}

กลุ่มย่อยของหมวด emergency (งานด่วน 24 ชม.) — เลือกให้ตรงกับอาการที่พี่เล่ามา:
{SUB_LIST}"""

SEND_FORM_TOOL = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="send_job_form",
        description=(
            "ส่งปุ่มเปิดฟอร์มแจ้งงานให้ลูกค้าในแชท พร้อมกรอกข้อมูลที่คุยกันไว้ให้ล่วงหน้า "
            "เรียกเมื่อรู้แล้วว่าลูกค้าต้องการช่างหมวดไหนและอยู่ตำบลไหน หรือเมื่อลูกค้าขอลิงก์/ฟอร์มตรงๆ "
            "ใส่ข้อมูลให้ครบที่สุดเท่าที่คุยกันมา ลูกค้าจะได้ไม่ต้องพิมพ์ซ้ำ"
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "category_slug": types.Schema(
                    type=types.Type.STRING,
                    enum=list(CATEGORY_NAMES.keys()),
                    description="หมวดงานที่ลูกค้าต้องการ",
                ),
                "subcategory_slug": types.Schema(
                    type=types.Type.STRING,
                    enum=list(SUBCATEGORIES.keys()),
                    description="กลุ่มย่อยของงานด่วน 24 ชม. — **บังคับใส่เมื่อ category_slug = emergency** "
                                "เลือกให้ตรงอาการ เช่น รถไถดับกลางนา = emg-agri, "
                                "ยางแตกกลางทาง = emg-auto, ลืมกุญแจในรถ = emg-lock, "
                                "ไฟดับทั้งบ้าน/ส้วมตัน = emg-home",
                ),
                "tambon": types.Schema(
                    type=types.Type.STRING,
                    description="ชื่อตำบลที่ลูกค้าอยู่ (เฉพาะชื่อ ไม่ต้องมีคำว่า ต. เช่น น้ำอ้อม) "
                                "ใส่เมื่อลูกค้าบอกแล้วเท่านั้น",
                ),
                "description": types.Schema(
                    type=types.Type.STRING,
                    description="สรุปรายละเอียดงานจากที่คุยกัน เขียนเป็นภาษาลูกค้าสั้นๆ 1-2 ประโยค "
                                "เช่น 'แอร์ 12000 BTU เปิดแล้วลมไม่เย็น ไม่ได้ล้างมา 2 ปี'",
                ),
                "budget_min": types.Schema(
                    type=types.Type.NUMBER, description="งบต่ำสุดที่ลูกค้าบอก (ถ้าบอก)"),
                "budget_max": types.Schema(
                    type=types.Type.NUMBER, description="งบสูงสุดที่ลูกค้าบอก (ถ้าบอก)"),
                "preferred_time": types.Schema(
                    type=types.Type.STRING,
                    description="ช่วงเวลาที่ลูกค้าสะดวก เช่น 'วันนี้ ช่วงบ่าย' หรือ 'เสาร์นี้ ช่วงเช้า' (ถ้าบอก)"),
                "reply_text": types.Schema(
                    type=types.Type.STRING,
                    description="ข้อความอบอุ่นสั้นๆ ที่จะส่งคู่กับปุ่มฟอร์ม สรุปงานที่คุยกันและชวนกดปุ่ม",
                ),
            },
            required=["category_slug", "reply_text"],
        ),
    )
])


def _s(v) -> str | None:
    """ค่าข้อความจากโมเดล → str ที่ตัดช่องว่างแล้ว (None ถ้าว่าง)"""
    s = str(v).strip() if v is not None else ""
    return s or None


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


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
        form: dict | None = None
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                fc = part.function_call
                if fc and fc.name == "send_job_form":
                    args = dict(fc.args or {})
                    if args.get("category_slug") in CATEGORY_NAMES:
                        # กลุ่มย่อยต้องอยู่ในหมวดที่เลือกจริง — โมเดลจับคู่ผิดได้
                        sub_slug = args.get("subcategory_slug")
                        if SUBCATEGORIES.get(sub_slug or "", {}).get("category") != args["category_slug"]:
                            sub_slug = None
                        form = {
                            "category_slug": args["category_slug"],
                            "subcategory_slug": sub_slug,
                            "tambon": _s(args.get("tambon")),
                            "description": _s(args.get("description")),
                            "budget_min": _num(args.get("budget_min")),
                            "budget_max": _num(args.get("budget_max")),
                            "preferred_time": _s(args.get("preferred_time")),
                        }
                    if args.get("reply_text"):
                        text_parts.append(str(args["reply_text"]))

        reply_text = "\n".join(t.strip() for t in text_parts if t and t.strip())[:LINE_TEXT_LIMIT]
        if not reply_text and not form:
            return None

        # บันทึกประวัติ — ฝั่ง assistant แนบ marker ไว้ให้โมเดลรู้ว่าส่งฟอร์มไปแล้ว
        saved_reply = reply_text
        if form:
            saved_reply += f"\n[ส่งปุ่มเปิดฟอร์มหมวด {form['category_slug']} พร้อมข้อมูลที่คุยไว้ให้ลูกค้าแล้ว]"
        await pool.execute(
            """INSERT INTO chat_history (line_user_id, role, content)
               VALUES ($1, 'user', $2), ($1, 'assistant', $3)""",
            line_user_id, user_text, saved_reply,
        )
        return {"text": reply_text, "form": form}
    except Exception:
        log.exception("AI chat ล้มเหลว — ถอยไปใช้ keyword matching")
        return None
