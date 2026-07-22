"""กันนัดติดต่อ/จ่ายเงินนอกระบบ

ถ้าช่างแอบใส่เบอร์โทรหรือไอดีไลน์ในชื่อร้าน คำแนะนำตัว หรือข้อความเสนอราคา
ลูกค้าจะโทรไปตกลงกันเองแล้วโอนเงินตรง ซึ่งเอิ้นได้คุ้มครองให้ไม่ได้เลย
(ช่างทิ้งงาน = ลูกค้าเสียเงินฟรี / ลูกค้าเบี้ยว = ช่างทำฟรี)
"""
import re

_SEPARATORS = re.compile(r"[\s\-().]+")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_DIGIT_RUN = re.compile(r"\d+")
# "ไลน์ ชื่อไอดี" / "line id: xxxx" / "แอดไลน์ @xxxx"
_LINE_ID = re.compile(r"(ไลน์|line|ไอดี|id)\s*[:=]?\s*@?[a-z0-9._-]{4,}", re.IGNORECASE)


def _looks_like_phone(run: str) -> bool:
    """เบอร์ไทยขึ้นต้นด้วย 0 เสมอ (มือถือ 10 หลัก / เบอร์บ้าน 9 หลัก) หรือ +66 นำหน้า
    เช็คหลักขึ้นต้นด้วย ไม่งั้น "ล้างแอร์ 9000-24000 BTU" จะโดนหาว่าเป็นเบอร์"""
    if run.startswith("66"):        # +66 81 234 5678
        run = "0" + run[2:]
    return run.startswith("0") and len(run) in (9, 10)


def find_contact_leak(text: str | None) -> str | None:
    """คืนชนิดข้อมูลติดต่อที่เจอ (ไว้ใส่ในข้อความเตือน) หรือ None ถ้าสะอาด"""
    if not text:
        return None
    # ตัดตัวคั่นออกก่อน กันเขียนเลี่ยงแบบ 081-234-5678 / 08 1234 5678 / ๐๘๑...
    flat = _SEPARATORS.sub("", text.translate(_THAI_DIGITS))
    if any(_looks_like_phone(m.group()) for m in _DIGIT_RUN.finditer(flat)):
        return "เบอร์โทร"
    if _LINE_ID.search(text):
        return "ไอดีไลน์"
    return None


def message(kind: str, where: str) -> str:
    return (f"ห้ามใส่{kind}ใน{where}ครับ — ลูกค้าติดต่อและจ่ายเงินผ่านระบบเท่านั้น "
            "เพื่อให้เอิ้นได้คุ้มครองเงินให้ทั้งช่างและลูกค้าได้")
