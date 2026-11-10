"""7-bosqich: talabalar ro'yxatini Excel/CSV dan yuklash."""
import base64
import hashlib
import io
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_roster.db")

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app import proctor_models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KtAttempt, KtExam, KtSetting, KtTeacher  # noqa: E402

Base.metadata.create_all(engine, checkfirst=True)
H = {"X-Teacher-Login": "ro-own", "X-Teacher-Password": "pw"}
O = {"X-Teacher-Login": "ro-oth", "X-Teacher-Password": "pw"}


def _exam():
    with SessionLocal() as db:
        for lg in ("ro-own", "ro-oth"):
            if not db.query(KtTeacher).filter_by(login=lg).first():
                db.add(KtTeacher(login=lg, password_hash=hashlib.sha256(b"pw").hexdigest(), name=lg))
        db.flush()
        own = db.query(KtTeacher).filter_by(login="ro-own").first()
        ex = KtExam(id=uuid.uuid4().hex, slug=f"ro-{uuid.uuid4().hex[:6]}", title="Ro", minutes=80, groups=["25-81"], status="active", teacher_id=own.id)
        db.add(ex); db.commit()
        return ex.id, ex.slug


def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO(); wb.save(b)
    return b.getvalue()


def _up(c, ex, fn, raw, h=H):
    return c.post(f"/api/exam/teacher/exams/{ex}/roster", json={"filename": fn, "content_b64": base64.b64encode(raw).decode()}, headers=h)


def test_126_rows_xlsx_and_csv_and_missing_list():
    ex, slug = _exam()
    rows = [["Guruh", "Ism familiya"]] + [[f"25-8{i % 3 + 1}", f"Talaba Ismi{i} Familiya{i}"] for i in range(126)]
    with TestClient(app) as c:
        r = _up(c, ex, "royxat.xlsx", _xlsx(rows))
        assert r.status_code == 200, r.text
        d = r.json(); assert d["total"] == 126 and d["missing_total"] == 126
        # guruhlar qo'shildi (mavjudi saqlanib qoldi), global ro'yxat ham buzilmadi
        with SessionLocal() as db:
            e = db.get(KtExam, ex)
            assert {"25-81", "25-82", "25-83"} <= set(e.groups)
            assert {"25-79", "25-81", "25-85"} <= set(db.get(KtSetting, "groups").value)
        # talaba kirdi (registr/bo'shliq farqi bilan) -> "kirmaganlar"dan chiqadi
        assert c.post("/api/exam/start", json={"student": "talaba  ISMI0 familiya0", "group": "25-81", "exam_slug": slug}).status_code == 200
        s = c.get(f"/api/exam/teacher/exams/{ex}/roster", headers=H).json()
        assert s["missing_total"] == 125
        # CSV: nuqtali vergul + BOM + bo'sh qator
        csv_raw = ("﻿Guruh;Ism\n25-81;Ali Valiyev\n\n25-82;Vali Aliyev\n").encode("utf-8")
        d = _up(c, ex, "r.csv", csv_raw).json(); assert d["total"] == 2          # yangi ro'yxat eskisini almashtiradi
        # sarlavhasiz CSV
        assert _up(c, ex, "r2.csv", b"25-81,Hasan Husanov\n25-81,Husan Hasanov\n").json()["total"] == 2
        assert c.delete(f"/api/exam/teacher/exams/{ex}/roster", headers=H).status_code == 200
        assert c.get(f"/api/exam/teacher/exams/{ex}/roster", headers=H).json() == {"has_roster": False}


def test_errors_are_explicit_and_all_or_nothing():
    ex, _ = _exam()
    with TestClient(app) as c:
        assert _up(c, ex, "ok.csv", b"Guruh,Ism\n25-81,Birinchi Talaba\n").status_code == 200
        with SessionLocal() as db:
            groups_before = list(db.get(KtExam, ex).groups); glob_before = list(db.get(KtSetting, "groups").value)
        bad = b"Guruh,Ism\n25-81,Yaxshi Talaba\n,Guruhsiz Talaba\n25-99,Al\n25-81,Yaxshi Talaba\n25$,Belgi Xato\n"
        r = _up(c, ex, "bad.csv", bad)
        assert r.status_code == 400
        t = r.json()["detail"]
        for frag in ("Qator 3: guruh bo'sh", "Qator 4: ism-familiya juda qisqa", "Qator 5: takroriy", "Qator 6: guruh nomi noto'g'ri"):
            assert frag in t, t
        s = c.get(f"/api/exam/teacher/exams/{ex}/roster", headers=H).json()
        assert s["total"] == 1 and s["filename"] == "ok.csv"                    # eski ro'yxat o'zgarmagan
        with SessionLocal() as db:
            assert list(db.get(KtExam, ex).groups) == groups_before and list(db.get(KtSetting, "groups").value) == glob_before
        assert _up(c, ex, "x.pdf", b"%PDF").status_code == 400
        assert _up(c, ex, "bos.csv", b"").status_code == 400
        assert _up(c, ex, "nosarlavha.csv", b"nima bu?,world\n").status_code == 400
        assert _up(c, ex, "ok.csv", b"Guruh,Ism\n25-81,Birinchi Talaba\n", O).status_code == 403
        assert c.get(f"/api/exam/teacher/exams/{ex}/roster").status_code == 401
