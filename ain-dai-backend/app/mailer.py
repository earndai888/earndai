"""ส่งอีเมล (best-effort) — ใช้ส่งใบเสร็จ

ตั้งค่า SMTP_* ใน env ถึงจะส่งจริง ไม่ตั้ง = ข้ามไปเฉยๆ (ใช้ใบเสร็จทาง LINE แทน)
รันใน thread แยกเพื่อไม่ให้ block event loop
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("mailer")


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user)


def _send_sync(to: str, subject: str, body: str,
               attachment: tuple[str, bytes, str] | None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        filename, data, mimetype = attachment
        maintype, _, subtype = mimetype.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        s.starttls()
        s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


async def send(to: str, subject: str, body: str,
               attachment: tuple[str, bytes, str] | None = None) -> bool:
    """คืน True ถ้าส่งสำเร็จ, False ถ้าไม่ได้ตั้งค่า/ส่งไม่สำเร็จ (ไม่ throw)"""
    if not configured() or not to:
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body, attachment)
        return True
    except Exception:
        log.exception("ส่งอีเมลไม่สำเร็จ: %s", to)
        return False
