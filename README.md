# AiTECH Proctoring API (FastAPI)

## Ishga tushirish
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- Swagger: http://localhost:8000/docs
- Birinchi ishga tushishda baza avtomatik yaratiladi va `mock.js` ga mos namunaviy ma'lumot (24 talaba, 8 imtihon, sessiyalar) yoziladi.
- Testlar: `python -m pytest -q`
- Sozlamalar: `.env.example` (`API_KEY` o'rnatilsa, har so'rovda `X-API-Key` sarlavhasi kerak).

## Endpointlar (`/api/v1`)
| Metod | Yo'l | Vazifa |
|---|---|---|
| POST | /sessions | Yangi sessiya boshlash |
| GET | /sessions?status=active | Sessiyalar (monitoring) |
| GET | /sessions/{id} | Sessiya tafsiloti |
| POST | /sessions/{id}/finish | Yakunlash |
| GET | /sessions/{id}/events | Eventlar (ball bilan) |
| POST | /sessions/{id}/events | Event qo'shish |
| PATCH | /sessions/{id}/events/{eid} | FP belgilash `{"fp": true}` |
| GET | /sessions/{id}/report | AI hisobot |
| POST | /sessions/{id}/decision | Proktor qarori |
| GET/POST | /students | Talabalar |
| GET/POST | /exams | Imtihonlar |
| GET | /analytics/overview | Dashboard statistikasi |

Risk hisobi serverda (`app/risk.py`) — frontend `riskEngine.js` bilan bir xil formula.

## Frontendni ulash
`.env` ga `VITE_API_URL=http://localhost:8000/api/v1` qo'ying, `src/lib/api.js` dan foydalaning.
Event turlari: `face_disappeared, multiple_faces, looking_away, looking_down, phone_detected, book_detected, laptop_detected, tab_switch, focus_lost, fullscreen_exit, clipboard_use`.


## KT imtihoni: davomiylik va umumiy deadline

Ustoz kabinetida **Imtihonni boshlash** bosilganda davomiylik (1–300 butun daqiqa) kiritiladi va tasdiqlanadi. Backend imtihon boshlangan paytda yagona `started_at` va `deadline` ni saqlaydi. Keyin kirgan barcha talabalar shu deadline bilan ishlaydi; ularning shaxsiy 80 daqiqasi qaytadan boshlanmaydi.

Mavjud Neon bazasida `kt_attempts.deadline` indeksi ilova ishga tushganda `checkfirst` bilan yaratiladi. Ma'lumotlarni o'chirish yoki qayta yaratish talab qilinmaydi.

## Production environment variables

Backend hosting:
- `DATABASE_URL` — Neon PostgreSQL connection string (server tomonda saqlang).
- `KT_DATA_KEY` — mavjud `backend qismi/.kt_key` faylidagi Fernet kalitining qiymati. Uni hosting secret/environment variable sifatida kiriting; repozitoriyga yubormang.
- `CORS_ORIGINS` — Vercel frontend domeni, masalan `https://your-project.vercel.app`.

Vercel frontend:
- `VITE_API_URL` — backend API bazaviy URL, masalan `https://your-backend.example.com` (oxirida `/api/kt` qo'shmang).

## Load test (faqat staging bazada)

```bash
cd "backend qismi"
pip install -r requirements-loadtest.txt
locust -f loadtest/locustfile.py --host https://YOUR-STAGING-BACKEND
```

Brauzerda Locust UI ochilgach, **150 users** va bosqichma-bosqich spawn rate kiriting. Avval ustoz kabinetidan staging imtihonini oching. Test noyob talaba urinishlari va javob yozuvlarini yaratadi; production bazada ishlatmang. Bu test 150 parallel userni taqlid qiladi, ammo natijani faqat haqiqiy Neon + backend staging muhitida o'lchash mumkin.

**Xavfsizlik eslatmasi:** yangilangan ZIP ichiga maxfiy `.kt_key` fayli ataylab qo‘shilmadi. Asl loyihangizdagi `backend qismi/.kt_key` faylini saqlang va lokal ishga tushirishda shu joyga qaytaring yoki uning qiymatini backend hostingdagi `KT_DATA_KEY` secretiga kiriting. Bu kalit yo‘qolsa, shifrlangan `data.json` savollarini ochib bo‘lmaydi.

## Ustoz profili (v1.6.0)
- `GET /api/kt/teacher/me`: login va ism (ustoz headerlari bilan).
- `POST /api/kt/teacher/password`: body `{old_password, new_password}`. Joriy parol tekshiriladi, yangi parol kamida 8 belgi va eskisidan farqli bo'lishi kerak. Hash mavjud sha256 sxemasi bilan saqlanadi.
- Eslatma: sha256 tuzsiz (salt yo'q). Keyingi bosqichda bcrypt/argon2 ga o'tkazish tavsiya etiladi.
