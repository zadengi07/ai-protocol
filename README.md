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
