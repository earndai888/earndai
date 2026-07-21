"""ใบ 50 ทวิ — หนังสือรับรองการหักภาษี ณ ที่จ่าย (มาตรา 50 ทวิ แห่งประมวลรัษฎากร)

สร้าง PDF ด้วย reportlab + ฟอนต์ไทย
- production (Docker): ติดตั้ง fonts-thai-tlwg ไว้แล้ว
- Windows dev: ใช้ Tahoma/Leelawadee ที่มีในเครื่อง
"""
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT = "ThaiFont"
FONT_BOLD = "ThaiFontBold"

# ไล่หาฟอนต์ไทยตามลำดับ (regular, bold ถ้ามี)
FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/tlwg/Sarabun.ttf", "/usr/share/fonts/truetype/tlwg/Sarabun-Bold.ttf"),
    ("/usr/share/fonts/truetype/tlwg/Garuda.ttf", "/usr/share/fonts/truetype/tlwg/Garuda-Bold.ttf"),
    ("/usr/share/fonts/truetype/tlwg/Loma.ttf", "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf"),
    ("C:/Windows/Fonts/leelawui.ttf", "C:/Windows/Fonts/leelawad.ttf"),
    ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahomabd.ttf"),
]

_registered = False


def _register_font() -> None:
    global _registered
    if _registered:
        return
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont(FONT, regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold if Path(bold).exists() else regular))
            _registered = True
            return
    raise RuntimeError(
        "ไม่พบฟอนต์ภาษาไทยสำหรับสร้าง PDF — ติดตั้ง fonts-thai-tlwg บนเซิร์ฟเวอร์")


# ── จำนวนเงินเป็นตัวอักษรไทย ──────────────────────────────

_DIGITS = "ศูนย์ หนึ่ง สอง สาม สี่ ห้า หก เจ็ด แปด เก้า".split()
_UNITS = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]


def _read_int(n: int) -> str:
    if n == 0:
        return "ศูนย์"
    if n >= 1_000_000:
        return _read_int(n // 1_000_000) + "ล้าน" + (_read_int(n % 1_000_000) if n % 1_000_000 else "")
    s = str(n)
    out = ""
    for i, ch in enumerate(s):
        d = int(ch)
        pos = len(s) - i - 1
        if d == 0:
            continue
        if pos == 1 and d == 1:
            out += "สิบ"
        elif pos == 1 and d == 2:
            out += "ยี่สิบ"
        elif pos == 0 and d == 1 and len(s) > 1:
            out += "เอ็ด"
        else:
            out += _DIGITS[d] + _UNITS[pos]
    return out


def baht_text(amount: Decimal | float) -> str:
    """123.45 → 'หนึ่งร้อยยี่สิบสามบาทสี่สิบห้าสตางค์'"""
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    baht = int(amount)
    satang = int((amount - baht) * 100)
    if satang == 0:
        return f"{_read_int(baht)}บาทถ้วน"
    return f"{_read_int(baht)}บาท{_read_int(satang)}สตางค์"


def _thai_date(d: date) -> str:
    months = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
              "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    return f"{d.day} {months[d.month]} {d.year + 543}"


# ── สร้าง PDF ────────────────────────────────────────────

def build_pdf(d: dict) -> bytes:
    """d: payer_name, payer_tax_id, payer_address, payee_name, payee_tax_id,
          payee_address, wht_no, pay_date(date), amount, tax, job_title"""
    _register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    L, R = 18 * mm, W - 18 * mm
    y = H - 16 * mm

    def txt(x, yy, s, size=10, bold=False):
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawString(x, yy, str(s))

    def center(yy, s, size=12, bold=True):
        c.setFont(FONT_BOLD if bold else FONT, size)
        c.drawCentredString(W / 2, yy, str(s))

    def line(yy, x1=None, x2=None):
        c.setLineWidth(0.4)
        c.line(x1 or L, yy, x2 or R, yy)

    # หัวเอกสาร
    c.setFont(FONT, 9)
    c.drawRightString(R, y, "ฉบับที่ 1 (สำหรับผู้ถูกหักภาษี ณ ที่จ่าย ใช้แนบพร้อมแบบแสดงรายการ)")
    y -= 8 * mm
    center(y, "หนังสือรับรองการหักภาษี ณ ที่จ่าย", 15)
    y -= 6 * mm
    center(y, "ตามมาตรา 50 ทวิ แห่งประมวลรัษฎากร", 11, bold=False)
    y -= 6 * mm
    c.setFont(FONT, 10)
    c.drawRightString(R, y, f"เล่มที่/เลขที่  {d['wht_no']}")
    y -= 5 * mm
    line(y)
    y -= 7 * mm

    # ผู้มีหน้าที่หักภาษี ณ ที่จ่าย
    txt(L, y, "ผู้มีหน้าที่หักภาษี ณ ที่จ่าย :", 10, bold=True)
    txt(L + 46 * mm, y, d["payer_name"], 10)
    y -= 5.5 * mm
    txt(L + 6 * mm, y, f"เลขประจำตัวผู้เสียภาษีอากร  {d.get('payer_tax_id') or '- ยังไม่ระบุ -'}", 10)
    y -= 5.5 * mm
    txt(L + 6 * mm, y, f"ที่อยู่  {d.get('payer_address') or '- ยังไม่ระบุ -'}", 10)
    y -= 8 * mm

    # ผู้ถูกหักภาษี ณ ที่จ่าย
    txt(L, y, "ผู้ถูกหักภาษี ณ ที่จ่าย :", 10, bold=True)
    txt(L + 46 * mm, y, d["payee_name"], 10)
    y -= 5.5 * mm
    txt(L + 6 * mm, y, f"เลขประจำตัวประชาชน  {d.get('payee_tax_id') or '- ยังไม่ระบุ -'}", 10)
    y -= 5.5 * mm
    txt(L + 6 * mm, y, f"ที่อยู่  {d.get('payee_address') or '- ยังไม่ระบุ -'}", 10)
    y -= 8 * mm

    # ตารางเงินได้
    line(y)
    y -= 6 * mm
    txt(L + 2 * mm, y, "ประเภทเงินได้พึงประเมินที่จ่าย", 10, bold=True)
    txt(L + 105 * mm, y, "วัน เดือน ปี ที่จ่าย", 10, bold=True)
    c.setFont(FONT_BOLD, 10)
    c.drawRightString(R - 26 * mm, y, "จำนวนเงินที่จ่าย")
    c.drawRightString(R - 2 * mm, y, "ภาษีที่หักนำส่ง")
    y -= 3 * mm
    line(y)
    y -= 6.5 * mm

    txt(L + 2 * mm, y, "5. ค่าจ้างทำของ / ค่าบริการ", 10)
    txt(L + 105 * mm, y, _thai_date(d["pay_date"]), 10)
    c.setFont(FONT, 10)
    c.drawRightString(R - 26 * mm, y, f"{d['amount']:,.2f}")
    c.drawRightString(R - 2 * mm, y, f"{d['tax']:,.2f}")
    y -= 5 * mm
    txt(L + 6 * mm, y, f"({d.get('job_title', '')[:70]})", 9)
    y -= 5 * mm
    line(y)
    y -= 6.5 * mm

    c.setFont(FONT_BOLD, 10)
    c.drawString(L + 2 * mm, y, "รวมเงินที่จ่ายและภาษีที่หักนำส่ง")
    c.drawRightString(R - 26 * mm, y, f"{d['amount']:,.2f}")
    c.drawRightString(R - 2 * mm, y, f"{d['tax']:,.2f}")
    y -= 3 * mm
    line(y)
    y -= 7 * mm
    txt(L + 2 * mm, y, f"รวมเงินภาษีที่หักนำส่ง (ตัวอักษร)   {baht_text(d['tax'])}", 10)
    y -= 9 * mm

    # ผู้จ่ายเงิน
    txt(L, y, "ผู้จ่ายเงิน       ☑ หักภาษี ณ ที่จ่าย        ☐ ออกภาษีให้ตลอดไป        ☐ ออกภาษีให้ครั้งเดียว", 10)
    y -= 12 * mm

    txt(L, y, "ขอรับรองว่าข้อความและตัวเลขดังกล่าวข้างต้นถูกต้องตรงกับความจริงทุกประการ", 10)
    y -= 16 * mm
    c.setFont(FONT, 10)
    c.drawCentredString(W - 55 * mm, y, "ลงชื่อ ..........................................................")
    y -= 6 * mm
    c.drawCentredString(W - 55 * mm, y, "ผู้จ่ายเงิน")
    y -= 6 * mm
    c.drawCentredString(W - 55 * mm, y, f"วันที่ {_thai_date(d['pay_date'])}")

    c.setFont(FONT, 8)
    c.drawCentredString(W / 2, 12 * mm,
                        "เอกสารนี้ออกโดยระบบเอิ้นได้ · โปรดตรวจสอบความถูกต้องกับผู้ทำบัญชีก่อนใช้ยื่นภาษี")
    c.showPage()
    c.save()
    return buf.getvalue()
