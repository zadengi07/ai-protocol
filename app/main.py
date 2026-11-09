from contextlib import asynccontextmanager
from datetime import datetime
import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from . import config
from .db import Base, engine
from sqlalchemy import inspect, text
from .models import KtAttempt
from .routers.exam import router as exam_router
from .routers.exam import bootstrap as exam_bootstrap
from .routers.ops import router as ops_router
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
    print("[startup] 1/5 zaxira tekshiruvi...", flush=True)
    _backup_sqlite_before_exam_migration()
    print("[startup] 2/5 jadvallar (create_all)...", flush=True)
    Base.metadata.create_all(engine, checkfirst=True)
    print("[startup] 3/5 ustunlar tekshiruvi...", flush=True)
    # Eski bazaga exam_id ustunini ma'lumotlarni o'chirmasdan qo'shish.
    columns = {c["name"] for c in inspect(engine).get_columns("kt_attempts")}
    if "exam_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_attempts ADD COLUMN exam_id VARCHAR(32) REFERENCES kt_exams(id)"))
    exam_columns = {c["name"] for c in inspect(engine).get_columns("kt_exams")}
    if "groups" not in exam_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN groups JSON NOT NULL DEFAULT '[]'"))
    if "subject_id" not in exam_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN subject_id INTEGER REFERENCES kt_subjects(id)"))
    if "questions" not in exam_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN questions JSON NOT NULL DEFAULT '[]'"))
    # SuperAdmin/fan: kt_teachers ga role/institution/department ustunlari (ma'lumot yo'qotmasdan).
    teacher_columns = {c["name"] for c in inspect(engine).get_columns("kt_teachers")}
    if "role" not in teacher_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_teachers ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'teacher'"))
    if "institution" not in teacher_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_teachers ADD COLUMN institution VARCHAR(200)"))
    if "department" not in teacher_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_teachers ADD COLUMN department VARCHAR(200)"))
    if "subject_id" not in teacher_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_teachers ADD COLUMN subject_id INTEGER REFERENCES kt_subjects(id)"))
    # Kafedra: kt_subjects ga department_id ustuni (kt_departments jadvali create_all orqali yaratiladi).
    subject_columns = {c["name"] for c in inspect(engine).get_columns("kt_subjects")}
    if "department_id" not in subject_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_subjects ADD COLUMN department_id INTEGER REFERENCES kt_departments(id)"))
    # Imtihon egasi: qaysi ustoz yaratgan/boshqaradi (kt_teacher_subjects jadvali create_all orqali yaratiladi).
    exam_columns = {c["name"] for c in inspect(engine).get_columns("kt_exams")}
    if "teacher_id" not in exam_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE kt_exams ADD COLUMN teacher_id INTEGER REFERENCES kt_teachers(id)"))
    # create_all mavjud jadvalga yangi index qo'shmaydi; eski DB lar uchun ham yaratamiz.
    print("[startup] 4/5 indekslar...", flush=True)
    for index in KtAttempt.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
    print("[startup] 5/5 bootstrap...", flush=True)
    exam_bootstrap()
    print("[startup] tayyor.", flush=True)
    yield


app = FastAPI(title="AiTECH Proctoring API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(exam_router)
app.include_router(ops_router)
app.include_router(proctor_router)


@app.get("/health")
def health():
    return {"status": "ok"}
