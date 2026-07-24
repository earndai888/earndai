"""สร้างข้อความ LINE: การ์ดงาน (Flex), ปุ่มเปิด LIFF, quick reply เลือกหมวด"""
from urllib.parse import urlencode

from .config import settings
from .intent import CATEGORY_NAMES, SUBCATEGORIES, subcategories_of

GREEN = "#2BA84A"
NAVY = "#1E3A5F"
ORANGE = "#F7941D"


def liff_url(path: str = "") -> str:
    return f"https://liff.line.me/{settings.liff_id}{path}"


def public_url(path: str) -> str | None:
    """ลิงก์ไฟล์บนเซิร์ฟเวอร์เรา (ให้ LINE โหลดรูป QR) — None ถ้ายังไม่ตั้งโดเมน"""
    base = settings.public_base_url.rstrip("/")
    return f"{base}{path}" if base else None


def bid_card(bid: dict, provider: dict, job_title: str) -> dict:
    """การ์ดข้อเสนอช่างที่ push เข้าแชทลูกค้า — กดเลือกช่างได้เลยในแชท"""
    stars = "★" * int(round(provider.get("rating_avg") or 0))
    rating = (f"{stars or '☆'} {float(provider['rating_avg']):.1f} "
              f"({provider['rating_count']} รีวิว)" if provider.get("rating_count")
              else "ช่างใหม่ ยังไม่มีรีวิว")
    rows = [
        {"type": "text", "text": "🔨 มีช่างเสนอราคา", "size": "sm", "color": GREEN, "weight": "bold"},
        {"type": "text", "text": provider["display_name"], "weight": "bold", "size": "lg",
         "color": NAVY, "wrap": True},
        {"type": "text", "text": rating, "size": "sm", "color": "#68776C"},
        {"type": "text", "text": f"💰 {int(bid['price']):,} บาท", "size": "xl",
         "color": ORANGE, "weight": "bold", "margin": "sm"},
    ]
    if bid.get("message"):
        rows.append({"type": "text", "text": f"💬 {bid['message']}", "size": "sm",
                     "color": NAVY, "wrap": True, "margin": "sm"})
    if bid.get("available_at"):
        rows.append({"type": "text", "text": f"🗓 ว่าง {bid['available_at']}", "size": "sm",
                     "color": "#68776C"})
    return {
        "type": "flex",
        "altText": f"ช่าง {provider['display_name']} เสนอ {int(bid['price']):,} บาท สำหรับ {job_title}",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "xs", "contents": rows},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": GREEN, "height": "sm",
                 "action": {"type": "postback", "label": "✅ เลือกช่างคนนี้",
                            "data": f"a=pick&job={bid['job_id']}&bid={bid['id']}",
                            "displayText": f"เลือกช่าง {provider['display_name']}"}},
            ]},
        },
    }


def payment_card(payment_id: str, amount, provider_name: str, qr_path: str) -> dict:
    """การ์ดจ่ายเงินในแชท — รูป QR PromptPay + ปุ่ม 'ฉันโอนแล้ว'"""
    qr = public_url(qr_path)
    body = [
        {"type": "text", "text": "🛡️ จ่ายผ่านกระเป๋ากลาง (escrow)", "size": "sm",
         "color": GREEN, "weight": "bold"},
        {"type": "text", "text": f"จ้าง {provider_name}", "weight": "bold", "size": "md",
         "color": NAVY, "wrap": True},
        {"type": "text", "text": f"{int(amount):,} บาท", "size": "xxl", "weight": "bold",
         "color": ORANGE, "align": "center", "margin": "md"},
        {"type": "text",
         "text": "เงินพักในบัญชีกลาง งานเสร็จและพี่กดยืนยันแล้วเงินถึงจะโอนให้ช่าง "
                 "โอนแล้วกดปุ่มด้านล่างได้เลยครับ",
         "size": "xs", "color": "#68776C", "wrap": True, "margin": "md"},
    ]
    bubble = {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "contents": body},
        "footer": {"type": "box", "layout": "vertical", "contents": [
            {"type": "button", "style": "primary", "color": NAVY, "height": "sm",
             "action": {"type": "postback", "label": "✅ ฉันโอนแล้ว",
                        "data": f"a=paid&pid={payment_id}", "displayText": "ฉันโอนเงินแล้ว"}},
        ]},
    }
    if qr:   # LINE โหลดรูปได้ต่อเมื่อ public_base_url เป็น https จริง
        bubble["hero"] = {"type": "image", "url": qr, "size": "full",
                          "aspectRatio": "1:1", "aspectMode": "fit",
                          "backgroundColor": "#FFFFFF"}
    return {"type": "flex", "altText": f"ชำระเงินจ้าง {provider_name} {int(amount):,} บาท",
            "contents": bubble}


def job_done_card(job_id: str, job_title: str) -> dict:
    """ช่างส่งงาน → การ์ดให้ลูกค้ากดยืนยันในแชท"""
    return {
        "type": "flex",
        "altText": f"ช่างส่งงาน {job_title} แล้ว กดยืนยันได้เลย",
        "contents": {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                {"type": "text", "text": "✅ ช่างส่งงานแล้ว", "size": "sm", "color": GREEN,
                 "weight": "bold"},
                {"type": "text", "text": job_title, "weight": "bold", "size": "md",
                 "color": NAVY, "wrap": True},
                {"type": "text",
                 "text": "ตรวจงานแล้วถ้าพอใจ กดยืนยันเพื่อปล่อยเงินให้ช่างครับ "
                         "(ถ้าไม่กดภายใน 24 ชม. ระบบยืนยันให้อัตโนมัติ)",
                 "size": "xs", "color": "#68776C", "wrap": True},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": GREEN, "height": "sm",
                 "action": {"type": "postback", "label": "👍 ยืนยัน พอใจงาน",
                            "data": f"a=confirm&job={job_id}", "displayText": "ยืนยันว่าพอใจงาน"}},
            ]},
        },
    }


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
