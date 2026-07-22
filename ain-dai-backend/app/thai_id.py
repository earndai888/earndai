"""ตรวจเลขบัตรประชาชนไทยและเบอร์โทร — ใช้ตอนช่างสมัคร

เลขบัตร 13 หลักมีหลักตรวจสอบ (check digit) ในตัว พิมพ์ผิดจับได้ทันที
ไม่ต้องรอแอดมินมานั่งไล่ดูทีหลัง
"""
import re


def normalize_id(value: str) -> str:
    """ตัดขีด/ช่องว่างออก เหลือแต่ตัวเลข"""
    return re.sub(r"\D", "", value or "")


def valid_national_id(value: str) -> bool:
    """13 หลัก + หลักสุดท้ายต้องตรงกับผลรวมถ่วงน้ำหนัก (mod 11)"""
    digits = normalize_id(value)
    if len(digits) != 13 or digits[0] == "0":
        return False
    total = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
    return (11 - total % 11) % 10 == int(digits[12])


def format_id(value: str) -> str:
    """1234567890123 → 1-2345-67890-12-3 (รูปแบบบนบัตร)"""
    d = normalize_id(value)
    if len(d) != 13:
        return value
    return f"{d[0]}-{d[1:5]}-{d[5:10]}-{d[10:12]}-{d[12]}"


def mask_id(value: str) -> str:
    """โชว์แค่ 4 ตัวท้าย — ใช้ตอนส่งกลับให้เจ้าตัวดูว่ากรอกไว้แล้ว"""
    d = normalize_id(value)
    return f"x-xxxx-xxxxx-xx-{d[-1]}" if len(d) == 13 else ""


def normalize_phone(value: str) -> str | None:
    """รับ 0812345678 / 081-234-5678 / +66812345678 → 0812345678
    คืน None ถ้าไม่ใช่เบอร์มือถือหรือเบอร์บ้านไทย"""
    d = re.sub(r"\D", "", value or "")
    if d.startswith("66") and len(d) == 11:      # +66 81 234 5678
        d = "0" + d[2:]
    if len(d) == 10 and d.startswith("0"):        # มือถือ 08x/09x/06x
        return d
    if len(d) == 9 and d.startswith("0"):         # เบอร์บ้าน 045-xxxxxx
        return d
    return None


def valid_full_name(value: str) -> bool:
    """ต้องมีทั้งชื่อและนามสกุล (อย่างน้อย 2 คำ) — ใช้ออกใบ 50 ทวิ"""
    parts = [p for p in (value or "").strip().split() if len(p) >= 2]
    return len(parts) >= 2
