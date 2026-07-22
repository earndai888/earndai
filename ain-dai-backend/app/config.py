from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env อยู่ที่ราก ain-dai-backend — อ้างแบบ absolute เผื่อ cwd ไม่ตรง
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # LINE Messaging API (จาก LINE Developers Console)
    line_channel_secret: str = "changeme"
    line_channel_access_token: str = "changeme"
    # LIFF
    liff_id: str = "0000000000-xxxxxxxx"
    line_login_channel_id: str = "0000000000"
    # Database
    database_url: str = "postgresql://aindai:aindai@localhost:5432/aindai"
    # PromptPay ของแพลตฟอร์ม (เบอร์มือถือ 10 หลัก หรือเลขผู้เสียภาษี 13 หลัก)
    # เงิน escrow จะเข้าบัญชีนี้ — ตั้งเป็นของจริงใน .env ก่อนใช้งาน
    promptpay_id: str = "0899999999"
    # อำเภอนำร่อง — meta จะแสดงเฉพาะตำบลในอำเภอนี้ (เว้นว่าง = ทุกตำบล)
    pilot_amphoe: str = "กันทรลักษ์"
    # รหัสเข้าหน้าแอดมิน — เว้นว่าง = ปิดหน้าแอดมินทั้งหมด (ต้องตั้งค่าเองก่อนใช้)
    admin_token: str = ""
    # ข้อมูลผู้มีหน้าที่หักภาษี ณ ที่จ่าย — ใช้พิมพ์บนใบ 50 ทวิ
    company_name: str = "เอิ้นได้"
    company_tax_id: str = ""
    company_address: str = ""
    # AI ชั้นที่ 2 — คุยโต้ตอบผ่าน Gemini ก่อนส่งลิงก์ฟอร์ม
    # (เว้นว่าง = ปิด ใช้ keyword matching อย่างเดียว) — คีย์ฟรีจาก aistudio.google.com/apikey
    gemini_api_key: str = ""
    # flash-lite = เร็วสุด เหมาะกับแชท (ปิด thinking ในโค้ดเพื่อความไว)
    gemini_model: str = "gemini-flash-lite-latest"
    # โหมดพัฒนา: อนุญาต header X-Debug-User แทนการ verify LIFF token
    # (production ต้องเป็น false — เปิดเฉพาะตอนพัฒนาในเครื่อง)
    dev_mode: bool = False
    # ความถี่ตรวจ auto-release (วินาที)
    auto_release_interval: int = 600

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")


settings = Settings()
