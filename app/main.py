from contextlib import asynccontextmanager
from datetime import datetime
import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import config
from .db import Base, engine
from sqlalchemy import inspect, text
from .models import KtAttempt
from .routers.exam_routes import router as exam_router
from .routers.kt import router as kt_router
from .routers.kt import bootstrap as kt_bootstrap
from .routers.proctor import router as proctor_router  # yangi: brauzer proktoring hodisalari


def _backup_sqlite_before_exam_migration() -> None:
    """SQLite bazasini exam_id migratsiyasidan oldin yonma-yon zaxiralaydi."""
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        return
    inspector = inspect(engine)
    if "kt_attempts" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("kt_attempts")}
    if "exam_id" in columns:
        return
    source_path = engine.url.database
    backup_path = f"{source_path}.pre-multiexam-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Avval eski bazaning zaxira nusxasi, undan keyin sxema migratsiyasi.
    _backup_sqlite_before_exam_migration()
    Base.metadata.create_all(engine, checkfirst=True)
    # Eski bazaga exam_id ustunini ma'lumotlarni o'chirmasdan qo'shish.
    columns = {c["name"] for c in inspect(engine).get_columns("kt_attempts")}
    if "exam_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_attempts ADD COLUMN exam_id VARCHAR(32) REFERENCES kt_exams(id)"))
    exam_columns = {c["name"] for c in inspect(engine).get_columns("kt_exams")}
    if "groups" not in exam_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN groups JSON NOT NULL DEFAULT '[]'"))
    # create_all mavjud jadvalga yangi index qo'shmaydi; eski DB lar uchun ham yaratamiz.
    for index in KtAttempt.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
    kt_bootstrap()
    yield


app = FastAPI(title="AiTECH Proctoring API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(exam_router)
app.include_router(kt_router)
app.include_router(proctor_router)


@app.get("/health")
def health():
    return {"status": "ok"}
