"""Brauzer proktoring hodisalaridan xavf balli. Ustoz dashboardi shu yerdan foydalanadi."""
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def proctor_summary(db: Session, attempt_id: str) -> dict:
    rows = db.execute(
        select(KtProctorEvent.event_type, KtProctorEvent.event_source, KtProctorEvent.event_details)
        .where(KtProctorEvent.attempt_id == attempt_id)
    ).all()
    score = 0
    by_type: dict[str, int] = {}
    seen_episodes: set = set()
    for etype, source, details in rows:
        by_type[etype] = by_type.get(etype, 0) + 1
        if source not in COUNTED_SOURCES:
            continue
        if etype in EPISODE_TYPES:
            d = details or {}
            key = (d.get("tab_id"), d.get("episode"))
            if key[1] is not None:
                if key in seen_episodes:
                    continue
                seen_episodes.add(key)
        score += WEIGHTS.get(etype, 0)
    return {"score": score, "level": _level(score), "total": len(rows), "by_type": by_type}

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
}
SOURCE_LABELS = {"detected": "aniq", "inferred": "taxmin", "blocked_attempt": "bloklandi",
                 "unsupported": "qo'llab-quvvatlanmaydi"}


def proctor_timeline(db, attempt_id: str, limit: int = 300) -> list[dict]:
    rows = db.scalars(
        select(KtProctorEvent).where(KtProctorEvent.attempt_id == attempt_id)
        .order_by(KtProctorEvent.event_time, KtProctorEvent.event_id).limit(limit)
    ).all()
    return [{
        "type": r.event_type,
        "label": LABELS.get(r.event_type, r.event_type),
        "source": r.event_source,
        "source_label": SOURCE_LABELS.get(r.event_source, r.event_source),
        "severity": r.severity,
        "at": r.event_time.isoformat(timespec="seconds"),
        "details": r.event_details or {},
    } for r in rows if r.event_type not in NOISE]