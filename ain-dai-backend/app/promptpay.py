"""สร้าง QR PromptPay จริงตามมาตรฐาน EMVCo (Thai QR Payment)
รองรับเบอร์มือถือ (10 หลัก) และเลขบัตรประชาชน/tax id (13 หลัก)"""
import io

import qrcode


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _crc16(data: str) -> str:
    """CRC-16/CCITT-FALSE (init 0xFFFF, poly 0x1021) — ตามสเปค EMVCo"""
    crc = 0xFFFF
    for byte in data.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def payload(promptpay_id: str, amount: float | None = None) -> str:
    pid = "".join(ch for ch in promptpay_id if ch.isdigit())
    if len(pid) == 13:  # เลขบัตรประชาชน / เลขผู้เสียภาษี
        proxy = _tlv("02", pid)
    else:  # เบอร์มือถือ → 0066 + ตัดศูนย์นำ
        proxy = _tlv("01", "0066" + pid.lstrip("0"))
    merchant = _tlv("00", "A000000677010111") + proxy
    data = (
        _tlv("00", "01")                              # payload format
        + _tlv("01", "12" if amount else "11")        # dynamic/static QR
        + _tlv("29", merchant)                        # merchant account info
        + _tlv("53", "764")                           # สกุลเงิน THB
    )
    if amount:
        data += _tlv("54", f"{amount:.2f}")
    data += _tlv("58", "TH")
    data += "6304"                                    # CRC tag + length
    return data + _crc16(data)


def qr_png(promptpay_id: str, amount: float | None = None) -> bytes:
    img = qrcode.make(payload(promptpay_id, amount), box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()
