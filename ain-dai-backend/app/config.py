from pydantic_settings import BaseSettings


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
    # AI ชั้นที่ 2 — คุยโต้ตอบผ่าน Gemini ก่อนส่งลิงก์ฟอร์ม
    # (เว้นว่าง = ปิด ใช้ keyword matching อย่างเดียว) — คีย์ฟรีจาก aistudio.google.com/apikey
    gemini_api_key: str = ""
    # alias ชี้รุ่น flash ล่าสุดเสมอ — กันโมเดลเก่าโดนปลดจนบอทพัง
    gemini_model: str = "gemini-flash-latest"
    # โหมดพัฒนา: อนุญาต header X-Debug-User แทนการ verify LIFF token
    dev_mode: bool = True
    # ความถี่ตรวจ auto-release (วินาที)
    auto_release_interval: int = 600

    class Config:
        env_file = ".env"


settings = Settings()
