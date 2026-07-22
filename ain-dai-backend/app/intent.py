"""Intent ชั้นที่ 1: keyword matching ภาษาไทย → หมวดงาน

คืน (slug, confidence) — confidence ต่ำกว่า THRESHOLD ให้ bot ส่ง quick reply
ให้ลูกค้าเลือกหมวดเอง (ชั้นที่ 3) แทนการเดา
ชั้นที่ 2 (classifier/LLM) เสียบเพิ่มได้ที่ classify() ภายหลัง
"""
from dataclasses import dataclass

THRESHOLD = 0.6

# คำหลัก → (slug, น้ำหนัก) — คำเฉพาะเจาะจงให้น้ำหนักสูงกว่าคำกว้าง
# นำร่องอำเภอกันทรลักษ์ 4 หมวด
KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "ac-cleaning": [
        ("ล้างแอร์", 1.0), ("แอร์", 0.8), ("แอร์ไม่เย็น", 1.0), ("ติดตั้งแอร์", 0.9),
        ("ย้ายแอร์", 1.0), ("เติมน้ำยาแอร์", 1.0), ("ซ่อมแอร์", 1.0),
        ("แอร์เสีย", 1.0), ("แอร์มีน้ำหยด", 1.0), ("แอร์เหม็น", 0.9),
    ],
    "gardening": [
        ("ตัดหญ้า", 1.0), ("ตัดต้นไม้", 1.0), ("จัดสวน", 1.0), ("ดายหญ้า", 1.0),
        ("หญ้ารก", 1.0), ("ตัดกิ่ง", 0.9), ("สวน", 0.6), ("ต้นไม้", 0.6),
        ("ถางหญ้า", 1.0), ("ตัดแต่งกิ่ง", 1.0), ("ดูแลสวน", 0.9), ("รดน้ำต้นไม้", 0.9),
    ],
    "housekeeping": [
        ("แม่บ้าน", 1.0), ("ทำความสะอาด", 1.0), ("กวาดบ้าน", 0.9), ("ถูบ้าน", 0.9),
        ("ล้างห้องน้ำ", 0.9), ("ซักผ้า", 0.7), ("รีดผ้า", 0.8), ("เก็บกวาด", 0.8),
        ("ทำความสะอาดบ้าน", 1.0), ("ล้างจาน", 0.7),
    ],
    "emergency": [
        ("ฉุกเฉิน", 1.0), ("ด่วน", 0.9), ("เร่งด่วน", 1.0), ("กลางดึก", 0.9),
        ("กลางคืน", 0.8), ("24ชม", 1.0), ("เดี๋ยวนี้", 0.8), ("ตอนนี้เลย", 0.8),
    ],
}

CATEGORY_NAMES = {
    "ac-cleaning": "ช่างแอร์",
    "gardening": "งานสวน/ตัดหญ้า",
    "housekeeping": "แม่บ้าน",
    "emergency": "งานด่วน 24 ชม.",
}

# ── งานด่วน 24 ชม. แยกเป็น 4 กลุ่มย่อย ────────────────────
# ช่างคนละแบบกันสิ้นเชิง (ช่างรถไถ ≠ ช่างกุญแจ) จึงต้องแยกเพื่อส่งงานให้ถูกคน
# examples = ตัวอย่างที่แสดงบนหน้าเว็บ, keywords = ใช้จับหมวดจากข้อความแชท
SUBCATEGORIES: dict[str, dict] = {
    "emg-agri": {
        "category": "emergency",
        "name": "รถไถ/เครื่องมือเกษตรเสียกลางไร่",
        "icon": "🚜",
        "examples": [
            "รถไถ / รถเกี่ยวข้าว / รถไถเดินตาม เครื่องดับ คลัตช์ไหม้ สายพานขาด",
            "เครื่องสูบน้ำเข้าไร่-นาเสีย ปั๊มน้ำบาดาลไม่ทำงาน",
            "โดรนเกษตร / เครื่องพ่นยา หัวฉีดตัน ระบบไฟมีปัญหา",
            "เครื่องตัดหญ้าการเกษตร / เลื่อยยนต์ ชำรุด",
        ],
        "keywords": [
            ("รถไถ", 1.0), ("รถเกี่ยว", 1.0), ("รถเกี่ยวข้าว", 1.0), ("ไถเดินตาม", 1.0),
            ("คลัตช์ไหม้", 1.0), ("สายพานขาด", 0.9), ("เครื่องดับ", 0.8),
            ("เครื่องสูบน้ำ", 1.0), ("ปั๊มน้ำบาดาล", 1.0), ("สูบน้ำเข้านา", 1.0),
            ("โดรนเกษตร", 1.0), ("เครื่องพ่นยา", 1.0), ("หัวฉีดตัน", 0.9),
            ("เลื่อยยนต์", 1.0), ("เครื่องตัดหญ้าเสีย", 1.0), ("เครื่องตัดหญ้าดับ", 1.0),
            ("เครื่องเกษตร", 1.0), ("กลางไร่", 0.8), ("กลางนา", 0.8),
        ],
    },
    "emg-auto": {
        "category": "emergency",
        "name": "รถเสียกลางทาง",
        "icon": "🚗",
        "examples": [
            "ปะยางนอกสถานที่ — รถยนต์ / มอเตอร์ไซค์ / รถการเกษตร ยางรั่ว ยางแตก",
            "พ่วงแบต / เปลี่ยนแบตด่วน รถสตาร์ทไม่ติด",
            "น้ำมันหมดกลางทาง ส่งน้ำมันฉุกเฉิน",
        ],
        "keywords": [
            ("ปะยาง", 1.0), ("ยางแตก", 1.0), ("ยางรั่ว", 1.0), ("ยางแบน", 1.0),
            ("พ่วงแบต", 1.0), ("แบตหมด", 1.0), ("เปลี่ยนแบต", 1.0), ("สตาร์ทไม่ติด", 1.0),
            ("รถเสีย", 1.0), ("น้ำมันหมด", 1.0), ("รถดับกลางทาง", 1.0), ("เข็นรถ", 0.8),
        ],
    },
    "emg-lock": {
        "category": "emergency",
        "name": "กุญแจ / เข้าบ้าน-เข้ารถไม่ได้",
        "icon": "🔑",
        "examples": [
            "สะเดาะกุญแจบ้าน / รถ — ลืมกุญแจไว้ข้างใน กุญแจหักคารู",
            "เปลี่ยนลูกบิด / เปลี่ยนระบบล็อกด่วน",
        ],
        "keywords": [
            ("สะเดาะกุญแจ", 1.0), ("กุญแจหาย", 1.0), ("ลืมกุญแจ", 1.0), ("กุญแจหัก", 1.0),
            ("เข้าบ้านไม่ได้", 1.0), ("ลูกบิด", 1.0), ("เปลี่ยนกุญแจ", 1.0),
            ("ช่างกุญแจ", 1.0), ("ล็อกรถ", 0.9), ("กุญแจติดในรถ", 1.0),
        ],
    },
    "emg-home": {
        "category": "emergency",
        "name": "ไฟ / น้ำ / ท่อ ในบ้าน",
        "icon": "⚡",
        "examples": [
            "ไฟช็อต ไฟดับทั้งบ้าน เบรกเกอร์ตัด ไฟรั่ว สายไฟไหม้",
            "ท่อประปาแตก น้ำทะลัก ปั๊มน้ำไม่ตัด",
            "ส้วมตัน ท่อตัน ใช้ห้องน้ำไม่ได้",
        ],
        "keywords": [
            ("ไฟช็อต", 1.0), ("ไฟดับ", 1.0), ("ไฟรั่ว", 1.0), ("เบรกเกอร์", 1.0),
            ("สายไฟไหม้", 1.0), ("ไฟไหม้สายไฟ", 1.0),
            ("ท่อแตก", 1.0), ("ท่อประปาแตก", 1.0), ("น้ำทะลัก", 1.0), ("น้ำรั่ว", 0.9),
            ("ปั๊มน้ำไม่ตัด", 1.0), ("ส้วมตัน", 1.0), ("ท่อตัน", 1.0), ("ชักโครกตัน", 1.0),
        ],
    },
}

# กลุ่มย่อยของงานด่วนก็คือคำหลักของหมวด emergency ด้วย
# (ไม่งั้น "รถไถเสีย" จะจับหมวดไม่ได้เลย เพราะไม่มีคำว่า "ด่วน/ฉุกเฉิน")
for _sub in SUBCATEGORIES.values():
    KEYWORDS[_sub["category"]].extend(_sub["keywords"])


def subcategories_of(category_slug: str) -> dict[str, dict]:
    return {s: v for s, v in SUBCATEGORIES.items() if v["category"] == category_slug}


@dataclass(frozen=True)
class IntentResult:
    slug: str | None
    confidence: float
    matched: list[str]

    @property
    def confident(self) -> bool:
        return self.slug is not None and self.confidence >= THRESHOLD


def classify(text: str) -> IntentResult:
    """ชั้นที่ 1: keyword matching. คะแนนหมวด = น้ำหนักคำที่เจอสูงสุด + โบนัสคำเสริม"""
    t = text.strip().lower().replace(" ", "")
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for slug, kws in KEYWORDS.items():
        found = [(kw, w) for kw, w in kws if kw.replace(" ", "") in t]
        if found:
            found.sort(key=lambda x: -x[1])
            best = found[0][1]
            bonus = min(0.15 * (len(found) - 1), 0.3)
            scores[slug] = min(best + bonus, 1.0)
            hits[slug] = [kw for kw, _ in found]
    if not scores:
        return IntentResult(None, 0.0, [])
    top = max(scores, key=lambda s: scores[s])
    ranked = sorted(scores.values(), reverse=True)
    # ถ้าสองหมวดคะแนนสูสีมาก ให้ลดความมั่นใจ → ระบบจะถามกลับ
    ambiguous = len(ranked) > 1 and (ranked[0] - ranked[1]) < 0.15 and ranked[0] < 1.0
    conf = scores[top] * (0.5 if ambiguous else 1.0)
    return IntentResult(top, round(conf, 2), hits[top])


def classify_sub(text: str, category_slug: str | None = None) -> str | None:
    """งานด่วนเป็นแบบไหน — คืน slug กลุ่มย่อย หรือ None ถ้าเดาไม่ได้
    (category_slug ใส่มาเพื่อจำกัดว่าหากลุ่มย่อยเฉพาะในหมวดนั้น)"""
    t = text.strip().lower().replace(" ", "")
    best, best_score = None, 0.0
    for slug, sub in SUBCATEGORIES.items():
        if category_slug and sub["category"] != category_slug:
            continue
        found = [w for kw, w in sub["keywords"] if kw.replace(" ", "") in t]
        if found and max(found) > best_score:
            best, best_score = slug, max(found)
    return best
