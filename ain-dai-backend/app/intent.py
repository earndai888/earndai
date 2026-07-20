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
    "emergency": "งานฉุกเฉิน 24 ชม.",
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
