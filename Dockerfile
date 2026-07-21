FROM python:3.13-slim

WORKDIR /app

# ฟอนต์ไทย — ใช้พิมพ์ใบ 50 ทวิ (PDF) ให้อ่านภาษาไทยได้
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-thai-tlwg \
 && rm -rf /var/lib/apt/lists/*

COPY ain-dai-backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ain-dai-backend/ .

# แพลตฟอร์ม cloud ส่วนใหญ่กำหนดพอร์ตผ่าน env PORT
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
