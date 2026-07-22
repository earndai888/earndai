"""LINE Messaging API client + ตรวจลายเซ็น webhook"""
import base64
import hashlib
import hmac
import logging

import httpx

from .config import settings

API = "https://api.line.me/v2/bot"
log = logging.getLogger("line_api")


def token_ready() -> bool:
    """token ใช้งานได้จริงไหม (ยังไม่ตั้ง/เป็นข้อความ placeholder = ส่งไม่ได้)"""
    tok = settings.line_channel_access_token
    return bool(tok) and tok != "changeme" and tok.isascii()


def verify_signature(body: bytes, signature: str) -> bool:
    """ตรวจ X-Line-Signature ด้วย HMAC-SHA256 ของ channel secret"""
    mac = hmac.new(settings.line_channel_secret.encode(), body, hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode()
    return hmac.compare_digest(expected, signature or "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.line_channel_access_token}"}


async def reply(reply_token: str, messages: list[dict]) -> None:
    if not token_ready():
        log.warning("ยังไม่ได้ตั้ง LINE_CHANNEL_ACCESS_TOKEN — ตอบกลับไม่ได้")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{API}/message/reply", headers=_headers(),
            json={"replyToken": reply_token, "messages": messages},
        )
        r.raise_for_status()


async def show_loading(chat_id: str, seconds: int = 30) -> None:
    """โชว์ animation "กำลังพิมพ์..." ในแชทระหว่างรอ AI ตอบ (best effort)"""
    if not token_ready():
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{API}/chat/loading/start", headers=_headers(),
                json={"chatId": chat_id, "loadingSeconds": seconds},
            )
    except Exception:
        pass  # แค่ animation — พังก็ไม่เป็นไร


async def push(to: str, messages: list[dict]) -> None:
    """ส่งข้อความหา user, group หรือ room id"""
    if not token_ready():
        log.warning("ยังไม่ได้ตั้ง LINE_CHANNEL_ACCESS_TOKEN — ส่งข้อความไม่ได้")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{API}/message/push", headers=_headers(),
            json={"to": to, "messages": messages},
        )
        r.raise_for_status()


async def verify_liff_token(id_token: str) -> dict | None:
    """ตรวจ LIFF ID token → คืน profile (sub = line_user_id) หรือ None ถ้าไม่ผ่าน"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": settings.line_login_channel_id},
        )
        return r.json() if r.status_code == 200 else None
