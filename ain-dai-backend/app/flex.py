"""สร้างข้อความ LINE: การ์ดงาน (Flex), ปุ่มเปิด LIFF, quick reply เลือกหมวด"""
from .config import settings
from .intent import CATEGORY_NAMES

GREEN = "#2BA84A"
NAVY = "#1E3A5F"
ORANGE = "#F7941D"


def liff_url(path: str = "") -> str:
    return f"https://liff.line.me/{settings.liff_id}{path}"


def open_form_message(category_slug: str | None) -> dict:
    """ปุ่มเปิดฟอร์มประกาศงาน (prefill หมวดถ้ารู้แล้ว)"""
    name = CATEGORY_NAMES.get(category_slug, "ช่าง") if category_slug else "ช่าง"
    path = f"?category={category_slug}" if category_slug else ""
    return {
        "type": "flex",
        "altText": f"เอิ้นหา{name} — กรอกรายละเอียดงานได้เลย",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                {"type": "text", "text": f"เอิ้นหา{name}ใช่ไหมครับ?", "weight": "bold",
                 "size": "lg", "color": NAVY, "wrap": True},
                {"type": "text", "text": "กดปุ่มด้านล่าง กรอกรายละเอียดงานสั้นๆ เดี๋ยวช่างในตำบลของคุณจะเสนอราคามาให้เลือกครับ",
                 "size": "sm", "color": "#68776C", "wrap": True},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": GREEN, "height": "sm",
                 "action": {"type": "uri", "label": f"📢 เอิ้นหา{name}", "uri": liff_url(path)}},
            ]},
        },
    }


def category_quick_reply() -> dict:
    """intent ไม่มั่นใจ → ให้ลูกค้าจิ้มเลือกหมวดเอง"""
    items = [
        {"type": "action", "action": {"type": "postback", "label": name[:20],
         "data": f"category={slug}", "displayText": name}}
        for slug, name in list(CATEGORY_NAMES.items())[:10]
    ]
    return {
        "type": "text",
        "text": "ต้องการช่างด้านไหนครับ? เลือกได้เลย 👇",
        "quickReply": {"items": items},
    }


def job_card(job: dict, category_name: str, tambon_name: str, bid_count: int = 0) -> dict:
    """การ์ดงานส่งเข้ากลุ่มช่างตำบล — ไม่มีข้อมูลติดต่อลูกค้า"""
    budget = ""
    if job.get("budget_min") or job.get("budget_max"):
        budget = f"งบ {int(job.get('budget_min') or 0):,}–{int(job.get('budget_max') or 0):,} บาท"
    when = " ".join(filter(None, [str(job.get("preferred_date") or ""), job.get("preferred_time") or ""]))
    rows = [
        {"type": "text", "text": f"🔔 งานใหม่ • {category_name}", "weight": "bold", "size": "md", "color": GREEN},
        {"type": "text", "text": job["title"], "weight": "bold", "size": "lg", "color": NAVY, "wrap": True},
        {"type": "text", "text": (job.get("description") or "")[:120], "size": "sm", "color": "#68776C", "wrap": True},
        {"type": "text", "text": f"📍 ต.{tambon_name}   🗓 {when}", "size": "sm", "color": NAVY},
    ]
    if budget:
        rows.append({"type": "text", "text": f"💰 {budget}", "size": "sm", "color": ORANGE, "weight": "bold"})
    return {
        "type": "flex",
        "altText": f"งานใหม่: {job['title']} (ต.{tambon_name})",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": NAVY, "height": "sm",
                 "action": {"type": "uri", "label": "💵 เสนอราคางานนี้",
                            "uri": liff_url(f"?job={job['id']}&view=bid")}},
            ]},
        },
    }
