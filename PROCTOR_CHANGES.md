# AiTECH Proctor — proktoring event tizimi: o'zgarishlar

## O'zgartirilgan MAVJUD fayllar (jami 3 ta, minimal)
| Fayl | O'zgarish | Sabab |
|---|---|---|
| `backend qismi/app/main.py` | +2 qator: `proctor_router` import va `include_router` | Yangi router ulandi |
| `frontend/src/pages/kt/ExamKT.jsx` | import + `useExamGuards(...)` → `useProctorEvents({att, student: name, group}, recordMockEvent)`, "Mock hodisalar jurnali" → "Hodisalar jurnali" | Mock hisoblash haqiqiy kuzatuvchiga almashdi |
| `frontend/src/pages/kt/ExamKTLink.jsx` | xuddi shu 3 ta o'zgarish | `/exam-kt-link` sahifasi ham xuddi shunday |

Diqqat: bu ikki `.jsx` faylning birinchi qatorida `// BU KOD FAYLGA UMUMAN TEGILMASN` izohi bor edi. Vazifangiz (7-band: mock'ni almashtirish) shu fayllarga tegmasdan bajarilmasdi, shuning uchun faqat yuqoridagi 3 ta joy o'zgartirildi, izoh joyida qoldi. Dizayn, javob saqlash, topshirish, taymer — o'zgarmagan. `useExamGuards.js` ham o'zgarmagan (endi KT sahifalari uni chaqirmaydi, aks holda hodisalar ikki marta sanalardi).

## Yangi fayllar
- `backend qismi/app/proctor_models.py` — jadval `kt_proctor_events`
- `backend qismi/app/routers/proctor.py` — endpointlar
- `backend qismi/tests/test_proctor.py` — backend testlari
- `frontend/src/lib/proctorEvents.js` — kuzatuvchi, IndexedDB navbat, batch yuborish
- `frontend/src/hooks/useProctorEvents.js` — React hook
- `frontend/tests/proctor.test.mjs` — kuzatuvchi testlari (Node)

## Muhim qaror: jadval nomi
`proctor_events` nomi bazada ESKI demo oqimi (`ProctoringEvent`, boshqa ustunlar) tomonidan band. Agar yangi jadvalni shu nom bilan yaratsam, `create_all` uni "mavjud" deb o'tkazib yuborib, yangi ustunlar yaratilmasdi. Shuning uchun jadval **`kt_proctor_events`**. API yo'llari so'ralgandek.

## Yangi API
- `POST /api/proctor/events` — bitta event
- `POST /api/proctor/events/batch` — `{attempt_id, events:[...]}` (maks. 100)
- `GET /api/proctor/events/{attempt_id}` — **faqat ustoz** (`X-Teacher-Login`/`X-Teacher-Password`), `?limit=&offset=`

Xavfsizlik: talaba `attempt_id` orqali tanishadi (mavjud `/api/kt/save` bilan bir xil mexanizm). `student_id`, `group_name`, `exam_id` mijozdan emas, bazadagi urinishdan olinadi. Boshqa urinish nomidagi eventlar rad etiladi. O'qish faqat ustozga. `student_id` = urinishdagi ism-familiya (KT'da alohida talaba ID yo'q).

## Migratsiya
Kerak emas: `main.py` lifespan'dagi `create_all(checkfirst=True)` yangi jadvalni o'zi yaratadi. Qo'lda kerak bo'lsa (PostgreSQL) — jadval `KtProctorEvent` modelidan; `attempt_id` → `kt_attempts.id ON DELETE CASCADE`.

## Ishga tushirish
Backend: `pip install -r requirements.txt && uvicorn app.main:app --port 8000`
Frontend: `npm install && npm run dev` (`.env` da `VITE_API_URL`)
Testlar: `python -m pytest tests/test_proctor.py -q` (backend papkasida), `node --test tests/proctor.test.mjs` (frontend papkasida)

## Real va taxminiy eventlar
`event_source`: `detected` | `inferred` (DevTools o'lcham taxmini, page_reload) | `blocked_attempt` (F12, Ctrl+C... bosildi va bekor qilindi) | `unsupported` (brauzer qo'llamaydi). DevTools ochilganini 100% aniqlab bo'lmaydi; taxmin `inferred` + `confirmed:false` bilan saqlanadi.
Bir nechta tab faqat bir xil brauzer profilida (BroadcastChannel) aniqlanadi; boshqa brauzer/qurilma aniqlanmaydi (events'dagi `tab_id`/`browser_name` orqali keyin tahlil qilish mumkin).

## Testlar holati (halol hisobot)
- Frontend kuzatuvchi (Node, soxta window/document/fetch/IndexedDB): **10/10 o'tdi**.
- Backend `test_proctor.py`: **yozildi, lekin ISHGA TUSHIRILMADI** (muhitda fastapi/sqlalchemy yo'q, tarmoq yo'q). Faqat `py_compile` o'tdi.
- `npm run build`: **ISHGA TUSHIRILMADI** (`npm install` tarmoqsiz muhitda tugamadi). JSX o'zgarishlari faqat 3 ta qator, qo'lda tekshirildi.
- Eski `tests/test_api.py` eski `/api/v1` API uchun yozilgan va hozirgi `main.py` bilan mos emas — men tegmadim, baseline sifatida ham ishga tushira olmadim.
- Brauzerda qo'lda tekshirish kerak: haqiqiy fullscreen chiqish, ikki tab, internetni uzish.
