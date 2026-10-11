"""Risk Engine — frontend `src/lib/riskEngine.js` bilan bir xil algoritm.

ball = base * conf * (1 - fp_rate) * (1 + log2(takror)) ; 30 soniyalik oynada >=2 xil hodisa bo'lsa +50% bonus.
"""
import math
from dataclasses import dataclass

RULES = {
    "face_disappeared": {"base": 25, "fp": 0.15, "label": "Yuz ko'rinmadi"},
    "multiple_faces": {"base": 35, "fp": 0.10, "label": "Bir nechta yuz"},
    "looking_away": {"base": 10, "fp": 0.30, "label": "Chetga qarash"},
    "looking_down": {"base": 15, "fp": 0.25, "label": "Pastga qarash"},
    "phone_detected": {"base": 30, "fp": 0.08, "label": "Telefon"},
    "book_detected": {"base": 25, "fp": 0.12, "label": "Kitob"},
    "laptop_detected": {"base": 20, "fp": 0.15, "label": "Noutbuk"},
    "tab_switch": {"base": 8, "fp": 0.20, "label": "Tab almashdi"},
    "focus_lost": {"base": 8, "fp": 0.20, "label": "Fokus yo'qoldi"},
    "fullscreen_exit": {"base": 12, "fp": 0.10, "label": "To'liq ekrandan chiqdi"},
    "clipboard_use": {"base": 5, "fp": 0.10, "label": "Nusxa olish / qo'yish"},
}
CORRELATION_WINDOW_S = 30
CORRELATION_FACTOR = 0.5
LEVELS = [(25, "Past"), (50, "O'rta"), (75, "Yuqori"), (100, "Kritik")]


@dataclass
class RiskResult:
    scored: list[dict]
    bonus: int
    total: int

    @property
    def level(self) -> str:
        return level_of(self.total)


def level_of(score: int) -> str:
    return next((n for m, n in LEVELS if score <= m), "Kritik")


def compute_risk(events: list[dict]) -> RiskResult:
    """events: [{id, t, type, conf, fp}]"""
    counts: dict[str, int] = {}
    scored = []
    for e in events:
        if e["fp"]:
            scored.append({**e, "score": 0.0})
            continue
        r = RULES[e["type"]]
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        repeat = 1 + math.log2(counts[e["type"]])
        scored.append({**e, "score": r["base"] * e["conf"] * (1 - r["fp"]) * repeat})

    active = sorted((e for e in scored if not e["fp"]), key=lambda e: e["t"])
    bonus, i = 0.0, 0
    while i < len(active):
        start, group = active[i]["t"], []
        while i < len(active) and active[i]["t"] - start <= CORRELATION_WINDOW_S:
            group.append(active[i])
            i += 1
        if len({e["type"] for e in group}) >= 2:
            bonus += CORRELATION_FACTOR * sum(e["score"] for e in group)

    raw = sum(e["score"] for e in active)
    return RiskResult(scored=scored, bonus=round(bonus), total=min(100, round(raw + bonus)))
