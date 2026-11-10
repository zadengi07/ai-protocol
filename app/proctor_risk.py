"""Brauzer proktoring hodisalaridan xavf balli. Ustoz dashboardi shu yerdan foydalanadi."""
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from .proctor_models import KtProctorEvent

# Har bir turdagi hodisa uchun ball. inferred / unsupported hodisalar ballga kirmaydi.
WEIGHTS = {
    "copy": 10, "cut": 10, "paste": 12, "contextmenu": 3, "selectstart": 3, "dragstart": 3,
    "shortcut_select_all": 5, "shortcut_copy": 10, "shortcut_cut": 10, "shortcut_paste": 12,
    "shortcut_ctrl_insert": 10, "shortcut_shift_insert": 12, "shortcut_shift_delete": 10,
    "devtools_shortcut": 20, "view_source_shortcut": 20, "save_shortcut": 5, "print_shortcut": 10,
    "print_attempt": 10, "screenshot_key": 10,
    "window_blur": 8, "tab_hidden": 8,          # bitta "chetga chiqish" davri faqat bir marta hisoblanadi
    "fullscreen_exit": 12, "multi_tab_detected": 25,
}
EPISODE_TYPES = {"window_blur", "tab_hidden"}
COUNTED_SOURCES = {"detected", "blocked_attempt"}


def _level(score: int) -> str:
    return "past" if score < 30 else ("o'rta" if score < 60 else ("yuqori" if score < 100 else "kritik"))


def proctor_rows_bulk(db: Session, attempt_ids: list, scoring_only: bool = False) -> dict:
    """Bir nechta urinish uchun proktoring qatorlarini BITTA so'rovda oladi: {attempt_id: [rows]}.
    scoring_only=True: faqat ball keltiradigan (WEIGHTS) va hisobga olinadigan manbali qatorlar — ro'yxat/summary uchun yetarli,
    ball bir xil chiqadi; hodisalar ro'yxati kerak joylarda (monitor, bitta talaba) False."""
    out: dict = {}
    if not attempt_ids:
        return out
    # Ball hisoblash uchun faqat kerakli ustunlar (page_url, brauzer, OS kabi og'ir maydonlar o'qilmaydi)
    rows = db.scalars(
        select(KtProctorEvent)
        .options(load_only(KtProctorEvent.event_id, KtProctorEvent.attempt_id, KtProctorEvent.event_type,
                           KtProctorEvent.event_time, KtProctorEvent.event_source, KtProctorEvent.event_details,
                           KtProctorEvent.severity, KtProctorEvent.justified))
        .where(KtProctorEvent.attempt_id.in_(attempt_ids))
        .where(*( [KtProctorEvent.event_type.in_(list(WEIGHTS)), KtProctorEvent.event_source.in_(list(COUNTED_SOURCES))] if scoring_only else [] ))
        .order_by(KtProctorEvent.event_time, KtProctorEvent.event_id)
    ).all()
    for r in rows:
        out.setdefault(r.attempt_id, []).append(r)
    return out


def _utc(dt):
    """Belgisiz (naive) vaqt — UTC deb olinadi, brauzer uni mahalliy vaqt deb adashmasligi uchun."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _score_rows(rows):
    """Ball va qaysi qator qancha ball qo'shgani: ({indeks: ball}, jami). "Asossiz" (justified=False) qatorlar kirmaydi."""
    pts: dict[int, int] = {}
    seen_episodes: set = set()
    for i, r in enumerate(rows):
        if getattr(r, "justified", None) is False or r.event_source not in COUNTED_SOURCES:
            continue
        if r.event_type in EPISODE_TYPES:
            d = r.event_details or {}
            key = (d.get("tab_id"), d.get("episode"))
            if key[1] is not None:
                if key in seen_episodes:
                    continue
                seen_episodes.add(key)
        w = WEIGHTS.get(r.event_type, 0)
        if w:
            pts[i] = w
    return pts, sum(pts.values())


def proctor_summary_from(rows) -> dict:
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r.event_type] = by_type.get(r.event_type, 0) + 1
    pts, score = _score_rows(rows)
    breakdown: dict[str, dict] = {}
    for i, w in pts.items():
        b = breakdown.setdefault(rows[i].event_type, {"n": 0, "points": 0})
        b["n"] += 1
        b["points"] += w
    excluded = sum(1 for r in rows if getattr(r, "justified", None) is False)
    return {"score": score, "level": _level(score), "total": len(rows), "by_type": by_type,
            "breakdown": breakdown, "excluded": excluded}


def proctor_summary(db: Session, attempt_id: str) -> dict:
    rows = db.execute(
        select(KtProctorEvent.event_type, KtProctorEvent.event_source, KtProctorEvent.event_details, KtProctorEvent.justified)
        .where(KtProctorEvent.attempt_id == attempt_id)
    ).all()
    return proctor_summary_from(rows)

NOISE = {"monitor_started", "window_focus", "tab_visible", "page_show"}
LABELS = {
    "window_blur": "Oyna fokusi yo'qoldi", "tab_hidden": "Boshqa tabga o'tdi",
    "copy": "Nusxa olishga urinish", "cut": "Kesishga urinish", "paste": "Joylashtirishga urinish",
    "contextmenu": "O'ng tugma", "selectstart": "Matn belgilashga urinish", "dragstart": "Sudrashga urinish",
    "shortcut_copy": "Ctrl+C", "shortcut_cut": "Ctrl+X", "shortcut_paste": "Ctrl+V",
    "shortcut_select_all": "Ctrl+A", "shortcut_ctrl_insert": "Ctrl+Insert",
    "shortcut_shift_insert": "Shift+Insert", "shortcut_shift_delete": "Shift+Delete",
    "devtools_shortcut": "DevTools shortcut", "view_source_shortcut": "Ctrl+U", "save_shortcut": "Ctrl+S",
    "print_shortcut": "Ctrl+P", "print_attempt": "Chop etish", "screenshot_key": "PrintScreen",
    "fullscreen_exit": "To'liq ekrandan chiqdi", "fullscreen_enter": "To'liq ekranga kirdi",
    "devtools_suspected": "DevTools ehtimoli", "page_reload": "Sahifa qayta yuklandi",
    "before_unload": "Sahifadan chiqishga urinish", "multi_tab_detected": "Bir nechta tab",
    "network_offline": "Internet uzildi", "network_online": "Internet qaytdi",
    "window_resize": "Oyna o'lchami o'zgardi", "orientation_change": "Ekran burildi",
    "rejoin": "Imtihonga qayta kirdi",
}
SOURCE_LABELS = {"detected": "aniq", "inferred": "taxmin", "blocked_attempt": "bloklandi",
                 "unsupported": "qo'llab-quvvatlanmaydi"}


# "Chetga chiqish" turlari va ularning qaytish hodisasi — davomiylikni hisoblash uchun
RETURNS = {"window_blur": "window_focus", "tab_hidden": "tab_visible",
           "network_offline": "network_online", "fullscreen_exit": "fullscreen_enter"}


def _durations(rows) -> dict[int, int]:
    out: dict[int, int] = {}
    opened: dict = {}
    back = {v: k for k, v in RETURNS.items()}
    for i, r in enumerate(rows):
        tab = (r.event_details or {}).get("tab_id")
        if r.event_type in RETURNS:
            opened[(r.event_type, tab)] = i
        elif r.event_type in back:
            j = opened.pop((back[r.event_type], tab), None)
            if j is not None:
                out[j] = max(0, int((r.event_time - rows[j].event_time).total_seconds()))
    return out


def proctor_timeline_from(rows, limit: int = 300) -> list[dict]:
    pts, _ = _score_rows(rows)
    dur = _durations(rows)
    return [{
        "id": r.event_id,
        "type": r.event_type,
        "label": LABELS.get(r.event_type, r.event_type),
        "source": r.event_source,
        "source_label": SOURCE_LABELS.get(r.event_source, r.event_source),
        "severity": r.severity,
        "at": _utc(r.event_time).isoformat(timespec="seconds"),
        "details": r.event_details or {},
        "points": pts.get(i, 0),
        "duration_s": dur.get(i),
        "justified": r.justified,
    } for i, r in enumerate(rows) if r.event_type not in NOISE][:limit]


def proctor_timeline(db, attempt_id: str, limit: int = 300) -> list[dict]:
    rows = db.scalars(
        select(KtProctorEvent).where(KtProctorEvent.attempt_id == attempt_id)
        .order_by(KtProctorEvent.event_time, KtProctorEvent.event_id).limit(limit)
    ).all()
    return proctor_timeline_from(rows, limit)