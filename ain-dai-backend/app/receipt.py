"""ใบเสร็จรับเงิน (หลักฐานการชำระเข้าบัญชีกลาง/escrow)

สร้าง PDF ด้วย reportlab ใช้ฟอนต์ไทยร่วมกับ wht.py
ส่งให้ลูกค้าทาง LINE (ปุ่มดาวน์โหลด) และอีเมล (ถ้ามี)
"""
import io
from datetime import date

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .config import settings
from .wht import FONT, FONT_BOLD, _register_font, _thai_date, baht_text

NAVY = (0.118, 0.227, 0.373)
GREEN = (0.169, 0.541, 0.290)


def build_pdf(d: dict) -> bytes:
    """d: receipt_no, pay_date(date), customer_name, job_title, provider_name, amount"""
    _register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    W, H = A5
    L, R = 16 * mm, W - 16 * mm
    y = H - 18 * mm

    def txt(x, yy, s, size=11, bold=False, color=(0, 0, 0)):
        c.setFillColorRGB(*color)
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawString(x, yy, str(s))

    def right(x, yy, s, size=11, bold=False, color=(0, 0, 0)):
        c.setFillColorRGB(*color)
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawRightString(x, yy, str(s))

    # หัวกระดาษ
    txt(L, y, settings.company_name or "เอิ้นได้", 16, bold=True, color=NAVY)
    right(R, y, "ใบเสร็จรับเงิน", 15, bold=True, color=NAVY)
    y -= 6 * mm
    right(R, y, "RECEIPT", 9, color=(0.4, 0.4, 0.4))
    if settings.company_tax_id:
        txt(L, y, f"เลขประจำตัวผู้เสียภาษี {settings.company_tax_id}", 8, color=(0.4, 0.4, 0.4))
    y -= 5 * mm
    if settings.company_address:
        txt(L, y, settings.company_address[:70], 8, color=(0.4, 0.4, 0.4))
        y -= 6 * mm
    else:
        y -= 2 * mm

    c.setStrokeColorRGB(*GREEN)
    c.setLineWidth(1.2)
    c.line(L, y, R, y)
    y -= 9 * mm

    txt(L, y, "เลขที่ใบเสร็จ", 10, color=(0.4, 0.4, 0.4))
    right(R, y, f"RCP-{d['receipt_no']:06d}", 11, bold=True)
    y -= 6 * mm
    txt(L, y, "วันที่", 10, color=(0.4, 0.4, 0.4))
    right(R, y, _thai_date(d["pay_date"]), 11)
    y -= 9 * mm

    for label, value in (("ได้รับเงินจาก", d.get("customer_name") or "-"),
                         ("สำหรับงาน", d.get("job_title") or "-"),
                         ("ผู้ให้บริการ", d.get("provider_name") or "-")):
        txt(L, y, label, 10, color=(0.4, 0.4, 0.4))
        txt(L + 32 * mm, y, value, 11)
        y -= 6.5 * mm

    y -= 3 * mm
    c.setFillColorRGB(0.91, 0.96, 0.925)
    c.rect(L, y - 12 * mm, R - L, 15 * mm, fill=1, stroke=0)
    txt(L + 4 * mm, y - 3 * mm, "จำนวนเงิน", 11, color=NAVY)
    right(R - 4 * mm, y - 4 * mm, f"{float(d['amount']):,.2f} บาท", 16, bold=True, color=GREEN)
    txt(L + 4 * mm, y - 9 * mm, f"({baht_text(d['amount'])})", 9, color=(0.3, 0.3, 0.3))
    y -= 20 * mm

    txt(L, y, "หมายเหตุ: เงินจำนวนนี้พักไว้ในบัญชีกลางของเอิ้นได้ (escrow)", 8.5, color=(0.4, 0.4, 0.4))
    y -= 4.5 * mm
    txt(L, y, "จะโอนให้ผู้ให้บริการเมื่องานเสร็จและลูกค้ายืนยันความพอใจแล้ว", 8.5, color=(0.4, 0.4, 0.4))
    y -= 10 * mm
    txt(L, y, "ขอบคุณที่ใช้บริการเอิ้นได้ — คนศรีสะเกษช่วยคนศรีสะเกษ 🙏", 9, color=GREEN)

    c.showPage()
    c.save()
    return buf.getvalue()
