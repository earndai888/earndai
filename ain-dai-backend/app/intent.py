"""Intent ชั้นที่ 1: keyword matching ภาษาไทย → หมวดงาน

คืน (slug, confidence) — confidence ต่ำกว่า THRESHOLD ให้ bot ส่ง quick reply
ให้ลูกค้าเลือกหมวดเอง (ชั้นที่ 3) แทนการเดา
ชั้นที่ 2 (classifier/LLM) เสียบเพิ่มได้ที่ classify() ภายหลัง
"""
from dataclasses import dataclass

THRESHOLD = 0.6

# คำหลัก → (slug, น้ำหนัก) — คำเฉพาะเจาะจงให้น้ำหนักสูงกว่าคำกว้าง
KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "electrician": [
        ("ช่างไฟ", 1.0), ("ไฟฟ้า", 0.9), ("ปลั๊ก", 0.9), ("เบรกเกอร์", 1.0),
        ("ไฟดับ", 0.9), ("ไฟช็อต", 1.0), ("ไฟรั่ว", 1.0), ("สายไฟ", 0.9),
        ("หลอดไฟ", 0.9), ("มิเตอร์ไฟ", 0.9), ("ติดตั้งไฟ", 0.9),
    ],
    "plumber": [
        ("ประปา", 1.0), ("ท่อน้ำ", 1.0), ("ท่อตัน", 1.0), ("ท่อแตก", 1.0),
        ("ก๊อกน้ำ", 1.0), ("น้ำรั่ว", 0.9), ("น้ำไม่ไหล", 0.9), ("ส้วมตัน", 1.0),
        ("ชักโครก", 0.9), ("ปั๊มน้ำ", 0.9), ("แท้งค์น้ำ", 0.9),
    ],
    "ac-cleaning": [
        ("ล้างแอร์", 1.0), ("แอร์", 0.8), ("แอร์ไม่เย็น", 1.0), ("ติดตั้งแอร์", 0.9),
        ("ย้ายแอร์", 1.0), ("เติมน้ำยาแอร์", 1.0), ("ซ่อมแอร์", 1.0),
    ],
    "appliance": [
        ("ตู้เย็น", 1.0), ("เครื่องซักผ้า", 1.0), ("ไมโครเวฟ", 1.0),
        ("พัดลม", 0.9), ("ทีวี", 0.8), ("หม้อหุงข้าว", 0.9), ("เครื่องใช้ไฟฟ้า", 0.9),
    ],
    "housekeeping": [
        ("แม่บ้าน", 1.0), ("ทำความสะอาด", 1.0), ("กวาดบ้าน", 0.9), ("ถูบ้าน", 0.9),
        ("ล้างห้องน้ำ", 0.9), ("ซักผ้า", 0.7), ("รีดผ้า", 0.8), ("เก็บกวาด", 0.8),
    ],
    "transport": [
        ("รถรับจ้าง", 1.0), ("ขนของ", 1.0), ("ย้ายบ้าน", 1.0), ("ย้ายของ", 1.0),
        ("รถกระบะ", 0.9), ("ขนย้าย", 1.0), ("ส่งของ", 0.8),
    ],
    "gardening": [
        ("ตัดหญ้า", 1.0), ("ตัดต้นไม้", 1.0), ("จัดสวน", 1.0), ("ดายหญ้า", 1.0),
        ("หญ้ารก", 1.0), ("ตัดกิ่ง", 0.9), ("สวน", 0.6), ("ต้นไม้", 0.6),
        ("ถางหญ้า", 1.0), ("ตัดแต่งกิ่ง", 1.0),
    ],
    "handyman": [
        ("ช่างซ่อม", 0.9), ("ซ่อมหลังคา", 1.0), ("หลังคารั่ว", 1.0), ("ซ่อมประตู", 1.0),
        ("ซ่อมรั้ว", 1.0), ("ทาสี", 0.9), ("ปูกระเบื้อง", 1.0), ("ซ่อมบ้าน", 0.9),
        ("เชื่อมเหล็ก", 1.0), ("มุงหลังคา", 1.0),
    ],
}

CATEGORY_NAMES = {
    "electrician": "ช่างไฟฟ้า", "plumber": "ช่างประปา", "ac-cleaning": "ล้างแอร์/ซ่อมแอร์",
    "appliance": "ซ่อมเครื่องใช้ไฟฟ้า", "housekeeping": "แม่บ้าน", "transport": "รถรับจ้าง",
    "gardening": "ตัดหญ้า-จัดสวน", "handyman": "ช่างซ่อมทั่วไป",
}


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
