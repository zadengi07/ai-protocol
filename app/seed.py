"""Frontend `src/data/mock.js` bilan mos namunaviy ma'lumotlar (faqat baza bo'sh bo'lsa)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models

NAMES = ["Aziz Karimov", "Dilnoza Yusupova", "Jasur Toshmatov", "Madina Rahimova", "Sardor Abdullayev", "Nilufar Ergasheva",
         "Bekzod Nazarov", "Shahnoza Qodirova", "Otabek Mirzayev", "Malika Sodiqova", "Jahongir Xolmatov", "Zarina Tursunova",
         "Ulug'bek Saidov", "Feruza Ismoilova", "Doniyor Rustamov", "Kamola Hamidova", "Sanjar Olimov", "Gulnora Aliyeva",
         "Shohruh Normatov", "Laylo Pardayeva", "Behzod Ahmedov", "Nodira Zokirova", "Islom Murodov", "Munisa Bobojonova"]
GROUPS = ["DI-21", "DI-22", "AT-21", "AT-22"]
COMMON = ["looking_away", "looking_away", "looking_down", "looking_down", "tab_switch", "tab_switch", "focus_lost",
          "clipboard_use", "phone_detected", "multiple_faces", "face_disappeared", "fullscreen_exit", "book_detected"]
HIGH = ["phone_detected", "looking_down", "multiple_faces", "looking_away"]


def _rng(seed: int):
    s = [(seed & 0xFFFFFFFF) or 1]

    def r():
        s[0] = (s[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return s[0] / 4294967296
    return r


def gen_events(seed: int) -> list[dict]:
    r = _rng(seed)
    n = [0, 0, 1, 2, 3, 4, 6, 9][int(r() * 8)]
    base = 300 + r() * 2700
    cluster = n >= 6
    ev = []
    for i in range(n):
        in_c = cluster and i >= n - 4
        ev.append({"t": base + r() * 25 if in_c else r() * 3500,
                   "type": HIGH[(i - (n - 4)) % len(HIGH)] if in_c else COMMON[int(r() * len(COMMON))],
                   "conf": round(0.6 + r() * 0.4, 2)})
    return sorted(ev, key=lambda e: e["t"])


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(models.Student.id).limit(1)):
        return
    students = []
    for i, name in enumerate(NAMES):
        first = name.split(" ")[0].lower().replace("'", "")
        students.append(models.Student(id=i + 1, name=name, group=GROUPS[i % 4], email=f"{first}{i + 1}@student.uz"))
    db.add_all(students)

    E = models.Exam
    exams = [
        E(id=1, title="Veb dasturlash asoslari", group="DI-21", date="2026-10-08", minutes=60, questions=40, status="Yakunlangan"),
        E(id=2, title="Ma'lumotlar bazasi (SQL)", group="DI-22", date="2026-10-11", minutes=45, questions=30, status="Jarayonda"),
        E(id=3, title="Algoritmlar va ma'lumotlar tuzilmasi", group="AT-21", date="2026-10-14", minutes=90, questions=50, status="Rejalashtirilgan"),
        E(id=4, title="Kompyuter tarmoqlari", group="AT-22", date="2026-10-16", minutes=60, questions=35, status="Rejalashtirilgan"),
        E(id=5, title="Python dasturlash", group="DI-21", date="2026-10-02", minutes=60, questions=40, status="Yakunlangan"),
        E(id=6, title="Operatsion tizimlar", group="DI-22", date="2026-10-06", minutes=60, questions=40, status="Yakunlangan"),
        E(id=7, title="Diskret matematika", group="AT-21", date="2026-10-07", minutes=60, questions=30, status="Yakunlangan"),
        E(id=8, title="Axborot xavfsizligi", group="AT-22", date="2026-10-09", minutes=60, questions=35, status="Yakunlangan"),
    ]
    db.add_all(exams)
    db.flush()

    finished_exam = {"DI-21": exams[0], "DI-22": exams[5], "AT-21": exams[6], "AT-22": exams[7]}
    now = datetime.now(timezone.utc)
    for s in students:
        ex = finished_exam[s.group]
        start = now - timedelta(days=s.id % 7, hours=s.id % 5)
        sess = models.ExamSession(student_id=s.id, exam_id=ex.id, status="finished", started_at=start,
                                  finished_at=start + timedelta(minutes=ex.minutes))
        db.add(sess)
        db.flush()
        db.add_all(models.Event(session_id=sess.id, t=round(e["t"], 1), type=e["type"], conf=e["conf"])
                   for e in gen_events(s.id * 97))
        if s.group == "DI-22":  # hozir jarayonda bo'lgan SQL imtihoni
            live = models.ExamSession(student_id=s.id, exam_id=2, status="active", started_at=now - timedelta(minutes=15))
            db.add(live)
    db.commit()
