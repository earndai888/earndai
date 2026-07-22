"""กันบุคลิก "น้องเอิ้นได้" เพี้ยนกลับตอนแก้ prompt ในอนาคต"""
from app.ai_chat import SEND_FORM_TOOL, SYSTEM_PROMPT
from app.intent import CATEGORY_NAMES


def test_เป็นผู้ชาย_และเรียกผู้ใช้ว่าพี่():
    assert "ผู้ชาย" in SYSTEM_PROMPT
    assert '"พี่" เสมอ' in SYSTEM_PROMPT
    # สรรพนามแทนตัวเองที่อนุญาต
    for p in ("น้องเอิ้นได้", "หนู", "ผม"):
        assert p in SYSTEM_PROMPT


def test_ไม่มีสำนวนผู้หญิงแบบเดิมหลงเหลือ():
    for bad in ("ค่ะคุณป้า", "ได้เลยครับคุณลุง", "คุณยายขา"):
        assert bad not in SYSTEM_PROMPT


def test_มีกฎห้ามรับปากแทนช่าง():
    assert "ห้ามรับปากแทนช่าง" in SYSTEM_PROMPT
    assert "ห้ามสร้างข้อมูลขึ้นเองเด็ดขาด" in SYSTEM_PROMPT
    # ตัวอย่างคำที่ห้ามพูด ต้องถูกระบุไว้ให้โมเดลรู้
    for banned in ("ช่างถึงภายใน 30 นาที", "ช่างรับงานแน่นอน", "งานเสร็จวันนี้แน่นอน"):
        assert banned in SYSTEM_PROMPT


def test_มีแนวคิดชุมชน():
    assert "คนศรีสะเกษช่วยคนศรีสะเกษ" in SYSTEM_PROMPT
    assert "ช่างในพื้นที่ของพี่" in SYSTEM_PROMPT


def test_tool_ครอบคลุมหมวดงานนำร่องครบ():
    decl = SEND_FORM_TOOL.function_declarations[0]
    enum = decl.parameters.properties["category_slug"].enum
    assert set(enum) == set(CATEGORY_NAMES)
    assert len(enum) == 4
