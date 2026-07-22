"""สร้างข้อความ LINE: การ์ดงาน (Flex), ปุ่มเปิด LIFF, quick reply เลือกหมวด"""
from urllib.parse import urlencode

from .config import settings
from .intent import CATEGORY_NAMES, SUBCATEGORIES, subcategories_of

GREEN = "#2BA84A"
NAVY = "#1E3A5F"
ORANGE = "#F7941D"


def liff_url(path: str = "") -> str:
    return f"https://liff.line.me/{settings.liff_id}{path}"


def openchat_invite(links: list[dict]) -> dict:
    """การ์ดปุ่มเข้ากลุ่มช่างประจำหมวด — ช่างกดปุ่มเดียวเข้ากลุ่มได้เลย
    (LINE ไม่มี API ดึงคนเข้ากลุ่ม ผู้ใช้ต้องกดยอมรับเอง)"""
    buttons = [
        {"type": "button", "style": "primary", "color": GREEN, "height": "sm", "margin": "sm",
         "action": {"type": "uri", "label": f"{l.get('icon') or '💬'} เข้ากลุ่ม{l['name_th']}"[:40],
                    "uri": l["openchat_url"]}}
        for l in links[:4]
    ]
    return {
        "type": "flex",
        "altText": "เชิญเข้ากลุ่มช่างเอิ้นได้",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                {"type": "text", "text": "เข้ากลุ่มช่างเอิ้นได้", "weight": "bold",
                 "size": "lg", "color": NAVY, "wrap": True},
                {"type": "text", "text": "กดปุ่มด้านล่างเพื่อเข้ากลุ่มรับงานประจำหมวดของคุณครับ "
                                         "งานใหม่จะแจ้งเข้ากลุ่มนี้",
                 "size": "sm", "color": "#68776C", "wrap": True},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": buttons},
        },
    }


def open_form_message(
    category_slug: str | None,
    subcategory_slug: str | None = None,
    description: str | None = None,
    tambon: str | None = None,
    budget_min: float | None = None,
    budget_max: float | None = None,
    preferred_time: str | None = None,
) -> dict:
    """ปุ่มเปิดฟอร์มประกาศงาน — เติมข้อมูลที่คุยกับ AI ไว้ให้ล่วงหน้า
    (ส่งผ่าน query string ให้หน้าเว็บกรอกลงฟอร์มอัตโนมัติ)"""
    name = CATEGORY_NAMES.get(category_slug, "ช่าง") if category_slug else "ช่าง"
    subcat = SUBCATEGORIES.get(subcategory_slug or "")
    headline = f"งานด่วน — {subcat['name']} ใช่ไหมครับ?" if subcat else f"เอิ้นหา{name}ใช่ไหมครับ?"
    btn_label = "📢 แจ้งงานด่วน" if subcat else f"📢 เอิ้นหา{name}"
    params: dict[str, str] = {}
    if category_slug:
        params["category"] = category_slug
    if subcategory_slug:
        params["sub"] = subcategory_slug
    if tambon:
        params["tambon"] = tambon[:40]
    if description:
        params["desc"] = description[:300]
    if budget_min:
        params["bmin"] = str(int(budget_min))
    if budget_max:
        params["bmax"] = str(int(budget_max))
    if preferred_time:
        params["when"] = preferred_time[:40]
    path = f"?{urlencode(params)}" if params else ""

    filled = [t for t in ("รายละเอียดงาน" if description else "",
                          f"ต.{tambon}" if tambon else "",
                          "งบประมาณ" if (budget_min or budget_max) else "") if t]
    sub = ("กรอก" + " • ".join(filled) + " ให้แล้ว กดตรวจดูอีกทีแล้วส่งได้เลยครับ"
           if filled else
           "กดปุ่มด้านล่าง กรอกรายละเอียดงานสั้นๆ เดี๋ยวช่างในตำบลของคุณจะเสนอราคามาให้เลือกครับ")
    return {
        "type": "flex",
        "altText": f"เอิ้นหา{name} — กรอกรายละเอียดงานได้เลย",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                {"type": "text", "text": headline, "weight": "bold",
                 "size": "lg", "color": NAVY, "wrap": True},
                {"type": "text", "text": sub, "size": "sm", "color": "#68776C", "wrap": True},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": GREEN, "height": "sm",
                 # LINE จำกัด label ปุ่มไว้ 20 ตัวอักษร — เกินแล้วยิงไม่ผ่าน
                 "action": {"type": "uri", "label": btn_label[:20], "uri": liff_url(path)}},
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


def subcategory_quick_reply(category_slug: str) -> dict | None:
    """หมวดที่มีงานย่อย (งานด่วน 24 ชม.) → ให้ลูกค้าจิ้มว่าด่วนเรื่องอะไร
    เพราะช่างรถไถกับช่างกุญแจคนละคนกัน ต้องรู้ก่อนถึงจะส่งงานให้ถูกคน"""
    subs = subcategories_of(category_slug)
    if not subs:
        return None
    items = [
        {"type": "action", "action": {
            "type": "postback", "label": f"{s['icon']} {s['name']}"[:20],
            "data": f"category={category_slug}&sub={slug}", "displayText": s["name"]}}
        for slug, s in subs.items()
    ]
    return {
        "type": "text",
        "text": "ด่วนเรื่องอะไรครับพี่? เลือกได้เลย 👇",
        "quickReply": {"items": items},
    }


def job_card(job: dict, category_name: str, tambon_name: str, bid_count: int = 0,
             sub_name: str | None = None) -> dict:
    """การ์ดงานส่งเข้ากลุ่มช่างตำบล — ไม่มีข้อมูลติดต่อลูกค้า"""
    if sub_name:  # งานด่วน — บอกให้ชัดว่าด่วนแบบไหน ช่างจะได้รู้ทันทีว่างานของตนไหม
        category_name = f"{category_name} • {sub_name}"
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
                            "uri": liff_url(f"/provider?job={job['id']}")}},
            ]},
        },
    }
