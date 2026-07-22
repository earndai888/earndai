"""เอิ้นได้ backend — รัน: uvicorn app.main:app --reload"""
import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai_chat, catalog, db
from .config import settings
from .routers import admin, jobs, webhook
from .routers.jobs import create_settlement

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aindai")


async def auto_release_loop() -> None:
    """งานสถานะ done ที่ลูกค้าเงียบเกิน auto_release_hours → confirmed + สร้าง settlement"""
    while True:
        try:
            pool = db.get_pool()
            cfg = await pool.fetchrow(
                "SELECT auto_release_hours FROM fee_config ORDER BY effective_from DESC, id DESC LIMIT 1")
            hours = cfg["auto_release_hours"] if cfg else 24
            rows = await pool.fetch(
                """UPDATE jobs SET status = 'confirmed'
                    WHERE status = 'done'
                      AND now() > (SELECT MAX(created_at) FROM payments p WHERE p.job_id = jobs.id)
                                  + make_interval(hours => $1)
                   RETURNING id""",
                hours,
            )
            for r in rows:
                await create_settlement(r["id"])
                log.info("auto-release งาน %s", r["id"])
        except Exception:
            log.exception("auto-release ล้มเหลว")
        await asyncio.sleep(settings.auto_release_interval)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await ai_chat.ensure_table()  # ตารางประวัติแชท AI (สร้างอัตโนมัติถ้ายังไม่มี)
    try:
        await catalog.ensure_subcategories()  # กลุ่มงานย่อยของงานด่วน 24 ชม.
    except Exception:
        log.exception("ซิงก์กลุ่มงานย่อยไม่สำเร็จ — ระบบยังใช้งานได้แบบไม่มีกลุ่มย่อย")
    task = asyncio.create_task(auto_release_loop())
    yield
    task.cancel()
    await db.disconnect()


app = FastAPI(title="เอิ้นได้ API", version="0.1.0", lifespan=lifespan)
app.include_router(webhook.router)
app.include_router(jobs.router)
app.include_router(admin.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "ain-dai", "dev_mode": settings.dev_mode}


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    """หน้าลูกค้า"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/provider", include_in_schema=False)
async def provider_page():
    """หน้าช่าง"""
    return FileResponse(STATIC_DIR / "provider.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """หน้าแอดมิน (ต้องมี ADMIN_TOKEN)"""
    return FileResponse(STATIC_DIR / "admin.html")
