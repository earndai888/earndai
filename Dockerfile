FROM python:3.13-slim

WORKDIR /app

COPY ain-dai-backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ain-dai-backend/ .

# แพลตฟอร์ม cloud ส่วนใหญ่กำหนดพอร์ตผ่าน env PORT
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
